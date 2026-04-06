# voice_client_local.py
# Desktop client for Hayeong's voice server.
# Connects to voice_server.py over localhost WebSocket.
#
# This is the local replacement for terminal voice.
# The phone app (Phase 10) connects to the same server the same way —
# just over Tailscale instead of localhost.
#
# TWO MODES:
#   PTT    — hold Right Shift to speak, release to send (default)
#   TOGGLE — press Right Shift once to start, once to stop
#   Switch:  press F8 mid-session
#   Quit:    press F9 or Ctrl+C
#
# INSTALL:
#   pip install websockets pynput sounddevice numpy scipy
#
# RUN:
#   Make sure voice_server.py is running first, then:
#   python voice_client_local.py
#
#   Or start both together via start_hayeong.bat

import asyncio
import json
import sys
import tempfile
import threading
import time

import numpy as np
import sounddevice as sd
import websockets
from scipy.io.wavfile import write as wav_write
from pynput import keyboard

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

SERVER_URI    = "ws://localhost:8765/ws/voice"
SAMPLE_RATE   = 16000      # must match voice_server expectation
INPUT_DEVICE  = 3          # HyperX QuadCast S — change if your device differs
OUTPUT_DEVICE = 6          # SteelSeries Sonar — change if your device differs
OUTPUT_SR     = 24000      # F5-TTS native output rate

# ── Key bindings ──
# PTT_KEY:    hold to speak, release to send (default: Right Shift)
# TOGGLE_KEY: press once to start listening, press again to stop
#             Separated from PTT so right shift stays free for gaming/Discord
# QUIT_KEY:   exit the client
PTT_KEY         = keyboard.Key.shift_r   # hold to talk
TOGGLE_KEY      = keyboard.Key.f7        # press once = start, again = stop
MODE_SWITCH_KEY = keyboard.Key.f8        # switch between PTT and TOGGLE mode
QUIT_KEY        = keyboard.Key.f9        # exit

CHUNK_SECONDS    = 0.3      # recording chunk size
MAX_RECORD_SECS  = 15       # hard cap per utterance
SILENCE_SECS     = 2.0      # TOGGLE mode: stop after this much silence (was 1.2 — too aggressive)
MIN_RECORD_SECS  = 1.5      # always record at least this long before silence check fires
VOLUME_THRESHOLD = 0.006    # slightly lower than before — more sensitive to quiet speech

# ─────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────

def get_volume(audio: np.ndarray) -> float:
    return float(np.abs(audio).mean())

def play_audio_chunks(chunks: list[bytes]):
    """
    Reassemble and play streamed int16 audio chunks from the server.
    Converts back to float32 for sounddevice.
    """
    if not chunks:
        return
    combined_int16 = np.frombuffer(b"".join(chunks), dtype=np.int16)
    audio_float    = combined_int16.astype(np.float32) / 32767.0

    # Reshape to stereo if even number of samples (server sends stereo)
    if len(audio_float) % 2 == 0:
        try:
            audio_float = audio_float.reshape(-1, 2)
        except ValueError:
            pass  # stay mono if reshape fails

    try:
        sd.play(audio_float, samplerate=OUTPUT_SR, device=OUTPUT_DEVICE)
        sd.wait()
        time.sleep(0.1)  # hardware buffer tail
    except Exception as e:
        print(f"⚠️  Playback error: {e}")


# ─────────────────────────────────────────────
# CLIENT STATE
# ─────────────────────────────────────────────

