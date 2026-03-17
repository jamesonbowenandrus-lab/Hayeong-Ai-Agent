# discord_hayeong.py
# Requires: pip install py-cord edge-tts miniaudio faster-whisper pygame

import discord
import os
import asyncio
import tempfile
import io
import wave
import edge_tts
import miniaudio
import pygame
import numpy as np
from faster_whisper import WhisperModel
from dotenv import load_dotenv
from main import (
    build_prompt, chat_with_ai,
    load_identity, load_memory, load_mood,
    save_memory, save_json, adjust_mood_by_context
)

PYCORD = hasattr(discord, "Bot")
print(f"🔍 Library: {'py-cord ✅' if PYCORD else 'discord.py ⚠️ install py-cord for voice'}")

# -------------------------
# Config
# -------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN not found in .env")

OWNER_ID_STR = os.getenv("OWNER_DISCORD_ID", "0").strip()
OWNER_ID = int(OWNER_ID_STR) if OWNER_ID_STR.isdigit() else 0
MOOD_FILE = "mood.json"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

client = discord.Bot(intents=intents) if PYCORD else discord.Client(intents=intents)

identity    = load_identity()
memory      = load_memory()
mood_state  = load_mood()
dynamic_traits = {
    "personality_intensity": 3,
    "emotional_warmth": 8,
    "tactical_intensity": 6,
    "motivation_style": "gently pushy",
    "teasing_level": "high"
}
ALLOWED_TEXT_CHANNELS = ["hayeong-chat"]

whisper = WhisperModel("base", compute_type="int8")
VOICE        = "en-US-AriaNeural"
SPEECH_RATE  = "-4%"
SPEECH_PITCH = "+5Hz"

pygame.mixer.init()

# -------------------------
# Audio output queue
# All speech goes through here so nothing blocks the event loop.
#
#   Discord message / voice input
#         ↓
#   AI processing  (executor thread — never blocks event loop)
#         ↓
#   audio_queue.put({"vc": vc, "path": mp3})
#         ↓
#   audio_player_task  (background loop)
#     ├─ vc.play()  if ssrc is set (UDP working)
#     └─ pygame     if ssrc is None (UDP blocked / TCP fallback)
# -------------------------
audio_queue: asyncio.Queue = asyncio.Queue()


# -------------------------
# SSRC readiness helpers
# -------------------------
async def wait_for_voice_ready(vc: discord.VoiceClient, timeout: float = 5.0) -> bool:
    """Poll until the voice handshake finishes (ssrc assigned). Returns True on success."""
    for _ in range(int(timeout / 0.1)):
        if vc.is_connected() and getattr(vc, "ssrc", None) is not None:
            print(f"✅ Voice ready — ssrc={vc.ssrc}")
            return True
        await asyncio.sleep(0.1)
    print(f"⚠️ Voice handshake timed out "
          f"(ssrc={getattr(vc, 'ssrc', None)}, connected={vc.is_connected()})")
    return False


async def safe_connect(channel: discord.VoiceChannel) -> discord.VoiceClient | None:
    """
    Connect to voice and wait for the SSRC handshake.
    Retries once with reconnect=True if the first attempt stalls.
    Returns the VoiceClient (possibly without UDP) or None on hard failure.
    """
    for attempt, kwargs in enumerate([{}, {"reconnect": True}], 1):
        try:
            vc = await channel.connect(**kwargs)
            if await wait_for_voice_ready(vc):
                return vc
            print(f"🔄 Attempt {attempt}: SSRC not received — "
                  f"{'retrying...' if attempt == 1 else 'UDP appears blocked on this network.'}")
            if attempt == 1:
                await vc.disconnect(force=True)
                await asyncio.sleep(1)
            else:
                # Return anyway — audio_player_task will use pygame fallback
                return vc
        except Exception as e:
            print(f"⚠️ Connect attempt {attempt} failed: {e}")
    return None

# -------------------------
# MiniaudioSource (no FFmpeg needed)
# -------------------------
class MiniaudioSource(discord.AudioSource):
    FRAME_SIZE = 3840  # 20ms @ 48kHz stereo 16-bit

    def __init__(self, mp3_path: str):
        decoded = miniaudio.decode_file(
            mp3_path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=48000
        )
        self._buffer = io.BytesIO(bytes(decoded.samples))

    def read(self) -> bytes:
        data = self._buffer.read(self.FRAME_SIZE)
        if not data:
            return b""
        if len(data) < self.FRAME_SIZE:
            data += b"\x00" * (self.FRAME_SIZE - len(data))
        return data

    def is_opus(self) -> bool:
        return False


