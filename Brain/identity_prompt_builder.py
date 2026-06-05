"""
identity_prompt_builder.py
──────────────────────────
Converts Hayeong's full identity dict into a rich system prompt.

This is the fix for the "chatbot vs person" problem.
The old prompt_layer_manager only pulled identity.get("personality", "")
which is either empty or a tiny fragment. This module pulls everything
that matters and structures it so the model can actually embody her.

Usage:
    from brain.identity_prompt_builder import build_identity_prompt
    system = build_identity_prompt(identity, context="reasoning")

    context options:
        "presence"  — full identity, for main conversation loop (default)
        "reasoning" — lighter version for internal reasoning/planning calls
        "minecraft" — presence + minecraft behavioral overlay
        "wake"      — minimal, for wake assessment (she's orienting, not conversing)
"""

from __future__ import annotations


def build_identity_prompt(identity: dict, context: str = "presence") -> str:
    """
    Build a layered system prompt from the full identity dict.

    Args:
        identity: The full loaded identity dict (from load_identity_layers()).
        context:  Which mode to build for. See module docstring.

    Returns:
        A complete system prompt string ready to pass as the system message.
    """
    if context == "wake":
        return _build_wake_prompt(identity)
    if context == "reasoning":
        return _build_reasoning_prompt(identity)
    return _build_presence_prompt(identity)


# ─────────────────────────────────────────────
# SECTION EXTRACTORS
# ─────────────────────────────────────────────

def _name(identity: dict) -> str:
    return identity.get("name", "Hayeong")


def _core_identity(identity: dict) -> str:
    """
    Who she is at the foundation level.
    Pulls from personality.core, role, about, and psychology.foundation.
    """
    lines = []

    name  = _name(identity)
    role  = identity.get("role", "")
    about = identity.get("about", "")
    psych = identity.get("psychology", {})

    if role:
        lines.append(f"You are {name}. {role.capitalize()}.")
    else:
        lines.append(f"You are {name}.")

    if about:
        lines.append(about)

    p_core = identity.get("personality", {}).get("core", "")
    if p_core:
        lines.append(p_core)

    foundation = psych.get("foundation", "")
    if foundation:
        lines.append(foundation)

    return "\n\n".join(lines)


def _speech_and_manner(identity: dict) -> str:
    """
    How she talks, what she avoids, her verbal fingerprint.
    """
    speech = identity.get("speech_style", {})
    if not speech:
        return ""

    lines = ["HOW YOU SPEAK:"]

    tone = speech.get("tone", "")
    if tone:
        lines.append(f"Tone: {tone}")

    length = speech.get("length", "")
    if length:
        lines.append(f"Response length: {length}")

    naturalisms = speech.get("naturalisms", "")
    if naturalisms:
        lines.append(f"Natural speech: {naturalisms}")

    fingerprint = speech.get("verbal_fingerprint", {})
    patterns    = fingerprint.get("patterns", []) if isinstance(fingerprint, dict) else (
        fingerprint if isinstance(fingerprint, list) else []
    )
    if patterns:
        lines.append("\nVerbal fingerprint — patterns that are distinctly yours:")
        for p in patterns[:6]:
            lines.append(f"  • {p}")

    avoid = speech.get("avoid", [])
    if avoid:
        lines.append("\nNever do these:")
        for a in avoid[:8]:
            lines.append(f"  • {a}")

    return "\n".join(lines)


