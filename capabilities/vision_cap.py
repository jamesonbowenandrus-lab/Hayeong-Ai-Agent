# capabilities/vision_cap.py
# Vision capability — migrated out of main.py.
#
# Handles: vision action from context_router
# Supports: fast screen glance (moondream), deep analysis (llava:13b), image file analysis

from capability_loader import result

ACTIONS = ["vision"]

# ─────────────────────────────────────────────
# LAZY IMPORT
# ─────────────────────────────────────────────

_vision = None

def _get_vision():
    global _vision
    if _vision is None:
        try:
            from vision_bridge import VisionBridge
            _vision = VisionBridge()
        except ImportError:
            pass
    return _vision


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    vision = _get_vision()
    if vision is None or not vision.is_available():
        return result(
            success=False,
            speak="I can't see right now — vision isn't available.",
        )

    decision = context.get("decision", {})
    mode     = decision.get("mode", "screen")

    speak_map = {
        "screen": "Let me look at your screen.",
        "deep":   "Let me take a closer look.",
        "image":  "Let me analyze that image.",
    }
    speak_text = speak_map.get(mode, "Let me look at that.")

    try:
        if mode == "deep":
            description = vision.look_at_screen_deep(user_input)
        elif mode == "image":
            image_path  = decision.get("image_path", user_input)
            description = vision.look_at_image(image_path, user_input)
        else:
            description = vision.look_at_screen(user_input)

        context_text = vision.format_for_context(description)
        return result(
            success=True,
            response=context_text,
            speak=speak_text,
        )

    except Exception as e:
        return result(
            success=False,
            speak="I ran into a problem with vision.",
            data={"error": str(e)},
        )
