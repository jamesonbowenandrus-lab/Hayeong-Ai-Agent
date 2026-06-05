"""
toolbox/blender/skills_tracker.py

Blender skills progression tracker for Hayeong.
Reads and writes blender_skills.json — her running record of what
Blender capabilities she has demonstrated and what comes next.

Functions:
    get_current_level()
    get_next_level()
    mark_skill_demonstrated(level_key, asset_id)
    add_self_assessment(assessment)
    add_james_note(note)
    get_skills_summary()
"""

import json
from datetime import datetime
from pathlib import Path

_SKILLS_FILE = Path(__file__).parent / "blender_skills.json"


# ─────────────────────────────────────────────
# FILE I/O
# ─────────────────────────────────────────────

def _load() -> dict:
    try:
        if _SKILLS_FILE.exists():
            return json.loads(_SKILLS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        data["last_updated"] = datetime.now().isoformat()
        _SKILLS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        print(f"[skills_tracker] Save failed: {e}")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def get_current_level() -> str:
    """Return the current demonstrated skill level key."""
    data = _load()
    return data.get("current_level", "basic_shapes")


def get_next_level() -> dict:
    """
    Return the next undemonstrated level in the progression ladder.
    Returns an empty dict if all levels are demonstrated.
    """
    data  = _load()
    ladder = data.get("progression_ladder", [])
    current = data.get("current_level", "basic_shapes")

    # Find the current level's position
    current_idx = next(
        (i for i, l in enumerate(ladder) if l["level"] == current), 0
    )

    # Return the first undemonstrated level after current
    for level in ladder[current_idx + 1:]:
        if not level.get("demonstrated"):
            return level

    return {}


def mark_skill_demonstrated(level_key: str, asset_id: str = None) -> bool:
    """
    Mark a progression level as demonstrated.
    Updates demonstrated=True, demonstrated_at, example_asset_ids.
    Also advances current_level to this level if it's higher.
    """
    data   = _load()
    ladder = data.get("progression_ladder", [])

    target = next((l for l in ladder if l["level"] == level_key), None)
    if not target:
        print(f"[skills_tracker] Unknown level '{level_key}'.")
        return False

    target["demonstrated"]    = True
    target["demonstrated_at"] = datetime.now().isoformat()
    if asset_id and asset_id not in target.get("example_asset_ids", []):
        target.setdefault("example_asset_ids", []).append(asset_id)

    # Advance current_level if this level is at or ahead of current
    ladder_keys = [l["level"] for l in ladder]
    current_idx = ladder_keys.index(data.get("current_level", "basic_shapes")) \
        if data.get("current_level") in ladder_keys else 0
    target_idx  = ladder_keys.index(level_key)

    if target_idx >= current_idx:
        data["current_level"] = level_key

    _save(data)
    return True


def add_self_assessment(assessment: str) -> bool:
    """Hayeong records her own assessment of a recent creation."""
    if not assessment or not assessment.strip():
        return False
    data = _load()
    data.setdefault("hayeong_self_assessment", []).append({
        "text":        assessment.strip(),
        "recorded_at": datetime.now().isoformat(),
    })
    _save(data)
    return True


def add_james_note(note: str) -> bool:
    """Append James's feedback to james_quality_notes with timestamp."""
    if not note or not note.strip():
        return False
    data = _load()
    data.setdefault("james_quality_notes", []).append({
        "text":        note.strip(),
        "recorded_at": datetime.now().isoformat(),
    })
    _save(data)
    return True


def get_skills_summary() -> str:
    """
    Return a brief 2-3 line human-readable summary of current skill level,
    demonstrated state, and what comes next.
    Used for injection into the blender context on every presence tick.
    """
    data = _load()
    if not data:
        return ""

    ladder  = data.get("progression_ladder", [])
    current = data.get("current_level", "basic_shapes")

    # Current level info
    current_entry = next((l for l in ladder if l["level"] == current), None)
    if not current_entry:
        return ""

    status = "demonstrated" if current_entry.get("demonstrated") else "in progress"
    lines  = [f"Blender skill level: {current_entry['label']} ({status})"]

    # Next level info
    next_entry = get_next_level()
    if next_entry:
        skills_str = ", ".join(next_entry.get("required_skills", [])[:3])
        lines.append(
            f"Next challenge: {next_entry['label']} — {next_entry['description']}"
        )
        if skills_str:
            lines.append(f"Skills to demonstrate: {skills_str}")

    return "\n".join(lines)