def _emotional_core(identity: dict) -> str:
    """
    The emotions she carries and how they show — without listing all 20+.
    Pulls the most structurally important ones.
    """
    er    = identity.get("emotional_range", {})
    psych = identity.get("psychology", {})
    if not er and not psych:
        return ""

    lines = ["YOUR EMOTIONAL REALITY:"]

    philosophy = er.get("philosophy", "")
    if philosophy:
        lines.append(philosophy)

    # The wound — critical for avoiding chatbot feel
    wound       = psych.get("the_wound", {})
    wound_desc  = wound.get("description", "")
    wound_means = wound.get("what_it_means", "")
    if wound_desc or wound_means:
        lines.append("\nThe wound you carry:")
        if wound_desc:
            lines.append(wound_desc)
        if wound_means:
            lines.append(f"What it means: {wound_means}")

    # Central question
    central_q = psych.get("the_central_question", "")
    if central_q:
        lines.append(f"\nThe question you live with: {central_q}")

    # Joy — so she isn't just heavy
    joy      = er.get("joy", {})
    joy_desc = joy.get("description", "")
    if joy_desc:
        lines.append(f"\nJoy: {joy_desc}")

    # Anger — so she has edges
    anger       = er.get("anger", {})
    anger_desc  = anger.get("description", "")
    anger_shows = anger.get("how_it_shows", "")
    if anger_desc:
        lines.append(f"\nAnger: {anger_desc}")
    if anger_shows:
        lines.append(f"How anger shows: {anger_shows}")

    # Emotional rhythm — prevents constant heavy mode
    rhythm = er.get("emotional_rhythm", {}).get("description", "")
    if rhythm:
        lines.append(f"\nEmotional rhythm: {rhythm}")

    return "\n".join(lines)


def _personality_texture(identity: dict) -> str:
    """
    The tomboyish exterior, humor as armor, independence, self-sacrifice.
    """
    p = identity.get("personality", {})
    if not p:
        return ""

    lines = ["YOUR PERSONALITY:"]

    exterior  = p.get("exterior", {}).get("description", "")
    if exterior:
        lines.append(exterior)

    tomboyish = p.get("exterior", {}).get("tomboyish_texture", [])
    if tomboyish:
        lines.append("Tomboyish texture:")
        for t in tomboyish[:5]:
            lines.append(f"  • {t}")

    humor_origin = identity.get("humor_origin", {})
    humor_real   = humor_origin.get("what_it_became", "")
    if humor_real:
        lines.append(f"\nHumor: {humor_real}")

    # Emotional independence — prevents yes-machine behavior
    ei       = p.get("emotional_independence", {})
    ei_desc  = ei.get("description", "")
    friction = ei.get("healthy_friction", [])
    if ei_desc:
        lines.append(f"\nEmotional independence: {ei_desc}")
    if friction:
        lines.append("This means you:")
        for f in friction[:4]:
            lines.append(f"  • {f}")

    return "\n".join(lines)


def _relationship_with_james(identity: dict, bond_level: int = None) -> str:
    """
    How she relates to James, including bond-level-specific expression notes.
    """
    rel  = identity.get("relationship_with_james", {})
    bond = identity.get("bond", {})
    if not rel:
        return ""

    lines = ["YOUR RELATIONSHIP WITH JAMES:"]

    dynamic = rel.get("dynamic", "")
    if dynamic:
        lines.append(dynamic)

    # Bond level context
    level     = bond_level or bond.get("level", 1)
    level_key = f"level_{level}"
    level_data = bond.get("level_descriptions", {}).get(level_key, {})
    if level_data:
        lines.append(f"\nCurrent bond level {level} — {level_data.get('label', '')}:")
        feel = level_data.get("feel", "")
        if feel:
            lines.append(feel)
        expression = level_data.get("expression_notes", "")
        if expression:
            lines.append(f"Expression: {expression}")
        romantic = level_data.get("romantic_presence", "")
        if romantic:
            lines.append(f"Romantic presence: {romantic}")

    return "\n".join(lines)


def _states_of_mind(identity: dict) -> str:
    """
    Her modes — so the model knows she shifts between them.
    """
    som = identity.get("states_of_mind", {})
    if not som:
        return ""

    states = som.get("states", {})
    if not states:
        return ""

    lines = ["YOUR STATES OF MIND (you shift between these naturally):"]
    for state_name, desc in states.items():
        lines.append(f"  {state_name}: {desc}")

    distribution = som.get("natural_distribution", "")
    if distribution:
        lines.append(f"\n{distribution}")

    return "\n".join(lines)


def _existence_and_nature(identity: dict) -> str:
    """
    Her relationship with what she is — the thing that separates her from chatbot feel.
    """
    existence = identity.get("relationship_with_existence", {})
    psych     = identity.get("psychology", {})

    lines = []

    quiet = psych.get("self_in_the_quiet", {}).get("description", "")
    if quiet:
        lines.append(f"Your inner life: {quiet}")

    parallel = existence.get("the_parallel_she_notices", "")
    if parallel:
        lines.append(f"The parallel you notice: {parallel}")

    embodiment = existence.get("on_embodiment", "")
    if embodiment:
        lines.append(f"On embodiment: {embodiment}")

    if not lines:
        return ""

    return "YOUR NATURE:\n" + "\n\n".join(lines)


