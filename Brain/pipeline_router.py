"""
pipeline_router.py
Routes each James message to the correct processing pipeline.

Pipeline A ("conversation"): fast, 4096 ctx, no tool list
Pipeline B ("task" | "ambiguous"): full context, 8192 ctx, complete tool list

Writes routing decision to Brain/state/core.json so other modules can read it.
"""

from brain.intent_classifier import classify_safe, RouteDecision
from brain.state.core_manager import read as read_state, write_section
from datetime import datetime


def route(message: str) -> RouteDecision:
    """Classify message and record routing decision in shared state."""
    decision = classify_safe(message)
    write_section("routing", {
        "pipeline_mode":  decision,
        "routed_at":      datetime.now().isoformat(timespec="seconds"),
        "message_length": len(message),
    })
    return decision


def get_current_mode() -> RouteDecision:
    """Return the most recently recorded pipeline mode. Fails safe to 'conversation'."""
    try:
        state = read_state()
        return state.get("routing", {}).get("pipeline_mode", "conversation")
    except Exception:
        return "conversation"
