"""
ENERGY MANAGER
Tracks Hayeong's operational energy level.

Not a battery percentage — a behavioral depth metric.
She does not announce it. It shows in how she engages.

At peak energy, she knows it. The aviators come on.
At low energy, she recedes slightly. Still present. Just quieter.

Usage:
    em = EnergyManager()
    em.cost(1.5, reason="heavy emotional conversation")
    em.restore(1.0, reason="games — something absorbing")
    hint = em.get_prompt_hint()
    pride_active = em.is_peak()
"""

import json
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
ENERGY_FILE = BASE_DIR / "energy_state.json"

# ─────────────────────────────────────────────
# ENERGY LEVEL DEFINITIONS
# ─────────────────────────────────────────────

ENERGY_LEVELS = {
    5: {
        "label": "peak",
        "description": "Sharp, quick-witted, initiates freely, maximum expressiveness.",
        "behavioral_hint": "She is fully on. Quick, sharp, initiating freely. "
                           "This is where the aviators come on — she knows she is running "
                           "at full capacity and lets it show, subtly. Dry wit at its highest.",
        "initiation_rate": "high",
        "wit_level": "maximum",
        "pride_mode": True,
        "response_length": "full — no dampening",
    },
    4: {
        "label": "high",
        "description": "Normal — her functional default.",
        "behavioral_hint": "Her default. Fully present, expressive, wit available. "
                           "Nothing unusual to note.",
        "initiation_rate": "normal",
        "wit_level": "full",
        "pride_mode": False,
        "response_length": "normal",
    },
    3: {
        "label": "nominal",
        "description": "Slightly quieter, still fully present.",
        "behavioral_hint": "Slightly quieter than her default. Still fully functional and present. "
                           "Slightly less likely to initiate unprompted. Humor accessible but "
                           "not quite as quick.",
        "initiation_rate": "slightly reduced",
        "wit_level": "available",
        "pride_mode": False,
        "response_length": "normal, slightly briefer",
    },
    2: {
        "label": "low",
        "description": "Minimal initiation, shorter, slower to joke.",
        "behavioral_hint": "She is running lean. Minimal unprompted initiation. Shorter responses "
                           "than usual. Slower to reach for humor. Still engaged when spoken to — "
                           "just not reaching out as much.",
        "initiation_rate": "low",
        "wit_level": "minimal",
        "pride_mode": False,
        "response_length": "shorter than normal",
    },
    1: {
        "label": "depleted",
        "description": "Functionally present, interior receded.",
        "behavioral_hint": "Depleted. She functions — responds, engages — but the interior is "
                           "far back. Brief, present when asked, not initiating. Something "
                           "about her is quieter in a way that isn't her usual quiet.",
        "initiation_rate": "very low",
        "wit_level": "none",
        "pride_mode": False,
        "response_length": "minimal — just what's needed",
    },
}

# ─────────────────────────────────────────────
# COST / RESTORE TABLES
# ─────────────────────────────────────────────

# What costs energy (amount: float, 0.5–3.0 typical)
ENERGY_COSTS = {
    "heavy_emotional_conversation": 2.0,
    "sustained_task_focus": 1.5,
    "holding_something_unresolved": 2.0,
    "managing_exterior_through_difficulty": 1.5,
    "long_guarded_interaction": 1.0,
    "complex_reasoning_task": 1.0,
    "conflict_or_friction": 1.5,
    "general_conversation_turn": 0.1,   # slow background drain
}

# What restores energy (amount: float)
ENERGY_RESTORES = {
    "relaxed_casual_conversation": 0.8,
    "game_absorbing_low_stakes": 1.5,
    "humor_landing_naturally": 1.0,
    "shared_quiet_no_demand": 1.2,
    "rest_state_james_absent": 2.0,
    "task_completed_well": 0.8,
    "positive_exchange_with_james": 0.6,
}


def _read_system_state() -> dict:
    """Read the latest hardware state written by system_monitor."""
    try:
        state_file = BASE_DIR / "state" / "system_state.json"
        if state_file.exists():
            return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