# -------------------------
# Local pygame fallback
# -------------------------
def _play_pygame_blocking(mp3_path: str):
    import time
    try:
        pygame.mixer.music.load(mp3_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print(f"⚠️ pygame error: {e}")

async def play_locally(mp3_path: str):
    loop = asyncio.get_event_loop()
    print("🔈 Playing locally via pygame (UDP unavailable)...")
    await loop.run_in_executor(None, _play_pygame_blocking, mp3_path)


# -------------------------
# TTS generation
# -------------------------
async def generate_tts(text: str) -> str | None:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tts_path = tmp.name
    tmp.close()
    try:
        communicate = edge_tts.Communicate(text, VOICE, rate=SPEECH_RATE, pitch=SPEECH_PITCH)
        await communicate.save(tts_path)
        return tts_path
    except Exception as e:
        print(f"⚠️ TTS generation error: {e}")
        try: os.remove(tts_path)
        except: pass
        return None


# -------------------------
# Audio player background task
# -------------------------
async def audio_player_task():
    print("🎵 Audio player task started")
    while True:
        try:
            item = await audio_queue.get()
            vc: discord.VoiceClient | None = item.get("vc")
            mp3_path: str = item.get("path", "")

            if not mp3_path or not os.path.exists(mp3_path):
                audio_queue.task_done()
                continue

            played = False

            # Use Discord voice only when UDP handshake completed (ssrc is set)
            if vc and vc.is_connected() and getattr(vc, "ssrc", None) is not None:
                try:
                    while vc.is_playing():
                        await asyncio.sleep(0.2)

                    done_event = asyncio.Event()

                    def _after(err):
                        if err:
                            print(f"⚠️ Playback error: {err}")
                        try:
                            client.loop.call_soon_threadsafe(done_event.set)
                        except Exception:
                            pass

                    vc.play(MiniaudioSource(mp3_path), after=_after)
                    print("🔊 Speaking via Discord voice...")
                    await asyncio.wait_for(done_event.wait(), timeout=30.0)
                    played = True
                except Exception as e:
                    print(f"⚠️ vc.play() failed: {e} — using pygame fallback")

            if not played:
                await play_locally(mp3_path)

            try: os.remove(mp3_path)
            except: pass

            audio_queue.task_done()

        except asyncio.CancelledError:
            print("🎵 Audio player task stopped")
            break
        except Exception as e:
            print(f"⚠️ audio_player_task error: {e}")


async def speak_in_discord(vc: discord.VoiceClient | None, text: str):
    """Generate TTS and enqueue for playback."""
    if not text.strip():
        return
    mp3_path = await generate_tts(text)
    if mp3_path:
        await audio_queue.put({"vc": vc, "path": mp3_path})


def get_vc(guild) -> discord.VoiceClient | None:
    return discord.utils.get(client.voice_clients, guild=guild)


# -------------------------
# Voice listen loop
# -------------------------
listening_tasks     = {}
currently_recording = {}
SILENCE_RMS = 0.0008

async def voice_listen_loop(vc: discord.VoiceClient, text_channel):
    guild_id = vc.guild.id
    print(f"👂 Listen loop started: {vc.channel.name}")
    CHUNK_SECONDS = 2

    # Wait for full handshake before attempting to record
    if not await wait_for_voice_ready(vc, timeout=10.0):
        print("⚠️ Listen loop: voice not fully ready — recording disabled (UDP likely blocked)")
        print("   Text chat still works. Voice input unavailable until UDP is unblocked.")
        try:
            while vc.is_connected():
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        return

    try:
        while vc.is_connected():
            chunk_done  = asyncio.Event()
            audio_store = {}

            class ChunkSink(discord.sinks.WaveSink):
                pass

            async def on_chunk_done(sink, channel, *args):
                audio_store["sink"] = sink
                currently_recording[guild_id] = False
                chunk_done.set()

            try:
                vc.start_recording(ChunkSink(), on_chunk_done, text_channel)
                currently_recording[guild_id] = True
            except Exception as e:
                print(f"⚠️ start_recording error: {e} — pausing 10s")
                await asyncio.sleep(10)
                continue

            await asyncio.sleep(CHUNK_SECONDS)

            if currently_recording.get(guild_id, False):
                try:
                    vc.stop_recording()
                except Exception as e:
                    print(f"⚠️ stop_recording error: {e}")
                currently_recording[guild_id] = False

            try:
                await asyncio.wait_for(chunk_done.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                continue

            sink = audio_store.get("sink")
            if not sink or not sink.audio_data:
                continue

            for user_id, audio_data in sink.audio_data.items():
                try:
                    audio_data.file.seek(0)
                    raw = audio_data.file.read()
                    if not raw or len(raw) < 100:
                        continue

                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(samples ** 2)))
                    print(f"   [rms={rms:.4f}]", end="\r")

                    if rms < SILENCE_RMS:
                        continue

                    print(f"\n   [voice! rms={rms:.4f}] transcribing...")

                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                    tmp.close()
                    with wave.open(tmp.name, "wb") as wf:
                        wf.setnchannels(sink.vc.decoder.CHANNELS)
                        wf.setsampwidth(2)
                        wf.setframerate(sink.vc.decoder.SAMPLING_RATE)
                        wf.writeframes(raw)

                    # Whisper in executor — must not block event loop during voice handshake
                    loop = asyncio.get_event_loop()
                    wav_path = tmp.name
                    def _transcribe():
                        segs, _ = whisper.transcribe(wav_path, language="en", vad_filter=True)
                        return "".join(s.text for s in segs).strip()
                    text = await loop.run_in_executor(None, _transcribe)
                    os.remove(wav_path)

                    if not text:
                        print("   (no speech detected)")
                        continue

                    print(f"🎙️ Heard: {text!r}")

                    adjust_mood_by_context(text, mood_state)
                    prompt = build_prompt(identity, memory, text, dynamic_traits, mood_state)
                    ai_response = await loop.run_in_executor(None, chat_with_ai, prompt)
                    print(f"🤖 Hayeong: {ai_response[:80]}...")

                    if text_channel:
                        await text_channel.send(f"*[🎙️]* {ai_response[:1900]}")

                    await speak_in_discord(vc, ai_response)

                    memory.append({"role": "user", "content": text})
                    memory.append({"role": "AI",   "content": ai_response})
                    save_memory(memory)

                except Exception as e:
                    print(f"⚠️ Audio chunk processing error: {e}")

    except asyncio.CancelledError:
        print(f"👂 Listen loop cancelled: {vc.channel.name}")
    except Exception as e:
        print(f"⚠️ Listen loop error: {e}")
    finally:
        currently_recording.pop(guild_id, None)


