"""
voice_io.py
Local desktop voice client for Hayeong.

Connects to voice_server.py via WebSocket. Records mic audio,
sends it to the server for processing, receives TTS audio back and plays it.

This is the desktop-local client. The iOS app uses the same WebSocket protocol
over Tailscale — same server, different client, zero refactor needed.

Usage:
  python voice_io.py          # VAD mode — speak naturally
  python voice_io.py --ptt    # PTT mode — hold Right Ctrl to speak
"""

import sys
import asyncio
import json
import time
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print("[voice_io] ERROR: sounddevice not installed — run: pip install sounddevice")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("[voice_io] ERROR: websockets not installed — run: pip install websockets")
    sys.exit(1)

try:
    from hayeong_state import set_interface_status, push_system_alert
except ImportError:
    def set_interface_status(iface, status): pass
    def push_system_alert(iface, status, reason): pass


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

WS_URL          = "ws://localhost:8765/ws/voice"
RECONNECT_DELAY = 3      # seconds between reconnection attempts
SAMPLE_RATE     = 16000  # Hz — Whisper native rate

# VAD configuration — tune these for your mic and environment
VAD_VOLUME_THRESHOLD = 0.018   # RMS threshold for speech detection
                                # HyperX QuadCast S: 0.015–0.025 typical
                                # Lower = more sensitive, Higher = fewer false triggers
VAD_SILENCE_SECS     = 1.0     # Seconds of silence before end-of-speech
VAD_MAX_SECS         = 20      # Maximum single recording length
VAD_CHUNK_SECS       = 0.1     # Smaller chunks = more responsive VAD
VAD_SPEECH_MIN_SECS  = 0.3     # Minimum speech — filters out coughs/chair sounds

USE_PTT = "--ptt" in sys.argv
PTT_KEY = "right ctrl"


# ─────────────────────────────────────────────
# AUDIO CAPTURE
# ─────────────────────────────────────────────

def record_until_silence() -> np.ndarray | None:
    """
    VAD mode: record until silence is detected.
    Returns float32 mono audio array, or None if nothing substantial was captured.
    """
    chunks          = []
    silent_chunks   = 0
    speaking_chunks = 0
    max_silent      = int(VAD_SILENCE_SECS    / VAD_CHUNK_SECS)
    max_total       = int(VAD_MAX_SECS        / VAD_CHUNK_SECS)
    min_speaking    = int(VAD_SPEECH_MIN_SECS / VAD_CHUNK_SECS)
    chunk_samples   = int(VAD_CHUNK_SECS * SAMPLE_RATE)
    is_speaking     = False

    for _ in range(max_total):
        chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE,
                       channels=1, dtype="float32")
        sd.wait()
        volume = float(np.abs(chunk).mean())

        if volume > VAD_VOLUME_THRESHOLD:
            chunks.append(chunk)
            speaking_chunks += 1
            silent_chunks    = 0
            is_speaking      = True
        elif is_speaking:
            # Include trailing silence so Whisper gets natural endings
            chunks.append(chunk)
            silent_chunks += 1
            if silent_chunks >= max_silent:
                break
        # Below threshold, not yet speaking — keep listening, don't record

    if speaking_chunks < min_speaking:
        return None  # Too short — noise burst, not real speech

    return np.concatenate(chunks, axis=0).flatten()


def record_ptt(key: str = PTT_KEY) -> np.ndarray | None:
    """
    PTT mode: record while the key is held. Release to send.
    Returns float32 mono audio array, or None if nothing substantial captured.
    """
    try:
        import keyboard
    except ImportError:
        print("[voice_io] PTT requires 'keyboard' package — run: pip install keyboard")
        time.sleep(1)
        return None

    # Wait for key press (polling — cancellable by task cancellation)
    while not keyboard.is_pressed(key):
        time.sleep(0.02)

    chunks        = []
    chunk_samples = int(VAD_CHUNK_SECS * SAMPLE_RATE)

    while keyboard.is_pressed(key):
        chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE,
                       channels=1, dtype="float32")
        sd.wait()
        chunks.append(chunk)

    if not chunks:
        return None

    audio       = np.concatenate(chunks, axis=0).flatten()
    min_samples = int(VAD_SPEECH_MIN_SECS * SAMPLE_RATE)
    if len(audio) < min_samples:
        return None

    return audio


# ─────────────────────────────────────────────
# PLAYBACK
# ─────────────────────────────────────────────

def _play_audio(pcm_bytes: bytes, sample_rate: int = 24000):
    """Play int16 PCM bytes received from voice_server (24kHz stereo-interleaved)."""
    audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_f32 = audio_i16.astype(np.float32) / 32767.0
    # Server sends stereo-interleaved; reshape so sounddevice plays both channels
    if len(audio_f32) % 2 == 0:
        try:
            audio_f32 = audio_f32.reshape(-1, 2)
        except Exception:
            pass
    sd.play(audio_f32, samplerate=sample_rate)
    sd.wait()