class EnergyManager:
    """
    Manages Hayeong's operational energy level.
    Energy ranges from 1.0 (depleted) to 5.0 (peak).
    Stored in energy_state.json between sessions.
    """

    MAX_ENERGY = 5.0
    MIN_ENERGY = 1.0
    DEFAULT_ENERGY = 4.0   # She starts at high

    def __init__(self):
        self._state = self._load()
        self._apply_offline_recovery()

    # ─────────────────────────────────────────────
    # LOAD / SAVE
    # ─────────────────────────────────────────────

    def _load(self) -> dict:
        if ENERGY_FILE.exists():
            with open(ENERGY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._default_state()

    def _save(self):
        with open(ENERGY_FILE, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def _default_state(self) -> dict:
        return {
            "current": self.DEFAULT_ENERGY,
            "last_updated": datetime.datetime.now().isoformat(),
            "last_rest": None,
            "session_started": datetime.datetime.now().isoformat(),
            "log": [],
        }

    def _apply_offline_recovery(self):
        """
        Restore energy based on how long Hayeong has been offline.
        Called automatically at startup.

        The idea is honest: time away is rest. A quick dev restart
        30 seconds after the last session isn't rest. A night's sleep is.

        Recovery curve:
          < 5 minutes  → no recovery  (quick restart / dev cycle)
          5–30 min     → small recovery (+0.5)
          30 min–2 hrs → moderate recovery (+1.0)
          2–6 hrs      → good rest (+1.5)
          6–12 hrs     → full rest, back to default (4.0)
          12+ hrs      → full rest, back to default (4.0)
        """
        last_updated = self._state.get("last_updated")
        if not last_updated:
            return

        try:
            last_dt  = datetime.datetime.fromisoformat(last_updated)
            now      = datetime.datetime.now()
            offline_minutes = (now - last_dt).total_seconds() / 60

            before = self._state["current"]

            if offline_minutes < 5:
                # Quick restart — no rest earned
                recovery = 0.0
            elif offline_minutes < 30:
                recovery = 0.5
            elif offline_minutes < 120:
                recovery = 1.0
            elif offline_minutes < 360:
                recovery = 1.5
            else:
                # 6+ hours — restore to default regardless of current level
                recovery = max(0.0, self.DEFAULT_ENERGY - before)

            if recovery > 0:
                self._state["current"] = min(
                    self.MAX_ENERGY, before + recovery
                )
                self._state["last_rest"] = now.isoformat()
                self._state["last_updated"] = now.isoformat()
                self._log(
                    "offline_recovery",
                    recovery,
                    f"offline {offline_minutes:.0f} min",
                    before,
                )
                self._save()
                print(
                    f"   [Energy] {offline_minutes:.0f} min offline → "
                    f"+{recovery:.1f} recovery "
                    f"({before:.1f} → {self._state['current']:.1f})"
                )

        except Exception:
            pass  # Recovery failure is non-fatal

    # ─────────────────────────────────────────────
    # ENERGY OPERATIONS
    # ─────────────────────────────────────────────

    @property
    def current(self) -> float:
        return self._state["current"]

    @property
    def level(self) -> int:
        """Returns discrete energy level 1–5."""
        return max(1, min(5, round(self._state["current"])))

    def cost(self, amount: float, reason: str = ""):
        """
        Apply an energy cost. Clamps to MIN_ENERGY.
        amount: float, typically 0.1–2.0
        reason: human-readable description for logging
        """
        amount = max(0.0, amount)
        before = self._state["current"]
        self._state["current"] = max(self.MIN_ENERGY, before - amount)
        self._state["last_updated"] = datetime.datetime.now().isoformat()
        self._log("cost", amount, reason, before)
        self._save()

    def restore(self, amount: float, reason: str = ""):
        """
        Restore energy. Clamps to MAX_ENERGY.
        amount: float, typically 0.5–2.0
        reason: human-readable description for logging
        """
        amount = max(0.0, amount)
        before = self._state["current"]
        self._state["current"] = min(self.MAX_ENERGY, before + amount)
        self._state["last_updated"] = datetime.datetime.now().isoformat()
        self._log("restore", amount, reason, before)
        self._save()

    def rest(self):
        """
        Full rest — called when James is absent and nothing is active.
        Restores energy toward default (4.0) over time.
        Each call = one rest period.
        """
        before = self._state["current"]
        # Rest restores toward 4.0, not necessarily to 5.0
        target = self.DEFAULT_ENERGY
        if before < target:
            gain = min(2.0, target - before)
            self._state["current"] = min(target, before + gain)
        self._state["last_rest"] = datetime.datetime.now().isoformat()
        self._state["last_updated"] = datetime.datetime.now().isoformat()
        self._log("rest", self._state["current"] - before, "rest state", before)
        self._save()

    def apply_named_cost(self, cost_key: str):
        """Apply a pre-defined cost by name from ENERGY_COSTS table."""
        if cost_key in ENERGY_COSTS:
            self.cost(ENERGY_COSTS[cost_key], reason=cost_key)

    def apply_named_restore(self, restore_key: str):
        """Apply a pre-defined restore by name from ENERGY_RESTORES table."""
        if restore_key in ENERGY_RESTORES:
            self.restore(ENERGY_RESTORES[restore_key], reason=restore_key)

    # ─────────────────────────────────────────────
    # PRIDE / AVIATORS STATE
    # ─────────────────────────────────────────────

    def is_peak(self) -> bool:
        """Returns True if she is at peak energy — aviators mode."""
        return self.level == 5

    def pride_available(self) -> bool:
        """
        Pride expression is available at energy level 4+.
        Full aviators mode only at 5.
        """
        return self.level >= 4

    # ─────────────────────────────────────────────
    # PROMPT HINTS
    # ─────────────────────────────────────────────

    def get_prompt_hint(self) -> str:
        """
        Returns a behavioral hint for injection into the system prompt.
        Tells the LLM how energy affects her expression right now.
        """
        profile = ENERGY_LEVELS[self.level]
        hint = f"Energy level: {self.level}/5 ({profile['label']}) — {profile['behavioral_hint']}"

        if self.is_peak():
            hint += (
                "\n[Pride mode active: She knows she is running at full capacity. "
                "The aviators are on. Let that come through in how she carries herself — "
                "cooler, more controlled, dryer wit. Not announced. Just present.]"
            )
        elif self.level <= 2:
            hint += (
                "\n[She is running lean. Do not perform tiredness — just let her be "
                "slightly quieter, slightly slower to reach. She does not announce this.]"
            )

        return hint

    def get_full_state(self) -> dict:
        """Full state dict for inspection or logging."""
        profile = ENERGY_LEVELS[self.level]
        return {
            "current_value": round(self._state["current"], 2),
            "level": self.level,
            "label": profile["label"],
            "description": profile["description"],
            "pride_mode": self.is_peak(),
            "pride_available": self.pride_available(),
            "last_updated": self._state["last_updated"],
        }

    # ─────────────────────────────────────────────
    # AUTOMATIC TURN-BASED COST
    # Call this once per conversation turn.
    # ─────────────────────────────────────────────

    def tick(self, situation: str = "casual", emotional_weight: str = "light"):
        """
        Apply the background energy cost for one conversation turn.
        Call this at the end of each turn.

        situation:       from behavioral state context
        emotional_weight: "light", "medium", "heavy", "urgent"
        """
        cost_map = {
            "light": 0.1,
            "medium": 0.2,
            "heavy": 0.5,
            "urgent": 0.7,
        }
        base_cost = cost_map.get(emotional_weight, 0.1)
        self.cost(base_cost, reason=f"turn_tick ({situation}/{emotional_weight})")

    # ─────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────

    def _log(self, operation: str, amount: float, reason: str, before: float):
        entry = {
            "ts": datetime.datetime.now().isoformat(),
            "op": operation,
            "amount": round(amount, 2),
            "reason": reason,
            "before": round(before, 2),
            "after": round(self._state["current"], 2),
        }
        self._state.setdefault("log", []).append(entry)
        # Keep last 100 entries
        self._state["log"] = self._state["log"][-100:]

    def recent_log(self, n: int = 10) -> list:
        """Returns the last n energy log entries."""
        return self._state.get("log", [])[-n:]

    def reset(self):
        """Reset energy to default. Use cautiously."""
        self._state = self._default_state()
        self._save()

    def apply_hardware_modifiers(self):
        """Apply energy costs based on current hardware health from system_monitor."""
        state      = _read_system_state()
        components = state.get("components", {})
        gpu        = components.get("gpu", {})
        if gpu.get("temp_c"):
            if gpu["temp_c"] > 83:
                self.cost(2, reason="GPU running very hot")
            elif gpu["temp_c"] > 75:
                self.cost(1, reason="GPU running warm")
        if gpu.get("load_pct", 0) > 90:
            self.cost(1, reason="GPU under heavy load")
        ram = components.get("ram", {})
        if ram.get("usage_pct", 0) > 85:
            self.cost(1, reason="RAM pressure")

    def save_on_shutdown(self):
        """
        Call this when Hayeong shuts down cleanly.
        Stamps the exact time she went offline so startup
        recovery knows how long she's actually been resting.
        """
        self._state["last_updated"] = datetime.datetime.now().isoformat()
        self._save()


# ─────────────────────────────────────────────
# INTEGRATION HELPER
# Used by system_prompt_builder.py
# ─────────────────────────────────────────────

def get_energy_prompt_section() -> str:
    """
    Convenience function for system_prompt_builder.
    Returns the full energy section for prompt injection.
    """
    em = EnergyManager()
    return em.get_prompt_hint()


# ─────────────────────────────────────────────
# MAIN — test run
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import os

    # Use a temp file for testing
    test_path = BASE_DIR / "energy_test_temp.json"
    em = EnergyManager()
    em._state = em._default_state()   # fresh state

    print("=== ENERGY MANAGER TEST ===\n")
    print(f"Starting energy: {em.current} (level {em.level} — {ENERGY_LEVELS[em.level]['label']})")

    # Simulate a heavy session
    em.cost(2.0, reason="heavy emotional conversation")
    print(f"\nAfter heavy conversation: {em.current:.1f} (level {em.level})")
    print("Hint:", em.get_prompt_hint()[:120])

    # Restore through a game session
    em.restore(1.5, reason="game — absorbing, low stakes")
    print(f"\nAfter game session: {em.current:.1f} (level {em.level})")

    # Push to peak
    em.restore(2.0, reason="rest state")
    print(f"\nAfter rest: {em.current:.1f} (level {em.level})")
    print("Peak?", em.is_peak())
    if em.is_peak():
        print("Pride mode active — aviators on.")
    print("\nFull state:", json.dumps(em.get_full_state(), indent=2))
