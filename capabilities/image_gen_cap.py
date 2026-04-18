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
                visual      = gen_result.get("visual_impression", "")
                prev_visual = gen_result.get("prev_impression", "")
                if visual:
                    response_ctx = (
                        f"[IMAGE ITERATION {bridge._session_state.get('iteration_count', 1)}]:"
                        f" {gen_result['image_path']}\n"
                        f"Changes made: {gen_result.get('changes_made', '')}\n"
                        f"What you see now: {visual}\n"
                        f"What you saw before: {prev_visual}\n\n"
                        f"Compare honestly — did the feedback get addressed? "
                        f"What improved? What's still off? "
                        f"Tell James what you notice and ask if this is closer or if you should keep going."
                    )
                else:
                    response_ctx = (
                        f"[IMAGE ITERATION]: {gen_result['image_path']}\n"
                        f"Changes made: {gen_result.get('changes_made', '')}\n"
                        f"Vision model wasn't available to analyze the output. "
                        f"Tell James the iteration is done and ask him to look — "
                        f"let him tell you what changed."
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
            visual = gen_result.get("visual_impression", "")
            if visual:
                response_ctx = (
                    f"[IMAGE GENERATED — SELF]: {gen_result['image_path']}\n"
                    f"What you actually see: {visual}\n\n"
                    f"React to what you see — not what you intended. "
                    f"If the hood is up when it should be down, say so. "
                    f"If the freckles came out right, say so. "
                    f"If the eyes look soft when they should be direct, say so. "
                    f"This is a design session. Have an opinion. "
                    f"Ask James if he wants to iterate on anything specific."
                )
            else:
                response_ctx = (
                    f"[IMAGE GENERATED — SELF]: {gen_result['image_path']}\n"
                    f"Vision model wasn't available to analyze the output. "
                    f"Tell James the image is ready and ask him to take a look — "
                    f"you'll react once you can see it."
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
            visual     = gen_result.get("visual_impression", "")
            if visual:
                response_ctx = (
                    f"[IMAGE GENERATED]: {image_path}\n"
                    f"Prompt used: {gen_result.get('prompt_used', prompt)[:120]}\n"
                    f"What you actually see in the image: {visual}\n\n"
                    f"React to what you see — not what you intended. "
                    f"If the hood is up when it should be down, say so. "
                    f"If the freckles came out right, say so. "
                    f"This is a collaboration. Have an opinion. "
                    f"Ask James if he wants to iterate on anything specific."
                )
            else:
                response_ctx = (
                    f"[IMAGE GENERATED]: {image_path}\n"
                    f"Prompt used: {gen_result.get('prompt_used', prompt)[:120]}\n"
                    f"Vision model wasn't available to analyze the output. "
                    f"Tell James the image is ready and ask him to take a look — "
                    f"you'll react once you can see it."
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
