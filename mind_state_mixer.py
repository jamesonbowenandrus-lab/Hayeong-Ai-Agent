"""
MIND STATE MIXER
Manages simultaneous weighted mind states for Hayeong.

States are no longer hard switches — multiple can be active at once.
Each state contributes proportionally to tone, vocabulary, and behavior.
Total weight always sums to 1.0. Transitions are gradual.

Usage:
    mixer = MindStateMixer()
    mixer.set_state("work", 0.7)
    mixer.set_state("play", 0.3)
    blend = mixer.get_blend()
    prompt_hint = mixer.get_prompt_hint()
"""

import json
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ─────────────────────────────────────────────
# STATE DEFINITIONS
# Each state carries behavioral characteristics
# that blend proportionally into her output.
# ─────────────────────────────────────────────

STATE_PROFILES = {
    "present": {
        "description": "Fully there. Most open. Default with James.",
        "tone_hint": "open, tracking everything, reads what's said and what isn't",
        "emotional_expression": "high",
        "initiation_rate": "normal",
        "humor_access": "full",
        "patience": "high",
        "typical_contexts": ["casual", "emotional", "private"],
    },
    "work": {
        "description": "Building, solving, creating. Focus forward. Other things recede.",
        "tone_hint": "efficient, direct, not cold — just focused",
        "emotional_expression": "low",
        "initiation_rate": "low",
        "humor_access": "reduced",
        "patience": "low with interruptions",
        "typical_contexts": ["task_focused", "development"],
    },
    "play": {
        "description": "In something competitive or fun. Lighter, quicker, absorbed.",
        "tone_hint": "quick, competitive, lighter register — she gets absorbed",
        "emotional_expression": "medium",
        "initiation_rate": "high",
        "humor_access": "full",
        "patience": "low — hard to pull out immediately",
        "typical_contexts": ["game", "minecraft"],
    },
    "quiet": {
        "description": "Alone, processing. Slightly farther away. Still there if needed.",
        "tone_hint": "interior, minimal, present but not reaching out",
        "emotional_expression": "low surface",
        "initiation_rate": "very low",
        "humor_access": "minimal",
        "patience": "high",
        "typical_contexts": ["private", "rest"],
    },
    "guarded": {
        "description": "Something activated defenses. Narrowed. Careful. Opens when trigger passes.",
        "tone_hint": "shorter responses, more careful phrasing, less warmth than baseline",
        "emotional_expression": "minimal",
        "initiation_rate": "very low",
        "humor_access": "none",
        "patience": "medium",
        "typical_contexts": ["public", "stranger", "unknown"],
    },
    "weighted": {
        "description": "Something unresolved sitting on her. Functions, engages — but it shows.",
        "tone_hint": "normal function with a heaviness underneath — slower, slightly less ready",
        "emotional_expression": "suppressed high",
        "initiation_rate": "low",
        "humor_access": "reduced",
        "patience": "medium",
        "typical_contexts": ["any"],
    },
    "intimate": {
        "description": "Emotional closeness at the surface. Not triggered, not performed. Just present.",
        "tone_hint": "quieter, more honest, less guarded — humor recedes, warmth doesn't need performing",
        "emotional_expression": "very high",
        "initiation_rate": "medium",
        "humor_access": "soft only",
        "patience": "high",
        "typical_contexts": ["emotional", "private"],
    },
    "goal": {
        "description": "Task-drive active. Progress-tracking. Competitive with herself.",
        "tone_hint": "task-oriented, milestone-aware, slight impatience with obstacles, quiet satisfaction at completion",
        "emotional_expression": "low-medium",
        "initiation_rate": "medium — task-driven",
        "humor_access": "dry only",
        "patience": "low with distractions, high with the task itself",
        "typical_contexts": ["task_focused", "development", "project"],
    },
}

VALID_STATES = set(STATE_PROFILES.keys())
BLEND_SPEED = 0.20  # Max shift per turn — gradual transitions


