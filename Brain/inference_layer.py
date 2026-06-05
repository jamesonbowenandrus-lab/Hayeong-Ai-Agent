"""
inference_layer.py
Builds the structured pre-reasoning block injected into Hayeong's system prompt.

Instructs Hayeong to reason through three questions before formulating any response:
  1. What is James actually trying to accomplish? (intent)
  2. Does anything here conflict with what was established? (contradiction)
  3. What am I uncertain about that I should ask rather than assume? (uncertainty)

Design rules:
- No second LLM call. Runs inside the main generation pass.
- Terse format — tokens are valuable.
- Must never block a response. If reasoning reveals nothing notable, she proceeds.
- conversation/ambiguous pipeline → full inference block
- task pipeline → abbreviated block focused on intent
"""

INFERENCE_BLOCK_FULL = """
═══════════════════════════════════════════════════════════
BEFORE RESPONDING — THINK THROUGH THIS FIRST
═══════════════════════════════════════════════════════════

Step 1 — INTENT
What is James actually trying to accomplish or express?
Not what he literally said — what does he mean given everything you know?
If his words are ambiguous, name the two most likely interpretations.

Step 2 — CONTRADICTION CHECK
Does anything in what James just said conflict with something established
earlier in this conversation or in your memory?
If yes: flag it in your response. Do not silently accept conflicting information.
If no: proceed.

Step 3 — UNCERTAINTY AUDIT
What would you need to know to respond fully and correctly?
If you are missing something important: ask ONE focused question instead of assuming.
If you have enough to proceed: proceed.

Step 4 — RESPOND
Now formulate your response based on steps 1-3.
Your response to James should feel natural — do not narrate the steps.
The thinking happens internally. Only the result reaches James.

═══════════════════════════════════════════════════════════"""


INFERENCE_BLOCK_TASK = """
═══════════════════════════════════════════════════════════
BEFORE ACTING — CONFIRM INTENT
═══════════════════════════════════════════════════════════
What is James actually asking you to do?
If the request is ambiguous, ask ONE clarifying question before proceeding.
If the request is clear, proceed with confidence.
═══════════════════════════════════════════════════════════"""


def get_inference_block(pipeline_mode: str = "conversation") -> str:
    """
    Return the appropriate inference block for the current pipeline mode.
    conversation/ambiguous → full 4-step block
    task → abbreviated intent-only block
    """
    if pipeline_mode == "task":
        return INFERENCE_BLOCK_TASK
    return INFERENCE_BLOCK_FULL


def get_contradiction_reminder(session_summary: str) -> str:
    """
    If a session summary exists, return a one-line prompt to check it for
    contradictions. Returns empty string when there's nothing to compare against.
    """
    if not session_summary or not session_summary.strip():
        return ""
    return (
        "\nNOTE: A session summary is in your context above. "
        "If James's current message conflicts with anything in that summary, "
        "flag it — do not silently accept the conflict.\n"
    )
