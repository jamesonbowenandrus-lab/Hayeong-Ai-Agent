# capabilities/image_gen_cap.py
# Image generation capability — migrated out of main.py.
#
# Handles: image_gen action from context_router
# Uses ComfyUI via comfyui_bridge.py. ComfyUI is started automatically
# by capability_loader's pre-dispatch app check.
#
# Three dispatch paths:
#   iterate  — James is refining a previous generation (feedback keywords)
#   self     — James wants to see Hayeong (generate_self keywords)
#   standard — any other generation request

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
# INTENT SIGNALS
# ─────────────────────────────────────────────

_ITERATE_SIGNALS = [
    "try again", "iterate", "refine", "adjust", "fix that",
    "keep the", "same but", "change the", "make it more", "make it less",
    "the hood is", "the hair is", "the eyes are", "still wrong",
    "almost", "close but", "better but", "one more time",
]

_SELF_SIGNALS = [
    "generate yourself", "draw yourself", "what do you look like",
    "show me you", "generate you", "draw you", "picture of you",
    "image of you", "show yourself", "your appearance",
]


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

    decision   = context.get("decision", {})
    user_lower = user_input.lower()

    # ── Iteration path — James is refining a previous generation ──
    if any(sig in user_lower for sig in _ITERATE_SIGNALS):
        last_prompt = bridge._session_state.get("last_positive_prompt", "")
        if last_prompt:
            gen_result = bridge.iterate(feedback=user_input, previous_prompt=last_prompt)
            if gen_result.get("success"):
                response_ctx = (
                    f"[IMAGE ITERATION]: {gen_result['image_path']}\n"
                    f"Changes made: {gen_result.get('changes_made', '')}\n"
                    f"Tell James the iteration is ready. Share what you changed and "
                    f"what you notice about the result — what's better, what's still off. "
                    f"Ask if it's closer to what he wanted or if you should adjust further."
                )
                return result(
                    success=True,
                    response=response_ctx,
                    speak="Let me refine that.",
                    data=gen_result,
                )
            else:
                return result(
                    success=False,
                    speak=gen_result.get("message", "Iteration failed."),
                )
        # No previous prompt — fall through to standard generation

    # ── Self-generation path — James wants to see Hayeong ──
    if any(sig in user_lower for sig in _SELF_SIGNALS):
        additional = decision.get("prompt", "")
        gen_result = bridge.generate_self(additional)
        if gen_result.get("success"):
            response_ctx = (
                f"[IMAGE GENERATED — SELF]: {gen_result['image_path']}\n"
                f"Prompt used: {gen_result.get('prompt_used', '')[:120]}\n"
                f"Tell James you generated yourself and share your honest reaction "
                f"to how it came out — what looks right, what doesn't, what you'd "
                f"want to change. This is a design session, not a delivery. "
                f"Ask if he wants to iterate on anything."
            )
            return result(
                success=True,
                response=response_ctx,
                speak="Give me a moment.",
                data=gen_result,
            )
        else:
            return result(
                success=False,
                speak=gen_result.get("message", "Self-generation failed."),
            )

    # ── Standard generation path ──
    prompt = decision.get("prompt") or user_input

    try:
        gen_result = bridge.generate(prompt)

        if gen_result.get("success"):
            image_path = gen_result.get("image_path", "")
            response_ctx = (
                f"[IMAGE GENERATED]: {image_path}\n"
                f"Prompt used: {gen_result.get('prompt_used', prompt)[:120]}\n"
                f"The image is ready. React to it honestly — notice what looks right, "
                f"what's off, what you'd want to change. This is a collaboration, not a "
                f"delivery. Tell James what you see and ask if he wants to iterate."
            )
            return result(
                success=True,
                response=response_ctx,
                speak="Give me a moment.",
                data={"image_path": image_path, "prompt": prompt},
            )
        else:
            return result(
                success=False,
                speak=gen_result.get("message", "Generation failed."),
                data=gen_result,
            )

    except Exception as e:
        return result(
            success=False,
            speak="Image generation ran into a problem.",
            data={"error": str(e)},
        )
