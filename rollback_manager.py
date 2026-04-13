# rollback_manager.py
# Per-action audit log for Hayeong's autonomous operations.
#
# Every autonomous action Hayeong takes — writing a capability, modifying a JSON
# field, registering a new entry — gets logged here with enough information to
# reverse it. Mistakes become recoverable instead of permanent.
#
# This is a complement to backup_manager.py, not a replacement:
#   backup_manager.py  — full directory snapshots, coarse-grained disaster recovery
#   rollback_manager.py — per-operation before/after log, fine-grained single-action undo
#
# Usage:
#   from rollback_manager import RollbackManager, snapshot_file
#
#   rollback = RollbackManager()
#   before   = snapshot_file(target_path)
#   target_path.write_text(new_code, encoding="utf-8")
#   rollback.log_action(
#       action_type   = "write_file",
#       description   = f"Wrote new capability: {filename}",
#       before_state  = before,
#       after_state   = {"path": str(target_path), "content": new_code},
#       triggered_by  = "self_mod",
#       rollback_cmd  = "delete_file" if not before["existed"] else "restore_file",
#       rollback_args = {"path": str(target_path)},
#   )

import json
import uuid
from datetime import datetime, date
from pathlib import Path

BASE_DIR = Path(__file__).parent


# ─────────────────────────────────────────────
# ACTION TYPES
# ─────────────────────────────────────────────

ACTION_TYPES = [
    "write_file",             # created a new file
    "modify_file",            # changed an existing file
    "delete_file",            # deleted a file (content in before_state)
    "json_field_set",         # changed a specific field in a JSON file
    "email_sent",             # sent an email — not reversible
    "capability_registered",  # added entry to capability_registry.json
    "task_added",             # added a task to task log
    "staging_submitted",      # submitted a staging proposal
]


# ─────────────────────────────────────────────
# PRE-ACTION SNAPSHOT HELPER
# ─────────────────────────────────────────────

def snapshot_file(path) -> dict:
    """
    Capture the current state of a file before modifying it.
    Returns a before_state dict ready to pass to log_action().

    If the file exists, captures its content.
    If it doesn't, records that it didn't exist (so rollback knows to delete it).
    """
    p = Path(path)
    if p.exists():
        return {
            "path":    str(p),
            "existed": True,
            "content": p.read_text(encoding="utf-8"),
        }
    return {
        "path":    str(p),
        "existed": False,
        "content": None,
    }


# ─────────────────────────────────────────────
# ROLLBACK MANAGER
# ─────────────────────────────────────────────

