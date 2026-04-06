# capabilities/image_gen_cap.py
# Image generation capability — ComfyUI bridge.

from capability_loader import result

ACTIONS = ["image_gen"]

_comfyui = None

def _get_comfyui():
    global _comfyui
    if _comfyui is None:
        try:
            from comfyui_bridge import ComfyUIBridge
            _comfyui = ComfyUIBridge()
        except ImportError:
            pass
    return _comfyui


def handle(action: str, user_input: str, context: dict) -> dict:
    comfyui = _get_comfyui()
    if comfyui is None or not comfyui.is_available():
        return result(success=False, speak="ComfyUI isn't running right now.")

    logger   = context.get("logger")
    speak_fn = context.get("speak_fn")
    u        = user_input.lower()

    try:
        if any(x in u for x in ["realistic", "make it real", "real photo"]):
            if speak_fn:
                speak_fn("Which image should I make realistic?", emotion="neutral")
            image_path = input("Image path: ").strip()
            gen_result = comfyui.make_realistic(image_path)
        elif any(x in u for x in ["screen", "on my screen"]):
            gen_result = comfyui.generate_from_screen(user_input)
        elif any(x in u for x in ["this image", "this photo", "reference"]):
            if speak_fn:
                speak_fn("Which image should I use as reference?", emotion="neutral")
            image_path = input("Image path: ").strip()
            gen_result = comfyui.generate_from_image(image_path, user_input)
        else:
            gen_result = comfyui.generate(user_input)

        success = gen_result.get("success", False)

        if logger:
            try:
                logger.log_capability_used(
                    "comfyui", action="generate",
                    outcome="success" if success else "failed",
                )
            except Exception:
                pass

        if success:
            return result(
                success=True,
                speak="On it, let me generate that.",
                data={"image_path": gen_result.get("image_path")},
            )
        else:
            return result(
                success=False,
                speak=gen_result.get("message", "Something went wrong with generation."),
            )

    except Exception as e:
        return result(success=False, speak="Image generation failed.", data={"error": str(e)})
