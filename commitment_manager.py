"""
commitment_manager.py
Tracks promises Hayeong makes and raises them as priority flags when overdue.
Called by: reasoning_loop.py (every tick), communication detection in main.py
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

COMMITMENTS_FILE = Path(__file__).parent / "state" / "commitments.json"


def _read() -> dict:
    if not COMMITMENTS_FILE.exists():
        return {"commitments": []}
    try:
        with open(COMMITMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"commitments": []}


def _write(data: dict):
    COMMITMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COMMITMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_commitment(text: str, due_within: int = 300) -> str:
    """
    Record a new commitment. Returns the commitment ID.
    Call this whenever Hayeong promises to do or check something.
    due_within: seconds until overdue (default 300 = 5 minutes)
    """
    data = _read()
    cmt = {
        "id":           f"cmt_{uuid.uuid4().hex[:6]}",
        "text":         text,
        "made_at":      datetime.now().isoformat(),
        "due_within":   due_within,
        "status":       "pending",
        "fulfilled_at": None,
    }
    data["commitments"].append(cmt)
    _write(data)
    print(f"[commitments] Added: {text[:80]}")
    return cmt["id"]


def fulfill_commitment(commitment_id: str):
    """Mark a commitment as fulfilled."""
    data = _read()
    for cmt in data["commitments"]:
        if cmt["id"] == commitment_id and cmt["status"] == "pending":
            cmt["status"]       = "fulfilled"
            cmt["fulfilled_at"] = datetime.now().isoformat()
            break
    _write(data)


def drop_commitment(commitment_id: str):
    """Mark a commitment as intentionally dropped (no longer relevant)."""
    data = _read()
    for cmt in data["commitments"]:
        if cmt["id"] == commitment_id:
            cmt["status"] = "dropped"
            break
    _write(data)


def get_overdue() -> list:
    """
    Return all pending commitments that have exceeded their due_within window.
    Updates their status to 'overdue' in place.
    """
    data    = _read()
    now     = datetime.now()
    overdue = []
    changed = False

    for cmt in data["commitments"]:
        if cmt["status"] != "pending":
            continue
        made_at = datetime.fromisoformat(cmt["made_at"])
        elapsed = (now - made_at).total_seconds()
        if elapsed > cmt["due_within"]:
            cmt["status"] = "overdue"
            overdue.append(cmt)
            changed = True

    if changed:
        _write(data)
    return overdue


def get_pending() -> list:
    """Return all commitments that are still pending (not yet overdue)."""
    data    = _read()
    now     = datetime.now()
    pending = []
    for cmt in data["commitments"]:
        if cmt["status"] != "pending":
            continue
        made_at = datetime.fromisoformat(cmt["made_at"])
        elapsed = (now - made_at).total_seconds()
        if elapsed <= cmt["due_within"]:
            pending.append(cmt)
    return pending


def get_all_active() -> list:
    """Return all pending + overdue commitments."""
    data = _read()
    return [c for c in data["commitments"] if c["status"] in ("pending", "overdue")]
