"""
Toolbox/voice/plugin.py

Voice capability plugin. Checks whether Kokoro TTS is available and
writes a voice_active flag to shared state so the reasoning loop knows
whether to apply speech-natural generation mode.

PERSISTENT = True: the voice_active flag must be in state from session
start — the reasoning loop reads it on every tick to decide whether to
add speech mode instructions to its prompts.
"""

import time

PERSISTENT = True

_CHECK_INTERVAL = 30   # recheck capability every 30 seconds
_last_check_at  = 0.0
_voice_capable  = None  # None = not yet checked


def tick():
    """Called every 2 seconds. Rechecks voice capability every 30 seconds."""
    global _last_check_at, _voice_capable

    now = time.time()
    if now - _last_check_at < _CHECK_INTERVAL:
        return
    _last_check_at = now

    capable = _check_voice_capability()

    if capable != _voice_capable:
        _voice_capable = capable
        try:
            from brain.state.core_manager import write_section
            write_section("voice_status", {
                "voice_active": capable,
                "checked_at":   _timestamp(),
            })
        except Exception:
            pass


def get_context_injection(state: dict = None) -> list:
    """No context injection — voice plugin only manages state flags."""
    return []


def _check_voice_capability() -> bool:
    """True if Kokoro TTS appears to be available in this process."""
    try:
        from toolbox.voice.voice import KOKORO_AVAILABLE
        return KOKORO_AVAILABLE
    except Exception:
        return False


def _timestamp() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")
