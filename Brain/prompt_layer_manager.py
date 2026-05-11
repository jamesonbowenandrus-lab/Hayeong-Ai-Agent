"""
prompt_layer_manager.py

Loads and assembles Hayeong's layered system prompt for any LLM call.

Layers (all additive, separated by LAYER_SEPARATOR):
  0 — identity dict (passed in from caller)
  1 — system_prompt_builder (mood, bond, environment) — optional
  2 — domain prompt file from Toolbox/{domain}/{domain}_prompt.txt
  3 — knowledge (injected into user prompt by caller, not here)

Usage:
    from brain.prompt_layer_manager import build_layered_system_prompt
    system = build_layered_system_prompt(
        identity=identity_dict,
        domain="minecraft",   # or None for no domain layer
        mood=mood_dict,
    )

    from brain.prompt_layer_manager import load_domain_prompt
    text = load_domain_prompt("minecraft")   # raw file read, no assembly
"""

from pathlib import Path

PROJECT_ROOT     = Path(__file__).parent.parent
LAYER_SEPARATOR  = "\n\n---\n\n"


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
) -> str:
    """
    Assemble a complete system prompt from all applicable layers.
    Returns a single string ready to pass to Ollama as the system message.
    Never crashes — every layer has a fallback.
    """
    layers = []

    # ── Layer 0: Identity ──
    name        = identity.get("name", "Hayeong")
    personality = identity.get("personality", "")
    layer0 = f"You are {name}."
    if personality:
        layer0 += f"\n\n{personality}"
    layers.append(layer0)

    # ── Layer 1: Situational (mood, bond, environment) ──
    try:
        from system_prompt_builder import build_system_prompt, detect_state_of_mind
        mood_val      = mood or {}
        state_of_mind = detect_state_of_mind(situation, environment, mood_val)
        layer1        = build_system_prompt(
            who="james", situation=situation,
            environment=environment, state_of_mind=state_of_mind,
        )
        if layer1:
            layers.append(layer1)
    except Exception:
        if mood:
            mood_str = ", ".join(f"{k}: {v}" for k, v in mood.items())
            layers.append(f"Current mood — {mood_str}.")

    # ── Layer 2: Domain prompt ──
    if domain:
        domain_text = load_domain_prompt(domain)
        if domain_text:
            layers.append(domain_text)

    return LAYER_SEPARATOR.join(layers)