class RollbackManager:
    """
    Per-action audit log for Hayeong's autonomous operations.
    Logs before/after state for every autonomous action.
    Supports single-action rollback and last-N rollback.

    Log is stored as JSONL (one JSON object per line) at logs/rollback_log.jsonl.
    Each line is a complete, self-contained action record.
    """

    LOG_PATH = BASE_DIR / "logs" / "rollback_log.jsonl"

    def __init__(self):
        self.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._session_start = datetime.now().isoformat()

    # ─────────────────────────────────────────
    # LOG AN ACTION
    # ─────────────────────────────────────────

    def log_action(
        self,
        action_type:  str,
        description:  str,
        before_state: dict,
        after_state:  dict,
        triggered_by: str  = "autonomous",
        approved_by:  str  = "autonomous",
        reversible:   bool = True,
        rollback_cmd: str  = "",
        rollback_args: dict = None,
        notes: str = "",
    ) -> str:
        """
        Log one autonomous action. Returns the action ID (8-char UUID prefix).
        Call this AFTER the action completes successfully.

        action_type:   One of ACTION_TYPES
        description:   Human-readable description of what happened
        before_state:  State before the action (use snapshot_file() for file ops)
        after_state:   State after the action
        triggered_by:  Which system initiated this ("self_mod", "capability", etc.)
        approved_by:   "autonomous" or "james"
        reversible:    Whether this action can be undone
        rollback_cmd:  "delete_file" | "restore_file" | "restore_json_field" | "not_reversible"
        rollback_args: Arguments the rollback operation needs
        notes:         Any additional context
        """
        action_id = uuid.uuid4().hex[:8]

        entry = {
            "id":           action_id,
            "timestamp":    datetime.now().isoformat(),
            "action_type":  action_type,
            "description":  description,
            "triggered_by": triggered_by,
            "approved_by":  approved_by,
            "reversible":   reversible,
            "rolled_back":  False,
            "before_state": before_state,
            "after_state":  after_state,
            "rollback_cmd": rollback_cmd if reversible else "not_reversible",
            "rollback_args": rollback_args or {},
            "notes":        notes,
        }

        with open(self.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return action_id

    # ─────────────────────────────────────────
    # RETRIEVE ACTIONS
    # ─────────────────────────────────────────

    def get_action(self, action_id: str) -> dict | None:
        """Retrieve a single action log entry by ID."""
        if not self.LOG_PATH.exists():
            return None
        with open(self.LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("id") == action_id:
                        return entry
                except json.JSONDecodeError:
                    continue
        return None

    def list_actions(self, limit: int = 20, rolled_back: bool = None) -> list:
        """
        List recent logged actions, newest first.
        rolled_back=None returns all, True returns only rolled-back, False returns active.
        """
        if not self.LOG_PATH.exists():
            return []
        entries = []
        with open(self.LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if rolled_back is None or entry.get("rolled_back") == rolled_back:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        # Newest first, limited
        return entries[-limit:][::-1]

    # ─────────────────────────────────────────
    # ROLLBACK
    # ─────────────────────────────────────────

    def rollback_action(self, action_id: str) -> dict:
        """
        Reverse a single logged action by its ID.
        Returns {"success": bool, "message": str}
        """
        entry = self.get_action(action_id)
        if not entry:
            return {"success": False, "message": f"Action {action_id} not found"}
        if entry.get("rolled_back"):
            return {"success": False, "message": f"Action {action_id} already rolled back"}
        if not entry.get("reversible"):
            return {
                "success": False,
                "message": f"Action {action_id} ({entry.get('action_type')}) is not reversible",
            }

        cmd  = entry.get("rollback_cmd")
        args = entry.get("rollback_args", {})

        try:
            if cmd == "delete_file":
                path = Path(args["path"])
                if path.exists():
                    path.unlink()
                message = f"Deleted {args['path']}"

            elif cmd == "restore_file":
                path    = Path(args["path"])
                content = entry["before_state"].get("content", "")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                message = f"Restored {args['path']} to previous content"

            elif cmd == "restore_json_field":
                path      = Path(args["path"])
                key_path  = args["key_path"]   # dot-notation e.g. "mood.focus"
                old_value = entry["before_state"]["value"]
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                keys = key_path.split(".")
                obj  = data
                for key in keys[:-1]:
                    obj = obj[key]
                obj[keys[-1]] = old_value
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                message = f"Restored {key_path} in {args['path']} to {old_value!r}"

            elif cmd == "not_reversible":
                return {
                    "success": False,
                    "message": f"Action {action_id} ({entry.get('action_type')}) cannot be undone",
                }

            else:
                return {"success": False, "message": f"Unknown rollback command: {cmd!r}"}

            self._mark_rolled_back(action_id)
            return {"success": True, "message": message}

        except Exception as e:
            return {"success": False, "message": f"Rollback failed: {e}"}

    def rollback_last(self, n: int = 1) -> list:
        """
        Roll back the last N actions in reverse order (most recent first).
        Skips already-rolled-back and non-reversible entries.
        Returns list of {"action_id": str, "success": bool, "message": str}.
        """
        candidates = [
            e for e in self.list_actions(limit=n * 3)
            if not e.get("rolled_back") and e.get("reversible")
        ][:n]

        results = []
        for entry in candidates:
            result = self.rollback_action(entry["id"])
            result["action_id"] = entry["id"]
            results.append(result)
        return results

    # ─────────────────────────────────────────
    # SESSION SUMMARY
    # ─────────────────────────────────────────

    def session_summary(self) -> str:
        """Human-readable summary of actions logged today."""
        today = date.today().isoformat()
        entries = []
        if self.LOG_PATH.exists():
            with open(self.LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        if e.get("timestamp", "").startswith(today):
                            entries.append(e)
                    except json.JSONDecodeError:
                        continue

        if not entries:
            return "No autonomous actions logged today."

        lines = [f"Actions logged today ({len(entries)}):"]
        for e in entries:
            ts      = e.get("timestamp", "?")[:16].replace("T", " ")
            status  = "↩ rolled back" if e.get("rolled_back") else "active"
            rev     = "" if e.get("reversible") else " [not reversible]"
            lines.append(f"  [{ts}] {e['action_type']}{rev} — {e['description']} ({status})")
        return "\n".join(lines)

    # ─────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────

    def _mark_rolled_back(self, action_id: str):
        """Rewrite the log file with the target entry marked as rolled back."""
        if not self.LOG_PATH.exists():
            return
        lines = []
        with open(self.LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    lines.append(line)
                    continue
                try:
                    entry = json.loads(stripped)
                    if entry.get("id") == action_id:
                        entry["rolled_back"] = True
                        lines.append(json.dumps(entry) + "\n")
                    else:
                        lines.append(line)
                except json.JSONDecodeError:
                    lines.append(line)
        with open(self.LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)


# ─────────────────────────────────────────────
# MODULE-LEVEL SINGLETON
# ─────────────────────────────────────────────

_rollback = RollbackManager()


def log_action(*args, **kwargs) -> str:
    """Module-level shortcut — no instantiation needed."""
    return _rollback.log_action(*args, **kwargs)


def rollback_last(n: int = 1) -> list:
    return _rollback.rollback_last(n)


def session_summary() -> str:
    return _rollback.session_summary()


# ─────────────────────────────────────────────
# DEBUG / TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile, os

    rm = RollbackManager()
    print("RollbackManager — self-test\n")

    # Test 1: write_file rollback
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w") as f:
        test_path = f.name
        f.write("# test file\n")

    before = snapshot_file(test_path)
    Path(test_path).write_text("# modified\n", encoding="utf-8")
    aid = rm.log_action(
        action_type   = "modify_file",
        description   = "Self-test: modified temp file",
        before_state  = before,
        after_state   = {"path": test_path, "content": "# modified\n"},
        triggered_by  = "test",
        rollback_cmd  = "restore_file",
        rollback_args = {"path": test_path},
    )
    print(f"Logged action: {aid}")

    result = rm.rollback_action(aid)
    print(f"Rollback result: {result}")
    assert Path(test_path).read_text() == "# test file\n", "Content not restored!"
    print("Content restored correctly.")

    result2 = rm.rollback_action(aid)
    print(f"Double-rollback guard: {result2}")
    assert not result2["success"]

    os.unlink(test_path)

    # Test 2: non-reversible
    aid2 = rm.log_action(
        action_type  = "email_sent",
        description  = "Self-test: sent email",
        before_state = {},
        after_state  = {},
        reversible   = False,
        rollback_cmd = "not_reversible",
    )
    result3 = rm.rollback_action(aid2)
    print(f"Non-reversible guard: {result3}")
    assert not result3["success"]

    print("\nSession summary:")
    print(rm.session_summary())
    print("\nAll tests passed.")