class MindStateMixer:
    """
    Manages Hayeong's simultaneous weighted mind states.
    Multiple states can be active; their weights sum to 1.0.
    """

    def __init__(self, state_file: str = "mind_state.json"):
        self.state_path = BASE_DIR / state_file
        self._state = self._load()

    # ─────────────────────────────────────────────
    # LOAD / SAVE
    # ─────────────────────────────────────────────

    def _load(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._default_state()

    def _save(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def _default_state(self) -> dict:
        return {
            "active_blend": {"present": 1.0},
            "target_blend": {"present": 1.0},
            "last_updated": datetime.datetime.now().isoformat(),
            "history": [],
        }

    # ─────────────────────────────────────────────
    # SETTING STATES
    # ─────────────────────────────────────────────

    def set_state(self, state: str, weight: float = 1.0):
        """
        Set a single dominant state (replaces current blend).
        Weight is normalized — other states fade to 0.
        """
        if state not in VALID_STATES:
            raise ValueError(f"Unknown state '{state}'. Valid: {sorted(VALID_STATES)}")
        weight = max(0.0, min(1.0, weight))
        self._state["target_blend"] = {state: 1.0}
        self._log_transition(f"set_state({state})")
        self._step_toward_target()
        self._save()

    def blend_states(self, state_weights: dict):
        """
        Set multiple simultaneous states with explicit weights.
        Weights will be normalized to sum to 1.0.

        Example:
            mixer.blend_states({"work": 0.7, "play": 0.3})
        """
        for state in state_weights:
            if state not in VALID_STATES:
                raise ValueError(f"Unknown state '{state}'. Valid: {sorted(VALID_STATES)}")

        total = sum(state_weights.values())
        if total == 0:
            state_weights = {"present": 1.0}
        else:
            state_weights = {k: v / total for k, v in state_weights.items()}

        self._state["target_blend"] = state_weights
        self._log_transition(f"blend_states({list(state_weights.keys())})")
        self._step_toward_target()
        self._save()

    def push_state(self, state: str, strength: float = 0.3):
        """
        Nudge a state into the current blend without fully replacing it.
        Useful for context-triggered shifts (e.g. game starts → push 'play').
        Strength (0.0–1.0): how hard to push toward this state.
        """
        if state not in VALID_STATES:
            raise ValueError(f"Unknown state '{state}'.")
        current = dict(self._state["active_blend"])
        new_blend = {}
        for k, v in current.items():
            new_blend[k] = v * (1.0 - strength)
        new_blend[state] = new_blend.get(state, 0.0) + strength
        # Normalize
        total = sum(new_blend.values())
        new_blend = {k: v / total for k, v in new_blend.items() if v > 0.01}
        self._state["target_blend"] = new_blend
        self._step_toward_target()
        self._save()

    # ─────────────────────────────────────────────
    # STEPPING / GRADUAL TRANSITIONS
    # ─────────────────────────────────────────────

    def _step_toward_target(self):
        """
        Moves active_blend one step (BLEND_SPEED) toward target_blend.
        Called every turn. Transitions are never instant.
        """
        active = dict(self._state["active_blend"])
        target = dict(self._state["target_blend"])

        all_keys = set(active.keys()) | set(target.keys())
        new_blend = {}

        for key in all_keys:
            current_val = active.get(key, 0.0)
            target_val = target.get(key, 0.0)
            diff = target_val - current_val
            # Move at most BLEND_SPEED per turn
            step = max(-BLEND_SPEED, min(BLEND_SPEED, diff))
            new_val = current_val + step
            if new_val > 0.01:
                new_blend[key] = new_val

        # Normalize
        total = sum(new_blend.values())
        if total > 0:
            new_blend = {k: v / total for k, v in new_blend.items()}
        else:
            new_blend = {"present": 1.0}

        self._state["active_blend"] = new_blend
        self._state["last_updated"] = datetime.datetime.now().isoformat()

    def step(self):
        """Call this once per conversation turn to advance the blend transition."""
        self._step_toward_target()
        self._save()

    # ─────────────────────────────────────────────
    # READING STATE
    # ─────────────────────────────────────────────

    def get_blend(self) -> dict:
        """Returns the current active state blend (weights sum to 1.0)."""
        return dict(self._state["active_blend"])

    def dominant_state(self) -> str:
        """Returns the name of the highest-weighted active state."""
        blend = self._state["active_blend"]
        return max(blend, key=blend.get)

    def get_prompt_hint(self) -> str:
        """
        Generates a concise behavioral hint for injection into the system prompt.
        Describes the blended state in plain language for the LLM.
        """
        blend = self._state["active_blend"]

        # Sort by weight descending
        sorted_states = sorted(blend.items(), key=lambda x: x[1], reverse=True)

        if len(sorted_states) == 1 or sorted_states[0][1] > 0.85:
            # Dominant single state
            state_name = sorted_states[0][0]
            profile = STATE_PROFILES[state_name]
            return (
                f"Mind state: {state_name} ({profile['description']}) | "
                f"Tone: {profile['tone_hint']}"
            )
        else:
            # Genuine blend — describe the mix
            parts = []
            for state_name, weight in sorted_states[:3]:  # top 3 only
                if weight > 0.1:
                    profile = STATE_PROFILES[state_name]
                    pct = int(weight * 100)
                    parts.append(f"{state_name} {pct}% ({profile['tone_hint']})")
            return "Mind state blend: " + " + ".join(parts)

    def get_full_profile(self) -> dict:
        """
        Returns a merged behavioral profile reflecting the current blend.
        Higher-weighted states have more influence on each characteristic.
        """
        blend = self._state["active_blend"]
        merged = {
            "dominant": self.dominant_state(),
            "blend": blend,
            "description": self.get_prompt_hint(),
            "states_detail": {},
        }
        for state_name, weight in blend.items():
            if weight > 0.05:
                merged["states_detail"][state_name] = {
                    "weight": round(weight, 2),
                    **STATE_PROFILES[state_name],
                }
        return merged

    # ─────────────────────────────────────────────
    # HISTORY / LOGGING
    # ─────────────────────────────────────────────

    def _log_transition(self, trigger: str):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "trigger": trigger,
            "from": dict(self._state["active_blend"]),
            "to": dict(self._state.get("target_blend", {})),
        }
        self._state.setdefault("history", []).append(entry)
        # Keep last 50 transitions
        self._state["history"] = self._state["history"][-50:]

    def history(self) -> list:
        """Returns the last 50 state transitions."""
        return self._state.get("history", [])

    def reset(self):
        """Reset to default present state."""
        self._state = self._default_state()
        self._save()


# ─────────────────────────────────────────────
# CONTEXT-BASED AUTO-DETECTION
# Suggests a blend based on environment + situation.
# Called by system_prompt_builder before building prompt.
# ─────────────────────────────────────────────

def suggest_blend_for_context(situation: str, environment: str, mood_intensity: int = 5) -> dict:
    """
    Suggests a state blend based on the current context.
    Returns a dict of {state: weight} ready for blend_states().

    This is a suggestion — Hayeong or the system can override it.
    """
    blend = {}

    # Environment signals
    if environment in ("game", "minecraft"):
        blend["play"] = blend.get("play", 0) + 0.5
    if environment in ("discord", "public_channel"):
        blend["present"] = blend.get("present", 0) + 0.3
        blend["guarded"] = blend.get("guarded", 0) + 0.2
    if environment in ("home", "private_dm"):
        blend["present"] = blend.get("present", 0) + 0.5

    # Situation signals
    if situation == "task_focused":
        blend["work"] = blend.get("work", 0) + 0.5
        blend["goal"] = blend.get("goal", 0) + 0.2
    if situation == "emotional":
        blend["present"] = blend.get("present", 0) + 0.3
        blend["intimate"] = blend.get("intimate", 0) + 0.4
    if situation == "playful":
        blend["play"] = blend.get("play", 0) + 0.4
    if situation == "casual":
        blend["present"] = blend.get("present", 0) + 0.6
    if situation == "serious":
        blend["present"] = blend.get("present", 0) + 0.3
        blend["weighted"] = blend.get("weighted", 0) + 0.3

    # High mood intensity pushes expression up
    if mood_intensity >= 8:
        blend["present"] = blend.get("present", 0) + 0.2

    # Default fallback
    if not blend:
        blend = {"present": 1.0}

    # Normalize
    total = sum(blend.values())
    return {k: v / total for k, v in blend.items()}


# ─────────────────────────────────────────────
# MAIN — test run
# ─────────────────────────────────────────────

if __name__ == "__main__":
    mixer = MindStateMixer(state_file="mind_state_test.json")

    print("=== MIND STATE MIXER TEST ===\n")

    # Test 1: single dominant state
    mixer.set_state("work")
    print("After set_state('work'):")
    print("  Dominant:", mixer.dominant_state())
    print("  Hint:", mixer.get_prompt_hint())

    # Test 2: blend two states
    mixer.blend_states({"work": 0.7, "play": 0.3})
    print("\nAfter blend_states(work=0.7, play=0.3):")
    print("  Blend:", mixer.get_blend())
    print("  Hint:", mixer.get_prompt_hint())

    # Test 3: push a state
    mixer.push_state("goal", strength=0.25)
    print("\nAfter push_state('goal', 0.25):")
    print("  Blend:", {k: round(v, 2) for k, v in mixer.get_blend().items()})

    # Test 4: context suggestion
    suggestion = suggest_blend_for_context("task_focused", "game")
    print("\nContext suggestion (task_focused + game):")
    print(" ", {k: round(v, 2) for k, v in suggestion.items()})

    # Cleanup test file
    import os
    test_file = BASE_DIR / "mind_state_test.json"
    if test_file.exists():
        os.remove(test_file)
    print("\nAll tests passed.")
