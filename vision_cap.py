# capabilities/vision_cap.py
# Vision capability — screen observation and image analysis.

from capability_loader import result

ACTIONS = ["vision"]

_vision = None

def _get_vision():
    global _vision
    if _vision is None:
        try:
            from vision_bridge import VisionBridge
            v = VisionBridge()
            if v.is_available():
                _vision = v
        except ImportError:
            pass
    return _vision


def handle(action: str, user_input: str, context: dict) -> dict:
    vision = _get_vision()
    if vision is None:
        return result(success=False, speak="Vision isn't available right now.")

    decision = context.get("decision", {})
    logger   = context.get("logger")
    mode     = decision.get("mode", "screen")

    try:
        if mode == "image":
            speak_fn = context.get("speak_fn")
            if speak_fn:
                speak_fn("Which image should I look at?", emotion="neutral")
            image_path = input("Image path: ").strip()
            vision_ctx = vision.look_at_image(image_path, user_input)
            speak_text = "Got it, analyzing now."
        elif mode == "deep":
            vision_ctx = vision.look_at_screen_deep(user_input)
            speak_text = "Let me take a closer look."
        else:
            vision_ctx = vision.look_at_screen(user_input)
            speak_text = "Let me take a look."

        if logger:
            try:
                logger.log_capability_used("vision", action="analyze", outcome="success")
            except Exception:
                pass

        return result(
            success=True,
            response=vision_ctx,
            speak=speak_text,
        )

    except Exception as e:
        return result(success=False, speak="I had trouble seeing that.", data={"error": str(e)})
