# capabilities/_template.py
#
# CAPABILITY TEMPLATE
# Copy this file to build a new capability.
# Rename it to: capabilities/your_name_cap.py
# Then add an entry in capability_registry.json.
#
# That's the entire process. main.py never changes.
#
# ─────────────────────────────────────────────
# REQUIRED: Tell the loader which actions this handles.
# These must match the action strings context_router.py returns.
# ─────────────────────────────────────────────

ACTIONS = [
    "your_action_name",   # e.g. "web_search", "vision", "image_generation"
]

# ─────────────────────────────────────────────
# REQUIRED: The handler function.
# This is what runs when Hayeong needs this capability.
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    """
    Run this capability.

    Parameters
    ----------
    action     : The action string that triggered this (from ACTIONS list)
    user_input : What the user said / typed
    context    : Dict containing:
                   context["memory"]      — recent conversation history
                   context["mood"]        — current mood state dict
                   context["decision"]    — full decision dict from context_router
                   context["model"]       — selected LLM model name
                   context["session"]     — SessionTrust object
                   context["speak_fn"]    — callable(text, emotion) to speak immediately
                   context["logger"]      — HayeongLogger instance or None

    Returns
    -------
    dict with keys:
        success  (bool)       — did it work?
        response (str|None)   — text to inject into AI prompt context
                                None = AI responds with no extra context
        speak    (str|None)   — say this immediately before AI generates
                                None = no pre-speak
        emotion  (str)        — TTS emotion for the speak phrase
        data     (dict)       — any extra structured data you want back
    """
    from capability_loader import result

    # ── Your implementation goes here ──────────────────────────────

    # Example: say something immediately while working
    # context["speak_fn"]("On it.", emotion="neutral")

    # Example: do the actual work
    # output = do_something(user_input)

    # Example: return context to inject into the AI prompt
    # return result(
    #     success=True,
    #     response=f"[Result from your_capability]: {output}",
    #     speak="Got it.",
    # )

    # Placeholder — replace with real implementation
    return result(
        success=False,
        data={"reason": "not_implemented"},
    )


# ─────────────────────────────────────────────
# OPTIONAL: Called once when capability is first loaded.
# Use for expensive setup like loading models.
# ─────────────────────────────────────────────

def on_load():
    """Called once when this capability is imported."""
    pass


# ─────────────────────────────────────────────
# OPTIONAL: Called when capability is hot-reloaded.
# Use to clean up before the new version takes over.
# ─────────────────────────────────────────────

def on_unload():
    """Called before this capability is reloaded or deactivated."""
    pass


# ─────────────────────────────────────────────
# REGISTRY ENTRY (paste into capability_registry.json)
# ─────────────────────────────────────────────
#
# {
#   "id":          "your_capability_id",
#   "name":        "Human Readable Name",
#   "description": "What this does and how to invoke it",
#   "status":      "active",
#   "approved_by": "james",
#   "script":      "capabilities/your_name_cap.py",
#   "actions":     ["your_action_name"]
# }
