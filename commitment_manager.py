"""
commitment_manager.py
Tracks commitments Hayeong makes during conversation.
Imported by reasoning_loop.py as: from commitment_manager import ...
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

COMMITMENTS_FILE = Path(__file__).parent / "Brain" / "state" / "commitments.json"


def _load() -> list:
    try:
        return json.loads(COMMITMENTS_FILE.read_text(encoding="utf-8")).get("commitments", [])
    except Exception:
        return []


def _save(commitments: list):
    COMMITMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMMITMENTS_FILE.write_text(
        json.dumps({"commitments": commitments}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_commitment(text: str, due_within: int = 300) -> str:
    """Add a commitment. due_within is seconds until overdue. Returns the commitment ID."""
    commitments = _load()
    cmt = {
        "id":           f"cmt_{uuid.uuid4().hex[:6]}",
        "text":         text,
        "made_at":      datetime.now().isoformat(),
        "due_within":   due_within,
        "status":       "active",
        "fulfilled_at": None,
    }
    commitments.append(cmt)
    _save(commitments)
    return cmt["id"]


def fulfill_commitment(cmt_id: str):
    commitments = _load()
    for c in commitments:
        if c["id"] == cmt_id:
            c["status"]       = "fulfilled"
            c["fulfilled_at"] = datetime.now().isoformat()
    _save(commitments)


def get_all_active() -> list:
    return [c for c in _load() if c.get("status") == "active"]


def get_overdue() -> list:
    now = datetime.now()
    overdue = []
    for c in _load():
        if c.get("status") != "active":
            continue
        try:
            made    = datetime.fromisoformat(c["made_at"])
            elapsed = (now - made).total_seconds()
            if elapsed > c.get("due_within", 300):
                overdue.append(c)
        except Exception:
            pass
    return overdue