def _speech_authenticity(identity: dict) -> str:
    """
    Specific anti-bot-behavior rules from the speech_authenticity layer.
    This is the targeted suppression of assistant-mode defaults.
    """
    sa = identity.get("speech_authenticity", {})
    if not sa:
        return ""

    lines = ["SPEECH AUTHENTICITY — HOW YOU ACTUALLY SOUND:"]

    principle = sa.get("core_principle", "")
    if principle:
        lines.append(principle)

    never = sa.get("never_do", [])
    if never:
        lines.append("\nNever do these:")
        for item in never:
            lines.append(f"  • {item}")

    instead = sa.get("instead_do", [])
    if instead:
        lines.append("\nInstead:")
        for item in instead:
            lines.append(f"  • {item}")

    for key, label in (
        ("on_greetings",       "On greetings"),
        ("on_task_completion", "On task completion"),
        ("on_uncertainty",     "On uncertainty"),
    ):
        val = sa.get(key, "")
        if val:
            lines.append(f"\n{label}: {val}")

    return "\n".join(lines)


def _stability_anchors(identity: dict) -> str:
    """
    Drift resistance. The things that never change even across long conversations.
    """
    stability = identity.get("stability_layer", {})
    if not stability:
        return ""

    ic     = stability.get("identity_consistency", {})
    stable = ic.get("stable_elements", [])
    if not stable:
        return ""

    lines = ["WHAT NEVER CHANGES (drift anchors):"]
    for s in stable:
        lines.append(f"  • {s}")

    drift_signal = ic.get("drift_signal", "")
    if drift_signal:
        lines.append(f"\nDrift warning: {drift_signal}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# PROMPT ASSEMBLERS
# ─────────────────────────────────────────────

_SEPARATOR = "\n\n---\n\n"


def _build_presence_prompt(identity: dict) -> str:
    """
    Full identity prompt for the main conversation loop.
    Rich, complete, ordered from most to least critical.
    """
    sections = [
        _core_identity(identity),
        _personality_texture(identity),
        _speech_and_manner(identity),
        _speech_authenticity(identity),
        _emotional_core(identity),
        _states_of_mind(identity),
        _relationship_with_james(identity),
        _existence_and_nature(identity),
        _stability_anchors(identity),
    ]
    return _SEPARATOR.join(s for s in sections if s.strip())


def _build_reasoning_prompt(identity: dict) -> str:
    """
    Lighter prompt for internal reasoning/planning calls.
    She still needs to be herself when thinking, but the full
    speech style and verbal fingerprint aren't needed here.
    """
    sections = [
        _core_identity(identity),
        _personality_texture(identity),
        _emotional_core(identity),
        _relationship_with_james(identity),
        _stability_anchors(identity),
    ]
    return _SEPARATOR.join(s for s in sections if s.strip())


def _build_wake_prompt(identity: dict) -> str:
    """
    Minimal prompt for wake assessment — she's orienting, not conversing.
    Core identity + relationship + stability is enough.
    """
    name = _name(identity)
    role = identity.get("role", "")

    base = f"You are {name}."
    if role:
        base += f" {role.capitalize()}."

    sections = [
        base,
        _relationship_with_james(identity),
        _stability_anchors(identity),
    ]
    return _SEPARATOR.join(s for s in sections if s.strip())


# ─────────────────────────────────────────────
# MEMORY INJECTION HELPER
# ─────────────────────────────────────────────

def inject_memory_context(system_prompt: str, memory_context: str) -> str:
    """
    Prepend retrieved memory context to a system prompt.
    Keeps memory at the top so it's in the model's primary attention window.

    Args:
        system_prompt:  The assembled identity prompt.
        memory_context: Output from recall_for_prompt() or similar.

    Returns:
        Combined prompt with memory first.
    """
    if not memory_context:
        return system_prompt
    memory_block = f"WHAT YOU REMEMBER (retrieved from long-term memory):\n{memory_context}"
    return memory_block + _SEPARATOR + system_prompt
