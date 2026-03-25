# discord_hayeong.py
# Requires: pip install "discord.py[voice]" davey edge-tts miniaudio faster-whisper pygame
#
# MIGRATION: py-cord → discord.py (DAVE/E2EE support)
#   - discord.py 2.7+ with davey handles Discord's DAVE E2EE protocol (required March 2026)
#   - py-cord 2.7.1 did not implement DAVE — voice connections were rejected with code 4017
#   - Voice receive rewritten: discord.sinks → discord.AudioSink + vc.listen()
#   - discord.Bot → discord.Client (discord.py doesn't expose Bot at top level)
#   - client.loop deprecated → asyncio.get_event_loop()
#   - Playback gate simplified: ssrc check removed, vc.is_connected() is sufficient with DAVE

import discord
import os
import asyncio
import threading
import tempfile
import io
import wave
import miniaudio
import pygame
import numpy as np
from faster_whisper import WhisperModel
from dotenv import load_dotenv

# ── TTS: F5-TTS (Hayeong's real voice) with edge-tts as fallback ──
try:
    from f5_tts.api import F5TTS as _F5TTS
    _F5_MODEL       = None   # loaded lazily on first use
    _F5_VOICE_REF   = os.path.join(os.path.dirname(__file__),
                                   "voice_prep", "samples", "source_5secs.wav")
    _F5_REF_TEXT    = "Before the video starts, I want to make a quick announcement."
    F5TTS_AVAILABLE = os.path.exists(_F5_VOICE_REF)
    if not F5TTS_AVAILABLE:
        print("⚠️  F5-TTS voice ref file not found — will fall back to edge-tts")
except ImportError:
    F5TTS_AVAILABLE = False
    print("⚠️  f5_tts not installed — using edge-tts fallback")

if not F5TTS_AVAILABLE:
    import edge_tts

