"""
intent_classifier.py
Lightweight routing classifier. Decides which pipeline handles James's input.

Returns: "conversation" | "task" | "ambiguous"

Design rules:
- Never generates responses. Only classifies.
- Fails safe to "conversation" — never block James from talking to Hayeong.
- Rule-based first. LLM upgrade is a drop-in replacement later.
- Called before the presence loop fires — must be fast (< 50ms target).

──────────────────────────────────────────────────────────────────────
FUTURE UPGRADE PATH (do not build yet — document for later)
──────────────────────────────────────────────────────────────────────
When Hayeong has 3-6 months of conversation logs, replace the rule-based
internals below with a call to a small LLM (Qwen 1.5b or 3b) running on
the RX 7900 XTX via ROCm/Ollama on port 11437.

The external interface — classify_safe(message: str) -> RouteDecision —
stays IDENTICAL. No downstream changes needed. The upgrade is internal only.

Fine-tuning that model on Hayeong's conversation logs (logs/conversations/)
makes it far more accurate for her specific interaction patterns. This is the
recommended first fine-tuning project: lower compute than 32b, concrete
measurable benefit, safe to experiment without affecting her core identity.
──────────────────────────────────────────────────────────────────────
"""

import re
from typing import Literal

RouteDecision = Literal["conversation", "task", "ambiguous"]

# Keywords that strongly signal task intent
_TASK_KEYWORDS = [
    # Minecraft
    "build", "mine", "craft", "go to", "follow", "farm", "collect",
    "place", "break", "dig", "fight", "explore", "find me",
    # Creative tools
    "render", "generate", "create an image", "make a model",
    "blender", "comfyui", "image of", "3d model",
    # File/system
    "read", "write", "save", "open", "run", "execute",
    "search for", "look up", "check",
    # Database
    "query", "database", "store", "retrieve",
    # Handoffs
    "implement", "handoff", "apply", "install",
]

# Patterns that strongly signal pure conversation
_CONVERSATION_PATTERNS = [
    r"^(hey|hi|hello|yo)\b",
    r"^(yeah|yes|no|ok|okay|sure|thanks|thank you|got it|makes sense)\b",
    r"^(how are you|what do you think|do you|are you|what's your)\b",
    r"^(i was thinking|i feel|i'm|im |i am)\b",
    r"^\?",  # starts with question mark (clarification)
]

_COMPILED_CONV = [re.compile(p, re.IGNORECASE) for p in _CONVERSATION_PATTERNS]


def classify(message: str) -> RouteDecision:
    """
    Classify James's message into a routing decision.
    Falls back to 'conversation' on any error.
    """
    if not message or not message.strip():
        return "conversation"

    msg = message.strip().lower()

    # Strong conversation signals — fast exit
    for pattern in _COMPILED_CONV:
        if pattern.match(msg):
            return "conversation"

    # Very short messages are almost always conversational
    if len(msg.split()) <= 3:
        return "conversation"

    # Task keyword scan
    task_hits = sum(1 for kw in _TASK_KEYWORDS if kw in msg)
    if task_hits >= 2:
        return "task"
    if task_hits == 1:
        return "ambiguous"

    # Default — conversation fast path
    return "conversation"


def classify_safe(message: str) -> RouteDecision:
    """Wrapper that guarantees a return value. Never raises."""
    try:
        return classify(message)
    except Exception:
        return "conversation"