# ─────────────────────────────────────────────
# WEBSOCKET VOICE LOOP
# ─────────────────────────────────────────────

async def _voice_loop(ws):
    """
    Handle a single active WebSocket connection.
    Runs three concurrent tasks:
      - Receive messages from server (print + buffer audio)
      - Play buffered audio
      - Record and send audio when server is idle
    """
    playback_queue = asyncio.Queue()

    # server_ready: set = server is idle, clear = server is processing/speaking
    server_ready = asyncio.Event()
    server_ready.set()

    async def _receive():
        audio_chunks = []
        async for message in ws:
            if isinstance(message, bytes):
                audio_chunks.append(message)
                continue
            try:
                data = json.loads(message)
            except Exception:
                continue
            msg_type = data.get("type", "")

            if msg_type == "transcript":
                print(f"\nYou: {data.get('text', '')}")
            elif msg_type == "thinking":
                print("Hayeong: [thinking...]", end="\r", flush=True)
            elif msg_type == "filler":
                print(f"\rHayeong: {data.get('text', '')}          ", flush=True)
            elif msg_type == "response_text":
                print(f"\rHayeong: {data.get('text', '')}          ", flush=True)
            elif msg_type == "audio_done":
                if audio_chunks:
                    await playback_queue.put(b"".join(audio_chunks))
                    audio_chunks = []
                server_ready.set()   # server finished — ready for next input
            elif msg_type == "error":
                print(f"\n[voice_io] Server error: {data.get('message', '')}")
                server_ready.set()   # unblock recording on error
            elif msg_type == "pong":
                pass

    async def _playback():
        loop = asyncio.get_event_loop()
        while True:
            pcm_bytes = await playback_queue.get()
            await loop.run_in_executor(None, _play_audio, pcm_bytes)

    async def _record_and_send():
        loop      = asyncio.get_event_loop()
        record_fn = record_ptt if USE_PTT else record_until_silence
        if USE_PTT:
            print(f"[voice_io] PTT mode — hold [{PTT_KEY}] to speak")
        else:
            print(f"[voice_io] VAD mode — speak naturally")

        while True:
            # Don't start a new recording while server is responding
            await server_ready.wait()

            audio = await loop.run_in_executor(None, record_fn)
            if audio is None:
                await asyncio.sleep(0.05)
                continue

            # Re-check after recording — server might have become active
            if not server_ready.is_set():
                continue   # discard: server got busy while we were recording

            server_ready.clear()   # mark server as busy before sending

            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
            await ws.send(json.dumps({"type": "audio_start"}))
            await ws.send(pcm)
            await ws.send(json.dumps({"type": "audio_end"}))

    receive_task  = asyncio.create_task(_receive())
    playback_task = asyncio.create_task(_playback())
    send_task     = asyncio.create_task(_record_and_send())

    # Any task completing (normally or by exception) triggers cleanup
    done, pending = await asyncio.wait(
        [receive_task, playback_task, send_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    # Propagate any exception so the outer loop knows why we exited
    for task in done:
        if not task.cancelled() and task.exception():
            raise task.exception()


# ─────────────────────────────────────────────
# RECONNECTION LOOP
# ─────────────────────────────────────────────

async def run_voice_client():
    """
    Outer reconnection loop — keeps the voice interface alive indefinitely.
    Reconnects silently on any connection drop.
    """
    while True:
        try:
            print(f"[voice_io] Connecting to voice server at {WS_URL}...")
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                print("[voice_io] Connected. Voice pipeline active.")
                set_interface_status("voice", "running")
                await _voice_loop(ws)
        except websockets.exceptions.ConnectionClosed:
            print("[voice_io] Connection closed — reconnecting...")
        except ConnectionRefusedError:
            print(f"[voice_io] Voice server not reachable — retrying in {RECONNECT_DELAY}s...")
        except Exception as e:
            print(f"[voice_io] Connection error: {e} — retrying in {RECONNECT_DELAY}s...")

        set_interface_status("voice", "reconnecting")
        await asyncio.sleep(RECONNECT_DELAY)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if USE_PTT:
        try:
            import keyboard
        except ImportError:
            print("[voice_io] PTT mode requires: pip install keyboard")
            sys.exit(1)
        print("[voice_io] PTT mode — install confirmed")

    print("[voice_io] Voice client starting...")
    try:
        asyncio.run(run_voice_client())
    except KeyboardInterrupt:
        print("\n[voice_io] Stopped.")
        set_interface_status("voice", "down")