async def start_listening(vc: discord.VoiceClient, text_channel=None):
    if not PYCORD:
        print("⚠️ Voice listening requires py-cord")
        return
    guild_id = vc.guild.id
    await stop_listening(vc)
    task = asyncio.create_task(voice_listen_loop(vc, text_channel or active_text_channel))
    listening_tasks[guild_id] = task


async def stop_listening(vc: discord.VoiceClient):
    guild_id = vc.guild.id
    task = listening_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if currently_recording.pop(guild_id, False):
        try:
            vc.stop_recording()
        except Exception:
            pass


# -------------------------
# Shutdown
# -------------------------
async def shutdown():
    print("\n🛑 Shutting down...")
    if _player_task and not _player_task.done():
        _player_task.cancel()
    for vc in list(client.voice_clients):
        try:
            await stop_listening(vc)
            await vc.disconnect(force=True)
        except Exception:
            pass
    save_memory(memory)
    save_json(MOOD_FILE, mood_state)
    await client.close()


active_text_channel = None
_player_task        = None

# -------------------------
# Events
# -------------------------
@client.event
async def on_ready():
    global active_text_channel, _player_task

    _player_task = asyncio.create_task(audio_player_task())

    print(f"\n✅ Hayeong online as {client.user}")
    print(f"👤 Owner ID: {OWNER_ID if OWNER_ID else '❌ NOT SET'}")
    print(f"🔧 Audio: miniaudio ✅ + pygame fallback ✅")
    print(f"💬 Text: {ALLOWED_TEXT_CHANNELS}")
    print(f"🎙️  Listening: {'chunked loop ✅' if PYCORD else '❌ needs py-cord'}\n")

    for guild in client.guilds:
        for ch in guild.text_channels:
            if ch.name in ALLOWED_TEXT_CHANNELS:
                active_text_channel = ch
                break

    if OWNER_ID:
        for guild in client.guilds:
            owner = guild.get_member(OWNER_ID)
            if owner and owner.voice and owner.voice.channel:
                vc = await safe_connect(owner.voice.channel)
                if vc:
                    print(f"🎙️ Owner in voice — joined: {owner.voice.channel.name}")
                    await start_listening(vc, active_text_channel)


