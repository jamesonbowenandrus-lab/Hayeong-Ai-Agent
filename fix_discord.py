"""
Run this from H:\hayeong\ to restore discord_hayeong.py to the correct version.
Usage: .venv\Scripts\python.exe fix_discord.py
"""
import os

content = r'''# discord_hayeong.py
# Requires: pip install "discord.py[voice]" davey discord-ext-voice-recv edge-tts miniaudio faster-whisper pygame
#
# MIGRATION: py-cord -> discord.py (DAVE/E2EE support)
#   - discord.py 2.7+ with davey handles Discord DAVE E2EE (required March 2026)
#   - py-cord 2.7.1 did not implement DAVE - voice connections rejected with code 4017
#   - Voice receive: discord-ext-voice-recv AudioSink + VoiceRecvClient
#   - discord.Bot -> discord.Client

import discord
from discord.ext import voice_recv
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

# -- TTS: F5-TTS with edge-tts fallback --
try:
    from f5_tts.api import F5TTS as _F5TTS
    _F5_MODEL     = None
    _F5_VOICE_REF = os.path.join(os.path.dirname(__file__), "voice_prep", "samples", "source_5secs.wav")
    _F5_REF_TEXT  = "Before the video starts, I want to make a quick announcement."
    F5TTS_AVAILABLE = os.path.exists(_F5_VOICE_REF)
    if not F5TTS_AVAILABLE:
        print("WARNING: F5-TTS voice ref not found - will fall back to edge-tts")
except ImportError:
    F5TTS_AVAILABLE = False
    print("WARNING: f5_tts not installed - using edge-tts fallback")

if not F5TTS_AVAILABLE:
    import edge_tts

from hayeong_core import (
    build_prompt, chat_with_ai,
    load_identity, load_memory, load_mood,
    save_memory, save_json, adjust_mood_by_context,
    MOOD_FILE,
)

# ---------------------------------------------
# CONFIG
# ---------------------------------------------

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

whisper = WhisperModel("base", compute_type="int8")

EDGE_VOICE       = "en-US-AriaNeural"
EDGE_SPEECH_RATE = "-4%"
EDGE_PITCH       = "+5Hz"

pygame.mixer.init()

DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS    = 2
SILENCE_RMS         = 0.0008
CHUNK_SECONDS       = 5

# ---------------------------------------------
# AUDIO OUTPUT QUEUE
# ---------------------------------------------

audio_queue: asyncio.Queue = asyncio.Queue()


# ---------------------------------------------
# VOICE HANDSHAKE
# ---------------------------------------------

async def wait_for_voice_ready(vc, timeout: float = 15.0) -> bool:
    for _ in range(int(timeout / 0.1)):
        if vc.is_connected():
            print("Voice ready (DAVE E2EE active)")
            return True
        await asyncio.sleep(0.1)
    print(f"WARNING: Voice connection timed out (connected={vc.is_connected()})")
    return False


async def safe_connect(channel: discord.VoiceChannel):
    for attempt, kwargs in enumerate([{}, {"reconnect": True}], 1):
        try:
            vc = await channel.connect(cls=voice_recv.VoiceRecvClient, **kwargs)
            if await wait_for_voice_ready(vc):
                return vc
            print(f"Attempt {attempt}: not ready - {'retrying...' if attempt == 1 else 'giving up.'}")
            if attempt == 1:
                await vc.disconnect(force=True)
                await asyncio.sleep(1)
            else:
                return vc
        except Exception as e:
            print(f"WARNING: Connect attempt {attempt} failed: {e}")
    return None


def get_vc(guild):
    return discord.utils.get(client.voice_clients, guild=guild)


# ---------------------------------------------
# AUDIO SOURCE
# ---------------------------------------------

class MiniaudioSource(discord.AudioSource):
    FRAME_SIZE = 3840

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


# ---------------------------------------------
# PYGAME FALLBACK
# ---------------------------------------------

def _play_pygame_blocking(audio_path: str):
    import time
    try:
        pygame.mixer.music.load(audio_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    except Exception as e:
        print(f"WARNING: pygame error: {e}")


async def play_locally(audio_path: str):
    loop = asyncio.get_event_loop()
    print("Playing locally via pygame...")
    await loop.run_in_executor(None, _play_pygame_blocking, audio_path)


# ---------------------------------------------
# TTS
# ---------------------------------------------

def _generate_f5_blocking(text: str):
    global _F5_MODEL
    try:
        if _F5_MODEL is None:
            print("Loading F5-TTS model...")
            _F5_MODEL = _F5TTS()
            print("F5-TTS model loaded")
        wav, sr, _ = _F5_MODEL.infer(
            ref_file=_F5_VOICE_REF,
            ref_text=_F5_REF_TEXT,
            gen_text=text,
            nfe_step=32,
            speed=0.95,
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
        print(f"WARNING: F5-TTS error: {e}")
        return None


async def generate_tts(text: str):
    if not text.strip():
        return None
    if F5TTS_AVAILABLE:
        loop     = asyncio.get_event_loop()
        wav_path = await loop.run_in_executor(None, _generate_f5_blocking, text)
        if wav_path:
            return wav_path
        print("WARNING: F5-TTS failed - falling back to edge-tts")
    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tts_path = tmp.name
    tmp.close()
    try:
        communicate = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_SPEECH_RATE, pitch=EDGE_PITCH)
        await communicate.save(tts_path)
        return tts_path
    except Exception as e:
        print(f"WARNING: edge-tts error: {e}")
        try:
            os.remove(tts_path)
        except Exception:
            pass
        return None


async def speak_in_discord(vc, text: str):
    if not text.strip():
        return
    audio_path = await generate_tts(text)
    if audio_path:
        await audio_queue.put({"vc": vc, "path": audio_path})


# ---------------------------------------------
# AUDIO PLAYER TASK
# ---------------------------------------------

async def audio_player_task():
    print("Audio player task started")
    while True:
        try:
            item       = await audio_queue.get()
            vc         = item.get("vc")
            audio_path = item.get("path", "")

            if not audio_path or not os.path.exists(audio_path):
                audio_queue.task_done()
                continue

            played = False

            if vc and vc.is_connected():
                try:
                    while vc.is_playing():
                        await asyncio.sleep(0.2)
                    done_event = asyncio.Event()
                    loop       = asyncio.get_event_loop()

                    def _after(err):
                        if err:
                            print(f"WARNING: Playback error: {err}")
                        try:
                            loop.call_soon_threadsafe(done_event.set)
                        except Exception:
                            pass

                    vc.play(MiniaudioSource(audio_path), after=_after)
                    print("Speaking via Discord voice (DAVE E2EE)...")
                    await asyncio.wait_for(done_event.wait(), timeout=30.0)
                    played = True
                except Exception as e:
                    print(f"WARNING: vc.play() failed: {e} - using pygame fallback")

            if not played:
                await play_locally(audio_path)

            try:
                os.remove(audio_path)
            except Exception:
                pass

            audio_queue.task_done()

        except asyncio.CancelledError:
            print("Audio player task stopped")
            break
        except Exception as e:
            print(f"WARNING: audio_player_task error: {e}")


# ---------------------------------------------
# VOICE RECEIVE SINK (discord-ext-voice-recv)
# ---------------------------------------------

class HayeongAudioSink(voice_recv.AudioSink):
    """
    Accumulates decoded PCM audio per user.
    voice_recv calls write(user, data) for every packet.
    The listen loop drains every CHUNK_SECONDS for Whisper.
    """

    def __init__(self):
        super().__init__()
        self._buffers: dict = {}
        self._lock = threading.Lock()

    def wants_opus(self) -> bool:
        return False  # want decoded PCM

    def write(self, user, data: voice_recv.VoiceData):
        user_id = user.id if user else 0
        pcm = data.pcm
        if not pcm:
            return
        with self._lock:
            if user_id not in self._buffers:
                self._buffers[user_id] = io.BytesIO()
            self._buffers[user_id].write(pcm)

    def drain(self) -> dict:
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


listening_tasks: dict = {}
active_sinks:    dict = {}


async def voice_listen_loop(vc, text_channel):
    guild_id = vc.guild.id
    print(f"Listen loop started: {vc.channel.name}")

    if not await wait_for_voice_ready(vc, timeout=15.0):
        print("WARNING: Listen loop: voice not ready - voice input disabled.")
        try:
            while vc.is_connected():
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        return

    sink = HayeongAudioSink()
    active_sinks[guild_id] = sink
    try:
        vc.listen(sink)
        print(f"AudioSink active - listening every {CHUNK_SECONDS}s")
    except Exception as e:
        print(f"WARNING: vc.listen() failed: {e}")
        return

    loop = asyncio.get_event_loop()

    try:
        while vc.is_connected():
            await asyncio.sleep(CHUNK_SECONDS)

            chunks = sink.drain()
            if not chunks:
                continue

            for user_id, raw_pcm in chunks.items():
                try:
                    if not raw_pcm or len(raw_pcm) < 200:
                        continue

                    samples = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    rms     = float(np.sqrt(np.mean(samples ** 2)))

                    indicator = "OK" if rms >= SILENCE_RMS else "SILENT"
                    print(f"   [{indicator} rms={rms:.5f}]", end="\r")

                    if rms < SILENCE_RMS:
                        continue

                    print(f"\n   [voice! rms={rms:.4f}] transcribing...")

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

                    print(f"Heard: {text!r}")

                    adjust_mood_by_context(text, mood_state)
                    prompt      = build_prompt(identity, memory, text, dynamic_traits, mood_state)
                    ai_response = await loop.run_in_executor(None, chat_with_ai, prompt)
                    print(f"Hayeong: {ai_response[:80]}...")

                    if text_channel:
                        await text_channel.send(f"*[mic]* {ai_response[:1900]}")

                    await speak_in_discord(vc, ai_response)

                    memory.append({"role": "user", "content": text})
                    memory.append({"role": "AI",   "content": ai_response})
                    save_memory(memory)

                except Exception as e:
                    print(f"WARNING: Audio chunk error: {e}")

    except asyncio.CancelledError:
        print(f"Listen loop cancelled: {vc.channel.name}")
    except Exception as e:
        print(f"WARNING: Listen loop error: {e}")
    finally:
        active_sinks.pop(guild_id, None)
        try:
            vc.stop_listening()
        except Exception:
            pass


async def start_listening(vc, text_channel=None):
    guild_id = vc.guild.id
    await stop_listening(vc)
    task = asyncio.create_task(voice_listen_loop(vc, text_channel or active_text_channel))
    listening_tasks[guild_id] = task


async def stop_listening(vc):
    guild_id = vc.guild.id
    task = listening_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        vc.stop_listening()
    except Exception:
        pass
    active_sinks.pop(guild_id, None)


# ---------------------------------------------
# SHUTDOWN
# ---------------------------------------------

async def shutdown():
    print("Shutting down...")
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


# ---------------------------------------------
# DISCORD EVENTS
# ---------------------------------------------

@client.event
async def on_ready():
    global active_text_channel, _player_task
    _player_task = asyncio.create_task(audio_player_task())
    print(f"\nHayeong online as {client.user}")
    print(f"Owner ID: {OWNER_ID if OWNER_ID else 'NOT SET - add OWNER_DISCORD_ID to .env'}")
    print(f"Voice: discord.py + davey (DAVE E2EE)")
    print(f"Voice receive: discord-ext-voice-recv AudioSink")
    print(f"Text channels: {ALLOWED_TEXT_CHANNELS}")
    print(f"Chunk: {CHUNK_SECONDS}s | Silence threshold: {SILENCE_RMS}\n")

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
                    print(f"Owner in voice - joined: {owner.voice.channel.name}")
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
                print(f"Auto-joined: {after.channel.name}")
                await start_listening(new_vc, active_text_channel)
        elif vc.channel != after.channel:
            await stop_listening(vc)
            await vc.move_to(after.channel)
            print(f"Moved to: {after.channel.name}")
            await asyncio.sleep(1)
            await start_listening(vc, active_text_channel)
    else:
        if vc:
            await stop_listening(vc)
            await vc.disconnect()
            print("Owner left - disconnected")


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
        await message.channel.send("Saving and shutting down...")
        await shutdown()
        return

    if cmd == "!join":
        if message.author.voice and message.author.voice.channel:
            target = message.author.voice.channel
            vc     = get_vc(message.guild)
            if vc is None:
                new_vc = await safe_connect(target)
                if new_vc:
                    await message.channel.send(f"Joined **{target.name}**!")
                    await start_listening(new_vc, message.channel)
            else:
                await stop_listening(vc)
                await vc.move_to(target)
                await asyncio.sleep(1)
                await message.channel.send(f"Moved to **{target.name}**!")
                await start_listening(vc, message.channel)
        else:
            await message.channel.send("Join a voice channel first, then type !join")
        return

    if cmd == "!leave":
        vc = get_vc(message.guild)
        if vc:
            await stop_listening(vc)
            await vc.disconnect()
            await message.channel.send("Left voice.")
        return

    if cmd == "!mood":
        mood_str = " | ".join(f"{k}: {v}" for k, v in mood_state.items())
        await message.channel.send(f"Mood: {mood_str}")
        return

    if cmd == "!status":
        vc        = get_vc(message.guild)
        vc_info   = f"In **{vc.channel.name}**" if vc and vc.is_connected() else "Not in voice"
        listening = "Yes" if message.guild.id in listening_tasks else "No"
        sink      = active_sinks.get(message.guild.id)
        await message.channel.send(
            f"**Hayeong Status**\n"
            f"Voice: {vc_info}\n"
            f"Listening: {listening}\n"
            f"Sink: {'AudioSink active' if sink else 'No sink'}\n"
            f"Voice lib: discord.py + davey (DAVE E2EE)\n"
            f"Queue: {audio_queue.qsize()}"
        )
        return

    if cmd.startswith("!trait "):
        try:
            key, val = cmd[7:].strip().split("=")
            dynamic_traits[key.strip()] = val.strip()
            await message.channel.send(f"OK: {key.strip()} -> {val.strip()}")
        except Exception:
            await message.channel.send("Usage: !trait key=value")
        return

    loop = asyncio.get_event_loop()
    async with message.channel.typing():
        adjust_mood_by_context(user_input, mood_state)
        try:
            prompt      = build_prompt(identity, memory, user_input, dynamic_traits, mood_state)
            ai_response = await loop.run_in_executor(None, chat_with_ai, prompt)
        except Exception as e:
            await message.channel.send(f"Ollama error: {e}")
            return

    for chunk in [ai_response[i:i+1900] for i in range(0, len(ai_response), 1900)]:
        await message.channel.send(chunk)

    vc = get_vc(message.guild)
    await speak_in_discord(vc, ai_response)

    memory.append({"role": "user", "content": user_input})
    memory.append({"role": "AI",   "content": ai_response})
    save_memory(memory)
    save_json(MOOD_FILE, mood_state)


# ---------------------------------------------
# ENTRY POINT
# ---------------------------------------------

client.run(TOKEN)
'''

path = os.path.join(os.path.dirname(__file__), 'discord_hayeong.py')
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f"Written {len(content)} chars to {path}")