# ── Safe import — no audio/voice stack from main ──
from hayeong_core import (
    build_prompt, chat_with_ai,
    load_identity, load_memory, load_mood,
    save_memory, save_json, adjust_mood_by_context,
    MOOD_FILE,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN not found in .env")

OWNER_ID_STR = os.getenv("OWNER_DISCORD_ID", "0").strip()
OWNER_ID     = int(OWNER_ID_STR) if OWNER_ID_STR.isdigit() else 0

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
intents.guilds          = True
intents.members         = True

# discord.py uses discord.Client — not discord.Bot
client = discord.Client(intents=intents)

identity   = load_identity()
memory     = load_memory()
mood_state = load_mood()

dynamic_traits = {
    "personality_intensity": 3,
    "emotional_warmth": 8,
    "tactical_intensity": 6,
    "motivation_style": "gently pushy",
    "teasing_level": "high",
}

ALLOWED_TEXT_CHANNELS = ["hayeong-chat"]

# ── Whisper — runs in a thread executor, never blocks the event loop ──
whisper = WhisperModel("base", compute_type="int8")

# ── edge-tts fallback config ──
EDGE_VOICE       = "en-US-AriaNeural"
EDGE_SPEECH_RATE = "-4%"
EDGE_PITCH       = "+5Hz"

pygame.mixer.init()

# ── Discord always sends 48 kHz stereo 16-bit PCM ──
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS    = 2

# ── Voice activity detection ──
#    RMS threshold — audio below this is treated as silence/noise
SILENCE_RMS = 0.0008

# ── Chunk size for voice processing ──
#    5 seconds gives Whisper much more context → far better transcription
CHUNK_SECONDS = 5

# ─────────────────────────────────────────────
# AUDIO OUTPUT QUEUE
# ─────────────────────────────────────────────

audio_queue: asyncio.Queue = asyncio.Queue()


# ─────────────────────────────────────────────
# VOICE HANDSHAKE HELPERS
# ─────────────────────────────────────────────

async def wait_for_voice_ready(vc: discord.VoiceClient, timeout: float = 15.0) -> bool:
    """
    Poll until the voice connection is ready.
    discord.py + davey handles the DAVE handshake internally —
    we just wait for is_connected() to be True.
    Longer timeout (15s) to give DAVE key exchange time to complete.
    """
    for _ in range(int(timeout / 0.1)):
        if vc.is_connected():
            print(f"✅ Voice ready (DAVE E2EE active)")
            return True
        await asyncio.sleep(0.1)
    print(f"⚠️  Voice connection timed out (connected={vc.is_connected()})")
    return False


async def safe_connect(channel: discord.VoiceChannel) -> "discord.VoiceClient | None":
    """
    Connect to voice and wait for DAVE handshake to complete.
    Retries once if first attempt stalls.
    """
    for attempt, kwargs in enumerate([{}, {"reconnect": True}], 1):
        try:
            vc = await channel.connect(**kwargs)
            if await wait_for_voice_ready(vc):
                return vc
            print(f"🔄 Attempt {attempt}: not ready — "
                  f"{'retrying...' if attempt == 1 else 'giving up.'}")
            if attempt == 1:
                await vc.disconnect(force=True)
                await asyncio.sleep(1)
            else:
                return vc
        except Exception as e:
            print(f"⚠️  Connect attempt {attempt} failed: {e}")
    return None


def get_vc(guild) -> "discord.VoiceClient | None":
    return discord.utils.get(client.voice_clients, guild=guild)


# ─────────────────────────────────────────────
# AUDIO SOURCE (no FFmpeg needed)
# ─────────────────────────────────────────────

class MiniaudioSource(discord.AudioSource):
    FRAME_SIZE = 3840   # 20 ms @ 48 kHz stereo 16-bit

    def __init__(self, audio_path: str):
        decoded = miniaudio.decode_file(
            audio_path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=48000,
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


# ─────────────────────────────────────────────
# PYGAME FALLBACK
# ─────────────────────────────────────────────

def _play_pygame_blocking(audio_path: str):
    import time
    try:
        pygame.mixer.music.load(audio_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print(f"⚠️  pygame error: {e}")


async def play_locally(audio_path: str):
    loop = asyncio.get_event_loop()
    print("🔈 Playing locally via pygame...")
    await loop.run_in_executor(None, _play_pygame_blocking, audio_path)


# ─────────────────────────────────────────────
# TTS GENERATION
# ─────────────────────────────────────────────

def _generate_f5_blocking(text: str) -> "str | None":
    """Generate audio using Hayeong's F5-TTS voice. Runs in a thread executor."""
    global _F5_MODEL
    try:
        if _F5_MODEL is None:
            print("🔊 Loading F5-TTS model (first use — takes a moment)...")
            _F5_MODEL = _F5TTS()
            print("✅ F5-TTS model loaded")

        wav, sr, _ = _F5_MODEL.infer(
            ref_file = _F5_VOICE_REF,
            ref_text = _F5_REF_TEXT,
            gen_text = text,
            nfe_step = 32,
            speed    = 0.95,
        )

        audio = np.array(wav, dtype=np.float32)
        peak  = np.abs(audio).max()
        if peak > 1.0:
            audio = audio / peak

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        from scipy.io.wavfile import write as wav_write
        wav_write(tmp.name, sr, audio)
        return tmp.name

    except Exception as e:
        print(f"⚠️  F5-TTS error: {e}")
        return None


async def generate_tts(text: str) -> "str | None":
    """
    Generate TTS audio and return path to temp file.
    Uses F5-TTS when available, edge-tts as fallback.
    """
    if not text.strip():
        return None

    if F5TTS_AVAILABLE:
        loop     = asyncio.get_event_loop()
        wav_path = await loop.run_in_executor(None, _generate_f5_blocking, text)
        if wav_path:
            return wav_path
        print("⚠️  F5-TTS failed — falling back to edge-tts")

    # edge-tts fallback
    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tts_path = tmp.name
    tmp.close()
    try:
        communicate = edge_tts.Communicate(
            text, EDGE_VOICE, rate=EDGE_SPEECH_RATE, pitch=EDGE_PITCH
        )
        await communicate.save(tts_path)
        return tts_path
    except Exception as e:
        print(f"⚠️  edge-tts error: {e}")
        try:
            os.remove(tts_path)
        except Exception:
            pass
        return None


async def speak_in_discord(vc: "discord.VoiceClient | None", text: str):
    """Generate TTS and enqueue for playback."""
    if not text.strip():
        return
    audio_path = await generate_tts(text)
    if audio_path:
        await audio_queue.put({"vc": vc, "path": audio_path})


# ─────────────────────────────────────────────
# AUDIO PLAYER TASK (background loop)
# ─────────────────────────────────────────────

async def audio_player_task():
    print("🎵 Audio player task started")
    while True:
        try:
            item       = await audio_queue.get()
            vc         = item.get("vc")
            audio_path = item.get("path", "")

            if not audio_path or not os.path.exists(audio_path):
                audio_queue.task_done()
                continue

            played = False

            # Play via Discord voice if connected
            if vc and vc.is_connected():
                try:
                    while vc.is_playing():
                        await asyncio.sleep(0.2)

                    done_event = asyncio.Event()
                    loop       = asyncio.get_event_loop()

                    def _after(err):
                        if err:
                            print(f"⚠️  Playback error: {err}")
                        try:
                            loop.call_soon_threadsafe(done_event.set)
                        except Exception:
                            pass

                    vc.play(MiniaudioSource(audio_path), after=_after)
                    print("🔊 Speaking via Discord voice (DAVE E2EE)...")
                    await asyncio.wait_for(done_event.wait(), timeout=30.0)
                    played = True
                except Exception as e:
                    print(f"⚠️  vc.play() failed: {e} — using pygame fallback")

            if not played:
                await play_locally(audio_path)

            try:
                os.remove(audio_path)
            except Exception:
                pass

            audio_queue.task_done()

        except asyncio.CancelledError:
            print("🎵 Audio player task stopped")
            break
        except Exception as e:
            print(f"⚠️  audio_player_task error: {e}")


# ─────────────────────────────────────────────
# VOICE RECEIVE — AudioSink (discord.py)
#
# discord.py uses AudioSink + vc.listen() instead of
# py-cord's WaveSink + start_recording()/stop_recording().
#
# HayeongAudioSink accumulates raw PCM per user continuously.
# The listen loop drains it every CHUNK_SECONDS and passes
# it to Whisper for transcription — same logic as before,
# just a different collection mechanism.
# ─────────────────────────────────────────────

class HayeongAudioSink(discord.AudioSink):
    """
    Accumulates raw PCM audio per user into per-user BytesIO buffers.
    Thread-safe — discord.py delivers audio from a background thread.
    """

    def __init__(self):
        self._buffers: dict[int, io.BytesIO] = {}
        self._lock = threading.Lock()

    def write(self, data: discord.VoiceData):
        """Called by discord.py for every audio packet received."""
        user_id = data.user.id if data.user else 0
        with self._lock:
            if user_id not in self._buffers:
                self._buffers[user_id] = io.BytesIO()
            self._buffers[user_id].write(data.data)

    def drain(self) -> dict[int, bytes]:
        """
        Atomically drain all buffers and return {user_id: pcm_bytes}.
        Resets buffers for the next chunk.
        """
        with self._lock:
            result = {}
            for user_id, buf in self._buffers.items():
                buf.seek(0)
                data = buf.read()
                if data:
                    result[user_id] = data
            self._buffers.clear()
            return result

    def cleanup(self):
        with self._lock:
            self._buffers.clear()


listening_tasks: dict[int, asyncio.Task] = {}
active_sinks:    dict[int, HayeongAudioSink] = {}


async def voice_listen_loop(vc: discord.VoiceClient, text_channel):
    guild_id = vc.guild.id
    print(f"👂 Listen loop started: {vc.channel.name}")

    # Wait for DAVE handshake before starting to receive
    if not await wait_for_voice_ready(vc, timeout=15.0):
        print("⚠️  Listen loop: voice not ready — voice input disabled.")
        print("   Text chat still works.")
        try:
            while vc.is_connected():
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        return

    # Start the AudioSink — audio flows in continuously
    sink = HayeongAudioSink()
    active_sinks[guild_id] = sink
    try:
        vc.listen(sink)
        print(f"🎙️  AudioSink active — listening for speech every {CHUNK_SECONDS}s")
    except Exception as e:
        print(f"⚠️  vc.listen() failed: {e}")
        return

    loop = asyncio.get_event_loop()

    try:
        while vc.is_connected():
            # Collect audio for CHUNK_SECONDS then process
            await asyncio.sleep(CHUNK_SECONDS)

            chunks = sink.drain()
            if not chunks:
                continue

            for user_id, raw_pcm in chunks.items():
                try:
                    if not raw_pcm or len(raw_pcm) < 200:
                        continue

                    # Convert raw PCM to float for RMS check
                    samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    rms     = float(np.sqrt(np.mean(samples ** 2)))

                    threshold_indicator = "✅" if rms >= SILENCE_RMS else "🔇"
                    print(f"   [{threshold_indicator} rms={rms:.5f} | threshold={SILENCE_RMS}]", end="\r")

                    if rms < SILENCE_RMS:
                        continue

                    print(f"\n   [voice! rms={rms:.4f}] transcribing...")

                    # Write clean WAV for Whisper
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                    tmp.close()
                    with wave.open(tmp.name, "wb") as wf:
                        wf.setnchannels(DISCORD_CHANNELS)
                        wf.setsampwidth(2)
                        wf.setframerate(DISCORD_SAMPLE_RATE)
                        wf.writeframes(raw_pcm)

                    wav_path = tmp.name

                    def _transcribe():
                        segs, _ = whisper.transcribe(wav_path, language="en", vad_filter=True)
                        return "".join(s.text for s in segs).strip()

                    text = await loop.run_in_executor(None, _transcribe)
                    os.remove(wav_path)

                    if not text:
                        print("   (no speech detected)")
                        continue

                    print(f"🎙️  Heard: {text!r}")

                    adjust_mood_by_context(text, mood_state)
                    prompt      = build_prompt(identity, memory, text, dynamic_traits, mood_state)
                    ai_response = await loop.run_in_executor(None, chat_with_ai, prompt)
                    print(f"🤖 Hayeong: {ai_response[:80]}...")

                    if text_channel:
                        await text_channel.send(f"*[🎙️]* {ai_response[:1900]}")

                    await speak_in_discord(vc, ai_response)

                    memory.append({"role": "user", "content": text})
                    memory.append({"role": "AI",   "content": ai_response})
                    save_memory(memory)

                except Exception as e:
                    print(f"⚠️  Audio chunk processing error: {e}")

    except asyncio.CancelledError:
        print(f"👂 Listen loop cancelled: {vc.channel.name}")
    except Exception as e:
        print(f"⚠️  Listen loop error: {e}")
    finally:
        active_sinks.pop(guild_id, None)
        try:
            vc.stop_listening()
        except Exception:
            pass


async def start_listening(vc: discord.VoiceClient, text_channel=None):
    guild_id = vc.guild.id
    await stop_listening(vc)
    task = asyncio.create_task(
        voice_listen_loop(vc, text_channel or active_text_channel)
    )
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
    # Stop the sink if active
    try:
        vc.stop_listening()
    except Exception:
        pass
    active_sinks.pop(guild_id, None)


# ─────────────────────────────────────────────
# SHUTDOWN
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# DISCORD EVENTS
# ─────────────────────────────────────────────

@client.event
async def on_ready():
    global active_text_channel, _player_task

    _player_task = asyncio.create_task(audio_player_task())

    print(f"\n✅ Hayeong online as {client.user}")
    print(f"👤 Owner ID: {OWNER_ID if OWNER_ID else '❌ NOT SET — add OWNER_DISCORD_ID to .env'}")
    print(f"🔐 Voice: discord.py + davey (DAVE E2EE ✅)")
    print(f"🎙️  Voice receive: AudioSink ✅")
    print(f"🔊 Audio: miniaudio ✅ + pygame fallback ✅")
    print(f"💬 Text channels: {ALLOWED_TEXT_CHANNELS}")
    print(f"⏱️  Chunk size: {CHUNK_SECONDS}s  |  Silence threshold: {SILENCE_RMS}\n")

    for guild in client.guilds:
        for ch in guild.text_channels:
            if ch.name in ALLOWED_TEXT_CHANNELS:
                active_text_channel = ch
                break

    # Auto-join owner if already in a voice channel
    if OWNER_ID:
        for guild in client.guilds:
            owner = guild.get_member(OWNER_ID)
            if owner and owner.voice and owner.voice.channel:
                vc = await safe_connect(owner.voice.channel)
                if vc:
                    print(f"🎙️  Owner in voice — joined: {owner.voice.channel.name}")
                    await start_listening(vc, active_text_channel)


@client.event
async def on_voice_state_update(member, before, after):
    if not OWNER_ID or member.id != OWNER_ID:
        return

    vc = get_vc(member.guild)

    if after.channel is not None:
        # Owner joined or moved
        if vc is None:
            new_vc = await safe_connect(after.channel)
            if new_vc:
                print(f"🎙️  Auto-joined: {after.channel.name}")
                await start_listening(new_vc, active_text_channel)
        elif vc.channel != after.channel:
            await stop_listening(vc)
            await vc.move_to(after.channel)
            print(f"🎙️  Moved to: {after.channel.name}")
            await asyncio.sleep(1)
            await start_listening(vc, active_text_channel)
    else:
        # Owner left voice
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

    # ── Bot commands ──
    if cmd == "!exit":
        await message.channel.send("Saving and shutting down... 💤")
        await shutdown()
        return

    if cmd == "!join":
        if message.author.voice and message.author.voice.channel:
            target = message.author.voice.channel
            vc     = get_vc(message.guild)
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
            await message.channel.send("⚠️ Join a voice channel first, then type `!join`.")
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
        vc        = get_vc(message.guild)
        vc_info   = f"In **{vc.channel.name}**" if vc and vc.is_connected() else "Not in voice"
        listening = "Yes 👂" if message.guild.id in listening_tasks else "No"
        sink      = active_sinks.get(message.guild.id)
        sink_info = "AudioSink active ✅" if sink else "No sink"
        await message.channel.send(
            f"**Hayeong Status**\n"
            f"Voice: {vc_info}\n"
            f"Listening: {listening}\n"
            f"Sink: {sink_info}\n"
            f"Voice lib: discord.py + davey (DAVE E2EE)\n"
            f"Queue depth: `{audio_queue.qsize()}`\n"
            f"Owner ID: {'✅' if OWNER_ID else '❌ NOT SET'}"
        )
        return

    if cmd == "!debug":
        vc = get_vc(message.guild)
        if vc:
            keys  = ("ws", "secret_key", "_connected", "sequence", "timestamp")
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

    # ── Main AI response (text) ──
    loop = asyncio.get_event_loop()
    async with message.channel.typing():
        adjust_mood_by_context(user_input, mood_state)
        try:
            prompt      = build_prompt(identity, memory, user_input, dynamic_traits, mood_state)
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


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

client.run(TOKEN)