"""
toolbox/voice/voice_tool.py

Registry entry point for explicit voice tasks assigned by the reasoning LLM.
Auto-speak on every response is handled by voice_output.py, not here.

Params:
    action   (str) — "speak" or "test"
    text     (str) — text to speak (action="speak")
    emotion  (str) — voice modulation, default "neutral"
"""

import sys
from pathlib import Path

VOICE_DIR = Path(__file__).parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))


def run(description: str, params: dict) -> str:
    action  = params.get("action", "speak").strip().lower()
    emotion = params.get("emotion", "neutral")

    if action == "speak":
        text = params.get("text", "").strip()
        if not text:
            raise ValueError("No text provided for voice speak action.")
        from toolbox.voice.voice_output import speak_streamed
        speak_streamed(text, emotion=emotion)
        return f"Speaking: {text[:80]}"

    elif action == "test":
        from toolbox.voice.voice_output import speak_streamed
        speak_streamed(
            "Voice system check. If you can hear this, it is working.",
            emotion="neutral",
        )
        return "Voice test triggered."

    else:
        raise ValueError(f"Unknown voice action: '{action}'. Use 'speak' or 'test'.")