class VoiceClient:
    MODE_PTT    = "ptt"
    MODE_TOGGLE = "toggle"

    def __init__(self):
        self.mode          = self.MODE_PTT
        self.ptt_held      = False
        self.toggle_active = False
        self.recording     = False
        self.should_quit   = False
        self.ws            = None          # set when connected
        self._send_queue   = asyncio.Queue()
        self._loop         = None          # event loop reference

    # ─────────────────────────────────────────
    # RECORDING — same patterns as voice_ptt.py
    # ─────────────────────────────────────────

    def record_while_held(self) -> bytes | None:
        """PTT: record the entire time the key is held."""
        chunks        = []
        chunk_samples = int(CHUNK_SECONDS * SAMPLE_RATE)
        max_chunks    = int(MAX_RECORD_SECS / CHUNK_SECONDS)
        self.recording = True
        print("🎙️  [PTT] Listening...", end="\r")

        for _ in range(max_chunks):
            if not self.ptt_held:
                break
            chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE,
                           channels=1, device=INPUT_DEVICE)
            sd.wait()
            chunks.append(chunk)

        self.recording = False
        if not chunks:
            return None

        combined = np.concatenate(chunks, axis=0)
        print("🎙️  [PTT] Sending...      ")
        # sd.rec() returns float32 in [-1.0, 1.0]
        # Must scale to int16 range before sending — otherwise Whisper gets near-silence
        return (combined * 32767).astype(np.int16).tobytes()

    def record_until_silence(self) -> bytes | None:
        """TOGGLE: record until silence detected."""
        chunks        = []
        silent_chunks = 0
        max_silent    = int(SILENCE_SECS / CHUNK_SECONDS)
        min_chunks    = int(MIN_RECORD_SECS / CHUNK_SECONDS)  # always record this many first
        max_chunks    = int(MAX_RECORD_SECS / CHUNK_SECONDS)
        chunk_samples = int(CHUNK_SECONDS * SAMPLE_RATE)
        self.recording = True
        print("🎙️  [TOGGLE] Listening...", end="\r")

        for i in range(max_chunks):
            if not self.toggle_active:
                break
            chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE,
                           channels=1, device=INPUT_DEVICE)
            sd.wait()
            chunks.append(chunk)

            # Don't check silence until minimum recording time has passed
            if i < min_chunks:
                continue

            if get_volume(chunk) < VOLUME_THRESHOLD:
                silent_chunks += 1
                if silent_chunks >= max_silent:
                    break
            else:
                silent_chunks = 0

        self.recording = False
        self.toggle_active = False

        if not chunks:
            return None

        combined = np.concatenate(chunks, axis=0)
        print("🎙️  [TOGGLE] Sending...   ")
        # sd.rec() returns float32 in [-1.0, 1.0]
        # Must scale to int16 range before sending — otherwise Whisper gets near-silence
        return (combined * 32767).astype(np.int16).tobytes()

    # ─────────────────────────────────────────
    # SEND HELPERS (thread-safe → event loop)
    # ─────────────────────────────────────────

    def _enqueue(self, coro):
        """Schedule a coroutine on the event loop from a non-async thread."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _send_audio(self, pcm_bytes: bytes):
        if not self.ws:
            return
        await self.ws.send(json.dumps({"type": "audio_start"}))
        # Send in 4KB chunks
        chunk_size = 4096
        for i in range(0, len(pcm_bytes), chunk_size):
            await self.ws.send(pcm_bytes[i:i + chunk_size])
            await asyncio.sleep(0)
        await self.ws.send(json.dumps({"type": "audio_end"}))

    # ─────────────────────────────────────────
    # KEY LISTENERS (run in pynput thread)
    # ─────────────────────────────────────────

    def on_press(self, key):
        if key == MODE_SWITCH_KEY:
            self.mode = self.MODE_TOGGLE if self.mode == self.MODE_PTT else self.MODE_PTT
            print(f"\n🔄 Switched to {self.mode.upper()} mode")
            return

        if key == QUIT_KEY:
            print("\n👋 Closing.")
            self.should_quit = True
            return

        # PTT mode — Right Shift held
        if key == PTT_KEY and self.mode == self.MODE_PTT:
            if not self.ptt_held and not self.recording:
                self.ptt_held = True
                t = threading.Thread(target=self._ptt_flow, daemon=True)
                t.start()

        # TOGGLE mode — F7 press: start listening / press again: stop
        if key == TOGGLE_KEY and self.mode == self.MODE_TOGGLE:
            if not self.toggle_active and not self.recording:
                self.toggle_active = True
                t = threading.Thread(target=self._toggle_flow, daemon=True)
                t.start()
            elif self.toggle_active:
                self.toggle_active = False
                print("\n🛑 Stopped listening.")

    def on_release(self, key):
        if key == PTT_KEY and self.mode == self.MODE_PTT:
            self.ptt_held = False

    def _ptt_flow(self):
        pcm = self.record_while_held()
        if pcm:
            self._enqueue(self._send_audio(pcm))
        print(f"\n  Ready — hold Right Shift to speak.")

    def _toggle_flow(self):
        pcm = self.record_until_silence()
        if pcm:
            self._enqueue(self._send_audio(pcm))
        print(f"\n  Ready — press F7 to speak.")

    # ─────────────────────────────────────────
    # WEBSOCKET RECEIVER
    # ─────────────────────────────────────────

    async def _receive_loop(self):
        """
        Handles all incoming messages from the server.
        Text messages are JSON control/info.
        Binary messages are audio chunks.
        """
        audio_chunks: list[bytes] = []
        receiving_audio = False

        async for message in self.ws:

            if isinstance(message, bytes):
                if receiving_audio:
                    audio_chunks.append(message)
                continue

            # JSON message
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "transcript":
                print(f"\nYou: {data.get('text', '')}")

            elif msg_type == "thinking":
                print("💭 Hayeong is thinking...", end="\r")
                receiving_audio = False
                audio_chunks    = []

            elif msg_type == "response_text":
                text    = data.get("text", "")
                emotion = data.get("emotion", "neutral")
                print(f"Hayeong [{emotion}]: {text}")
                receiving_audio = True   # audio stream follows

            elif msg_type == "audio_done":
                receiving_audio = False
                if audio_chunks:
                    # Play in thread so we don't block the receive loop
                    chunks_copy = audio_chunks[:]
                    audio_chunks = []
                    t = threading.Thread(
                        target=play_audio_chunks, args=(chunks_copy,), daemon=True
                    )
                    t.start()

            elif msg_type == "error":
                print(f"\n⚠️  Server error: {data.get('message', '')}")

            elif msg_type == "pong":
                pass  # keepalive confirmed

    # ─────────────────────────────────────────
    # MAIN RUN LOOP
    # ─────────────────────────────────────────

    async def run_async(self):
        self._loop = asyncio.get_event_loop()

        print("\n" + "─" * 52)
        print("  Hayeong Voice Client")
        print(f"  Connecting to {SERVER_URI}")
        print("─" * 52)

        try:
            async with websockets.connect(SERVER_URI, ping_interval=20) as ws:
                self.ws = ws
                print("✅ Connected to Hayeong\n")
                print(f"  Mode: {self.mode.upper()}")
                print("  PTT key:     Right Shift (hold to speak)")
                print("  Toggle key:  F7 (press once = listen, again = stop)")
                print("  Mode switch: F8")
                print("  Quit:        F9")
                print("─" * 52)
                print("  Waiting for you...\n")

                # Start keyboard listener in background thread
                listener = keyboard.Listener(
                    on_press=self.on_press,
                    on_release=self.on_release
                )
                listener.start()

                # Receive loop runs until disconnected or quit
                receive_task = asyncio.create_task(self._receive_loop())

                while not self.should_quit:
                    await asyncio.sleep(0.1)

                receive_task.cancel()
                listener.stop()

        except ConnectionRefusedError:
            print(f"\n❌ Could not connect to {SERVER_URI}")
            print("   Make sure voice_server.py is running first.")
            print("   Start it with:  python voice_server.py")
        except Exception as e:
            print(f"\n❌ Connection error: {e}")

    def run(self):
        asyncio.run(self.run_async())


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    client = VoiceClient()
    client.run()