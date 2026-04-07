# capabilities/image_gen_cap.py
# Image generation capability — migrated out of main.py.
#
# Handles: image_gen action from context_router
# Uses ComfyUI via comfyui_bridge.py. ComfyUI is started automatically
# by capability_loader's pre-dispatch app check.

from capability_loader import result

ACTIONS = ["image_gen"]

# ─────────────────────────────────────────────
# LAZY IMPORT
# ─────────────────────────────────────────────

_bridge = None

def _get_bridge():
    global _bridge
    if _bridge is None:
        try:
            from comfyui_bridge import ComfyUIBridge
            _bridge = ComfyUIBridge()
        except ImportError:
            pass
    return _bridge


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    bridge = _get_bridge()
    if bridge is None:
        return result(
            success=False,
            speak="Image generation isn't available right now.",
        )

    decision = context.get("decision", {})

    # Prefer an explicit prompt from the decision engine, otherwise use raw input
    prompt = decision.get("prompt") or user_input

    try:
        gen_result = bridge.generate(prompt)

        if gen_result.get("success"):
            image_path  = gen_result.get("image_path", "")
            message     = gen_result.get("message", "Image generated.")
            response_ctx = (
                f"[IMAGE GENERATED]: {image_path}\n"
                f"Generation message: {message}\n"
                f"Tell James the image is ready and briefly describe what you generated "
                f"based on the prompt: {prompt}"
            )
            return result(
                success=True,
                response=response_ctx,
                speak="Give me a moment.",
                data={"image_path": image_path, "prompt": prompt},
            )
        else:
            msg = gen_result.get("message", "Generation failed.")
            return result(
                success=False,
                speak=msg,
                data=gen_result,
            )

    except Exception as e:
        return result(
            success=False,
            speak="Image generation ran into a problem.",
            data={"error": str(e)},
        )
