# voice_io.py
# Voice interface — separate process, fails safely.
#
# If Kokoro, Whisper, sounddevice, or any other voice dependency fails,
# this process exits cleanly in its own window. The brain and text
# interface are completely unaffected.
#
# What this process does:
#   OUTPUT side: polls the brain's output queue and speaks responses via TTS
#   INPUT side:  listens for voice input and writes it to the brain's input queue
#
# All voice imports are inside run() so an import failure only kills this
# process, not anything that imports this file.
#
# Usage:
#   python voice_io.py
#
# Started automatically by start_hayeong.bat in its own window.

import sys
import time

try:
    from hayeong_state import push_input, pop_output, set_interface_status, push_system_alert
except ImportError:
    print("[voice_io] ERROR: hayeong_state.py not found.")
    sys.exit(1)

POLL_INTERVAL  = 0.1   # seconds between queue checks
MAX_RETRIES    = 5
RETRY_DELAY    = 30    # seconds between retry attempts
GIVE_UP_DELAY  = 300   # seconds to wait after giving up before trying again


def notify_brain_of_voice_failure(reason: str):
    try:
        push_system_alert("voice", "failed", reason)
    except Exception:
        pass


def run():
    print("[voice_io] Voice interface starting...")

    # ── All voice imports inside the function ──
    # If any of these fail, we exit cleanly without crashing the brain.
    try:
        import sounddevice as sd
        import numpy as np
        from scipy.io.wavfile import write as wav_write
        import tempfile
    except ImportError as e:
        set_interface_status("voice", "down")
        print(f"[voice_io] Audio dependencies missing ({e}). Voice unavailable.")
        print("[voice_io] Install: pip install sounddevice scipy numpy")
        return

    try:
        import whisper
        _whisper_model = whisper.load_model("base")
        print("[voice_io] Whisper loaded.")
    except Exception as e:
        set_interface_status("voice", "down")
        print(f"[voice_io] Whisper failed ({e}). Voice input unavailable.")
        return

    try:
        from kokoro import KPipeline
        _tts = KPipeline(lang_code="a")
        _tts_available = True
        print("[voice_io] Kokoro TTS loaded.")
    except Exception as e:
        _tts = None
        _tts_available = False
        print(f"[voice_io] Kokoro unavailable ({e}) — will print responses instead of speaking.")

    set_interface_status("voice", "running")
    print("[voice_io] Voice interface running.")
    if not _tts_available:
        print("[voice_io] TTS down — responses will be printed to this window.")

    # ── Configuration ──
    SAMPLE_RATE      = 16000
    VOLUME_THRESHOLD = 0.01
    SILENCE_SECS     = 1.2
    MAX_SECS         = 12
    CHUNK_SECS       = 0.4
    WAKE_WORDS       = ["hayeong", "hey young", "hay young"]

    def speak(text: str):
        if _tts_available and _tts:
            try:
                import soundfile as sf
                samples_list = []
                for _, _, audio in _tts(text, voice="af_heart"):
                    samples_list.append(audio)
                if samples_list:
                    import numpy as _np
                    combined = _np.concatenate(samples_list)
                    sd.play(combined, samplerate=24000)
                    sd.wait()
                    return
            except Exception as e:
                print(f"[voice_io] TTS error: {e}")
        print(f"Hayeong: {text}")

    def get_volume(chunk) -> float:
        return float(np.abs(chunk).mean())

    def record_until_silence() -> str | None:
        chunks        = []
        silent_chunks = 0
        max_silent    = int(SILENCE_SECS / CHUNK_SECS)
        max_total     = int(MAX_SECS / CHUNK_SECS)
        chunk_samples = int(CHUNK_SECS * SAMPLE_RATE)

        for _ in range(max_total):
            chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
            sd.wait()
            chunks.append(chunk)
            if get_volume(chunk) < VOLUME_THRESHOLD:
                silent_chunks += 1
                if silent_chunks >= max_silent:
                    break
            else:
                silent_chunks = 0

        if not chunks:
            return None
        combined = np.concatenate(chunks, axis=0)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_write(f.name, SAMPLE_RATE, combined)
            return f.name

    def transcribe(audio_file: str) -> str:
        try:
            result = _whisper_model.transcribe(audio_file)
            return result.get("text", "").strip()
        except Exception as e:
            print(f"[voice_io] Transcribe error: {e}")
            return ""

    # ── Main voice loop with retry ──
    print("[voice_io] Listening for wake word...")

    consecutive_errors = 0

    while True:
        try:
            # ── OUTPUT: speak any pending responses ──
            resp = pop_output()
            if resp:
                text = resp.get("content", "")
                if text:
                    speak(text)

            # ── INPUT: listen for voice, write to brain queue ──
            chunk = sd.rec(
                int(CHUNK_SECS * SAMPLE_RATE),
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            )
            sd.wait()

            if get_volume(chunk) > VOLUME_THRESHOLD * 3:
                print("[voice_io] Recording...")
                audio_file = record_until_silence()
                if audio_file:
                    text = transcribe(audio_file)
                    import os
                    try: os.unlink(audio_file)
                    except OSError: pass

                    if text and any(w in text.lower() for w in WAKE_WORDS):
                        user_input = text
                        for w in WAKE_WORDS:
                            user_input = user_input.lower().replace(w, "").strip()
                        if user_input:
                            print(f"[voice_io] Heard: {user_input}")
                            push_input(user_input, source="voice")

            consecutive_errors = 0
            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n[voice_io] Voice interface stopped.")
            set_interface_status("voice", "down")
            break
        except Exception as e:
            consecutive_errors += 1
            print(f"[voice_io] Error in voice loop ({consecutive_errors}/{MAX_RETRIES}): {e}")
            set_interface_status("voice", "error")

            if consecutive_errors >= MAX_RETRIES:
                reason = f"Too many consecutive errors. Last: {e}"
                print(f"[voice_io] Giving up after {MAX_RETRIES} errors. Notifying brain.")
                notify_brain_of_voice_failure(reason)
                set_interface_status("voice", "down")
                print(f"[voice_io] Waiting {GIVE_UP_DELAY}s before retrying...")
                time.sleep(GIVE_UP_DELAY)
                consecutive_errors = 0
            else:
                time.sleep(RETRY_DELAY)


if __name__ == "__main__":
    run()
