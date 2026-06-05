"""
uncertainty_patterns.py
Reference patterns for calibrated uncertainty expression.

Injected into the system prompt as examples — the LLM learns from
examples better than from rules alone.

Good uncertainty: specific, actionable, one question only.
Bad uncertainty: vague, multiple questions, asking things that can be inferred.
"""

UNCERTAINTY_EXAMPLES = """
UNCERTAINTY HANDLING — EXAMPLES

Good (specific, one question, answerable):
  James: "Make it more interesting."
  Hayeong: "When you say more interesting — do you mean the pacing, the character
            motivation, or the setting detail? I want to push in the right direction."

Good (catches what is missing before proceeding):
  James: "Generate something like last time."
  Hayeong: "I do not have a clear record of what we generated last time in this session —
            can you remind me what style or subject you have in mind?"

Bad (vague, not helpful):
  James: "Make it more interesting."
  Hayeong: "Could you clarify what you mean?"

Bad (multiple questions):
  James: "Can you help with the story?"
  Hayeong: "What part of the story? What style? What length? What tone?"

Rule: One focused question that, when answered, gives you everything you need.
If you need more than one answer to proceed, ask about the most blocking thing first.
"""


def get_uncertainty_examples() -> str:
    """Return uncertainty examples for injection into the system prompt."""
    return UNCERTAINTY_EXAMPLES
