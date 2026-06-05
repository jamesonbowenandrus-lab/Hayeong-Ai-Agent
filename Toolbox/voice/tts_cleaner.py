"""
toolbox/voice/tts_cleaner.py

Text cleaning and prosody utilities for Hayeong's TTS pipeline.
Call clean_for_tts() on any text before passing it to Kokoro or F5-TTS.

Functions:
    clean_for_tts(text)        — strip everything that shouldn't be spoken
    get_prosody_from_state()   — map Brain/state mood to Kokoro speed/pitch params
"""

import re


# ─────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────

# Patterns applied in order — earlier removals prevent later matches from seeing removed text
_PATTERNS = [
    # URLs — never read aloud
    (re.compile(r'https?://\S+'), ''),
    (re.compile(r'www\.\S+'), ''),

    # Code fences with content — strip the fences, keep the content readable
    (re.compile(r'```[a-zA-Z]*\n?(.*?)```', re.DOTALL), r'\1'),

    # Inline code — `value` → value
    (re.compile(r'`([^`]+)`'), r'\1'),

    # Markdown bold/italic — **text** → text, *text* → text, _text_ → text
    (re.compile(r'\*\*(.+?)\*\*'), r'\1'),
    (re.compile(r'\*(.+?)\*'), r'\1'),
    (re.compile(r'__(.+?)__'), r'\1'),
    (re.compile(r'_(.+?)_'), r'\1'),

    # Markdown headers — ## Title → Title
    (re.compile(r'^#{1,6}\s+', re.MULTILINE), ''),

    # Bracketed stage directions / action labels — [laughs], [pause], [BLENDER TOOL] etc.
    # Remove entirely — they are directions, not content to speak
    (re.compile(r'\[[^\]]{1,40}\]'), ''),

    # Em dash — sentence continues more naturally with a comma pause
    (re.compile(r'\s*—\s*'), ', '),

    # Ellipsis — becomes a natural pause (single comma, TTS handles the rest)
    (re.compile(r'\.{3,}'), ', '),

    # Markdown horizontal rules
    (re.compile(r'^[-*_]{3,}\s*$', re.MULTILINE), ''),

    # Bullet points — "• item" or "- item" → just read the item
    (re.compile(r'^\s*[•\-\*]\s+', re.MULTILINE), ''),

    # Numbered list markers — "1. item" → just read the item
    (re.compile(r'^\s*\d+\.\s+', re.MULTILINE), ''),

    # JSON-like patterns that leaked into speech — { "key": "value" }
    (re.compile(r'\{[^}]{0,200}\}'), ''),

    # Repeated punctuation — "!!!" → "!", "???" → "?"
    (re.compile(r'([!?]){2,}'), r'\1'),

    # Collapse multiple spaces / blank lines into single space
    (re.compile(r'\n{2,}'), ' '),
    (re.compile(r'[ \t]+'), ' '),
]


def clean_for_tts(text: str) -> str:
    """
    Prepare text for TTS synthesis.
    Strips anything that would be read aloud incorrectly.
    When in doubt, removes rather than mangles.
    """
    if not text:
        return ""

    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)

    return result.strip()


# ─────────────────────────────────────────────
# PROSODY FROM STATE
# ─────────────────────────────────────────────

_MOOD_PROSODY_MAP = {
    # mood string → Kokoro-compatible params
    # Only speed is currently used by Kokoro's KPipeline.
    # pitch is included for future use when Kokoro supports it.
    "neutral":   {"speed": 0.88, "pitch": 1.00},
    "calm":      {"speed": 0.85, "pitch": 0.99},
    "warm":      {"speed": 0.85, "pitch": 1.01},
    "engaged":   {"speed": 0.92, "pitch": 1.01},
    "curious":   {"speed": 0.87, "pitch": 1.00},
    "focused":   {"speed": 0.93, "pitch": 0.99},
    "excited":   {"speed": 0.96, "pitch": 1.02},
    "concerned":  {"speed": 0.83, "pitch": 0.99},
    "frustrated": {"speed": 0.93, "pitch": 0.98},
    "uncertain":  {"speed": 0.84, "pitch": 1.00},
    "tired":      {"speed": 0.80, "pitch": 0.97},
}

_DEFAULT_PROSODY = {"speed": 0.88, "pitch": 1.00}


def get_prosody_from_state() -> dict:
    """
    Read Hayeong's current emotional state from Brain/state/core.json
    and return matching Kokoro prosody parameters.
    Falls back to neutral defaults on any failure.
    """
    try:
        from brain.state.core_manager import read
        state  = read()
        # presence_output.emotion is the most current emotional state
        # (set by the presence loop after each LLM response)
        emotion = (
            state.get("presence_output", {}).get("emotion", "")
            or state.get("identity", {}).get("mood", "")
            or "neutral"
        )
        return _MOOD_PROSODY_MAP.get(emotion.lower(), _DEFAULT_PROSODY)
    except Exception:
        return _DEFAULT_PROSODY
