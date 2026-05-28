"""
self_review.py
Optional self-review pass before Hayeong finalizes a response.

Sends a short prompt to the model asking it to verify:
- Does this response actually address what James asked?
- Is the tone appropriate?
- Is there anything missing?

Returns the original response if the check passes, or a corrected version.

This is an optional second LLM call. Do not call this for short exchanges
or when latency matters more than accuracy. Use threshold checks before calling.
Controlled by SELF_REVIEW_ENABLED in brain/config.py.
"""

import requests
from brain.config import PRESENCE_URL, PRESENCE_MODEL


REVIEW_SYSTEM = """You are reviewing your own response before sending it.
Be brief. If the response is good, say only: PASS
If the response misses something important or has the wrong tone, provide a corrected version.
Do not explain. Either say PASS or provide the corrected text."""


def review_response(draft: str, james_said: str, recent_context: str = "") -> str:
    """
    Returns the final response — either the original draft (if PASS) or a corrected version.
    Fetches conversation context automatically if not provided.
    Falls back to draft on any error.
    """
    if not recent_context:
        try:
            from brain.conversation_buffer import format_for_context
            recent_context = format_for_context(n=5)
        except Exception:
            recent_context = ""

    prompt = (
        f"James said: {james_said}\n\n"
        f"Recent context:\n{recent_context}\n\n"
        f"Your draft response:\n{draft}\n\n"
        "Review: Does this response appropriately address what James said given the context?"
    )

    try:
        resp = requests.post(PRESENCE_URL, json={
            "model":    PRESENCE_MODEL,
            "messages": [
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            "stream":     False,
            "keep_alive": -1,
            "options":    {"num_ctx": 4096},
        }, timeout=30)

        content = resp.json().get("message", {}).get("content", "").strip()

        if not content or content.upper().startswith("PASS"):
            return draft
        return content

    except Exception as e:
        print(f"[self_review] Review failed, using draft: {e}")
        return draft