@client.event
async def on_voice_state_update(member, before, after):
    if not OWNER_ID or member.id != OWNER_ID:
        return

    vc = get_vc(member.guild)

    if after.channel is not None:
        if vc is None:
            new_vc = await safe_connect(after.channel)
            if new_vc:
                print(f"🎙️ Auto-joined: {after.channel.name}")
                await start_listening(new_vc, active_text_channel)
        elif vc.channel != after.channel:
            await stop_listening(vc)
            await vc.move_to(after.channel)
            print(f"🎙️ Moved to: {after.channel.name}")
            await asyncio.sleep(1)
            await start_listening(vc, active_text_channel)
    else:
        if vc:
            await stop_listening(vc)
            await vc.disconnect()
            print("🔇 Owner left — disconnected")


@client.event
async def on_message(message):
    global active_text_channel

    if message.author == client.user:
        return
    if not isinstance(message.channel, discord.TextChannel):
        return
    if message.channel.name not in ALLOWED_TEXT_CHANNELS:
        return

    active_text_channel = message.channel
    user_input = message.content.strip()
    if not user_input:
        return
    cmd = user_input.lower()

    if cmd == "!exit":
        await message.channel.send("Saving and shutting down... 💤")
        await shutdown()
        return

    if cmd == "!join":
        if message.author.voice and message.author.voice.channel:
            target = message.author.voice.channel
            vc = get_vc(message.guild)
            if vc is None:
                new_vc = await safe_connect(target)
                if new_vc:
                    await message.channel.send(f"🎙️ Joined **{target.name}**!")
                    await start_listening(new_vc, message.channel)
            else:
                await stop_listening(vc)
                await vc.move_to(target)
                await asyncio.sleep(1)
                await message.channel.send(f"🎙️ Moved to **{target.name}**!")
                await start_listening(vc, message.channel)
        else:
            await message.channel.send("⚠️ Join a voice channel first!")
        return

    if cmd == "!leave":
        vc = get_vc(message.guild)
        if vc:
            await stop_listening(vc)
            await vc.disconnect()
            await message.channel.send("👋 Left voice.")
        return

    if cmd == "!mood":
        mood_str = " | ".join(f"{k}: {v}" for k, v in mood_state.items())
        await message.channel.send(f"📊 {mood_str}")
        return

    if cmd == "!status":
        vc = get_vc(message.guild)
        vc_info   = f"In **{vc.channel.name}**" if vc and vc.is_connected() else "Not in voice"
        listening = "Yes 👂" if message.guild.id in listening_tasks else "No"
        ssrc_val  = getattr(vc, 'ssrc', None) if vc else None
        udp_ok    = f"✅ (ssrc={ssrc_val})" if ssrc_val is not None else "❌ local audio only"
        await message.channel.send(
            f"**Hayeong Status**\n"
            f"Voice: {vc_info}\n"
            f"Listening: {listening}\n"
            f"UDP: {udp_ok}\n"
            f"Queue depth: `{audio_queue.qsize()}`\n"
            f"Owner ID: {'✅' if OWNER_ID else '❌ NOT SET'}"
        )
        return

    if cmd == "!debug":
        vc = get_vc(message.guild)
        if vc:
            keys = ('ssrc', 'ws', 'udp', 'secret_key', '_connected', 'sequence', 'timestamp')
            lines = "\n".join(
                f"  {k}: {str(getattr(vc, k, 'MISSING'))[:80]}" for k in keys
            )
            await message.channel.send(f"```\n{lines}\n```")
        else:
            await message.channel.send("Not in voice.")
        return

    if cmd.startswith("!trait "):
        try:
            key, val = cmd[7:].strip().split("=")
            dynamic_traits[key.strip()] = val.strip()
            await message.channel.send(f"✅ `{key.strip()}` → `{val.strip()}`")
        except Exception:
            await message.channel.send("⚠️ Usage: `!trait key=value`")
        return

    # ---- Main AI response ----
    loop = asyncio.get_event_loop()
    async with message.channel.typing():
        adjust_mood_by_context(user_input, mood_state)
        try:
            prompt = build_prompt(identity, memory, user_input, dynamic_traits, mood_state)
            ai_response = await loop.run_in_executor(None, chat_with_ai, prompt)
        except Exception as e:
            await message.channel.send(f"⚠️ Ollama error: `{e}`")
            return

    for chunk in [ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)]:
        await message.channel.send(chunk)

    vc = get_vc(message.guild)
    await speak_in_discord(vc, ai_response)

    memory.append({"role": "user", "content": user_input})
    memory.append({"role": "AI",   "content": ai_response})
    save_memory(memory)
    save_json(MOOD_FILE, mood_state)


client.run(TOKEN)