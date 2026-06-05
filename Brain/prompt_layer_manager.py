"""
prompt_layer_manager.py

Loads and assembles Hayeong's layered system prompt for any LLM call.

What changed from the original:
  - Layer 0 now uses identity_prompt_builder.build_identity_prompt()
    instead of identity.get("personality", "") — which was pulling
    almost nothing from the identity dict.
  - Memory retrieval now fires on ALL paths, not just the non-domain path.
  - Memory failures now print to console instead of silently passing.
  - context parameter lets callers specify "presence", "reasoning", or "wake".
  - user_input parameter passed through so memory retrieval is relevant
    to what James just said.

Layers (additive, separated by LAYER_SEPARATOR):
  0 — Full identity (via identity_prompt_builder)
  1 — Retrieved memory context (from ChromaDB recall)
  2 — Situational (mood, bond, environment) from system_prompt_builder
  3 — Domain prompt file from Toolbox/{domain}/{domain}_prompt.txt

Usage:
    from brain.prompt_layer_manager import build_layered_system_prompt
    system = build_layered_system_prompt(
        identity=identity_dict,
        domain="minecraft",   # or None
        mood=mood_dict,
        context="presence",   # "presence" | "reasoning" | "wake"
        user_input="...",     # used for memory retrieval relevance
    )
"""

from pathlib import Path

PROJECT_ROOT    = Path(__file__).parent.parent
LAYER_SEPARATOR = "\n\n---\n\n"


def load_domain_prompt(domain: str) -> str:
    """
    Read Toolbox/{domain}/{domain}_prompt.txt.
    Returns empty string if the file doesn't exist — never crashes.
    """
    if not domain:
        return ""
    path = PROJECT_ROOT / "Toolbox" / domain / f"{domain}_prompt.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def build_layered_system_prompt(
    identity: dict,
    domain: str = None,
    mood: dict = None,
    situation: str = "casual",
    environment: str = "home",
    context: str = "presence",
    user_input: str = "",
) -> str:
    """
    Assemble a complete system prompt from all applicable layers.
    Returns a single string ready to pass to Ollama as the system message.
    Never crashes — every layer has a fallback.

    Args:
        identity:    Full identity dict from load_identity_layers().
        domain:      Optional tool domain (e.g. "minecraft", "blender").
        mood:        Current mood dict.
        situation:   Situational context string (e.g. "casual", "focused").
        environment: Environment string (e.g. "home", "game").
        context:     Prompt context — "presence", "reasoning", or "wake".
                     Controls how much of the identity is included.
        user_input:  The user's current message. Used for memory retrieval
                     so recalled memories are relevant to what James just said.
    """
    layers = []

    # ── Layer 0: Full identity ──────────────────────────────────────────────
    try:
        from brain.identity_prompt_builder import build_identity_prompt
        layer0 = build_identity_prompt(identity, context=context)
    except Exception as e:
        # Hard fallback — should never hit this, but must never crash
        name        = identity.get("name", "Hayeong")
        personality = identity.get("personality", {})
        core        = personality.get("core", "") if isinstance(personality, dict) else str(personality)
        layer0      = f"You are {name}."
        if core:
            layer0 += f"\n\n{core}"
        print(f"[prompt_layer_manager] identity_prompt_builder failed, using fallback: {e}")

    layers.append(layer0)

    # ── Layer 1: Memory context — fires on ALL paths ────────────────────────
    # Memory is inserted at position 0 (before identity) so it receives
    # the model's primary attention. Failures are logged, never swallowed.
    memory_context = ""
    try:
        from memory.memory_retriever import recall_for_prompt
        query = user_input or situation
        if query:
            memory_context = recall_for_prompt(query, n_results=4)
    except Exception as e:
        print(f"[prompt_layer_manager] Memory retrieval failed: {e}")

    if memory_context:
        memory_block = (
            "WHAT YOU REMEMBER (retrieved from long-term memory — "
            "use this to be continuous, not to start fresh):\n"
            + memory_context
        )
        layers.insert(0, memory_block)

    # ── Layer 2: Situational (mood, bond, environment) ──────────────────────
    try:
        from system_prompt_builder import build_system_prompt, detect_state_of_mind
        mood_val      = mood or {}
        state_of_mind = detect_state_of_mind(situation, environment, mood_val)
        layer2        = build_system_prompt(
            who="james", situation=situation,
            environment=environment, state_of_mind=state_of_mind,
        )
        if layer2:
            layers.append(layer2)
    except Exception:
        if mood:
            mood_str = ", ".join(f"{k}: {v}" for k, v in mood.items())
            layers.append(f"Current mood — {mood_str}.")

    # ── Layer 3: Domain prompt ──────────────────────────────────────────────
    if domain:
        domain_text = load_domain_prompt(domain)
        if domain_text:
            layers.append(domain_text)

    return LAYER_SEPARATOR.join(layers)
