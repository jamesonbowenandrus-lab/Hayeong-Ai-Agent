# task_manager.py
# Hayeong's task log — backlog, active work, completed history, blocked items.
#
# Design principles:
#   - Nothing is ever deleted. Completed tasks stay forever.
#   - Both James and Hayeong can add tasks and notes.
#   - Ongoing tasks (maintenance, learning) are valid and don't need to "complete."
#   - Blocked is a real state — she doesn't silently drop things she can't finish.
#   - Notes on any task capture the thinking, not just the outcome.
#   - Tasks requiring new code are flagged — ties into self_mod_manager + code_consultant.
#
# File: task_log.json (created automatically on first use)

import json
import uuid
import datetime
from pathlib import Path

BASE_DIR      = Path(__file__).parent
TASK_LOG_PATH = BASE_DIR / "task_log.json"

# Valid task states
STATE_BACKLOG   = "backlog"
STATE_ACTIVE    = "active"
STATE_BLOCKED   = "blocked"
STATE_COMPLETED = "completed"

# Valid task types
TYPE_TASK     = "task"       # one-off, has a clear done state
TYPE_ONGOING  = "ongoing"    # recurring or continuous — never truly "completed"
TYPE_PROJECT  = "project"    # multi-step, may have sub-tasks in notes

# Valid origins
ORIGIN_JAMES   = "james"
ORIGIN_HAYEONG = "hayeong"


def _now() -> str:
    return datetime.datetime.now().isoformat()

def _short_id() -> str:
    return str(uuid.uuid4())[:8]


class TaskManager:
    """
    Manages Hayeong's task log.

    Usage:
        tm = TaskManager()
        tm.add_task("Wire task manager into main.py", origin="james", priority="high")
        tm.add_note(task_id, "hayeong", "Started looking at main.py structure.")
        tm.complete_task(task_id, note="Done. Wired into startup and conversation loop.")
    """

    def __init__(self):
        self._log = self._load()

    # ─────────────────────────────────────────────
    # LOAD / SAVE
    # ─────────────────────────────────────────────

    def _load(self) -> dict:
        if TASK_LOG_PATH.exists():
            with open(TASK_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._empty_log()

    def _save(self):
        with open(TASK_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._log, f, indent=2, ensure_ascii=False)

    def _empty_log(self) -> dict:
        return {
            "_note": (
                "Hayeong's task log. "
                "Completed tasks are permanent — never removed. "
                "Notes capture the thinking, not just the outcome."
            ),
            STATE_BACKLOG:   [],
            STATE_ACTIVE:    [],
            STATE_BLOCKED:   [],
            STATE_COMPLETED: [],
        }

    # ─────────────────────────────────────────────
    # ADD TASK
    # ─────────────────────────────────────────────

    def add_task(
        self,
        title: str,
        description: str = "",
        origin: str = ORIGIN_JAMES,
        priority: str = "medium",
        task_type: str = TYPE_TASK,
        requires_new_code: bool = False,
        related_capability: str = None,
        initial_note: str = None,
    ) -> dict:
        """
        Add a new task to the backlog.

        title:              Short name for the task.
        description:        What needs to be done and why.
        origin:             "james" or "hayeong" — who created it.
        priority:           "high" | "medium" | "low"
        task_type:          "task" | "ongoing" | "project"
        requires_new_code:  True if this task needs new/modified code to complete.
        related_capability: Name of the capability this task relates to, if any.
        initial_note:       Optional first note on creation.
        """
        task = {
            "id":                 _short_id(),
            "title":              title,
            "description":        description,
            "origin":             origin,
            "priority":           priority,
            "type":               task_type,
            "requires_new_code":  requires_new_code,
            "related_capability": related_capability,
            "state":              STATE_BACKLOG,
            "created_at":         _now(),
            "updated_at":         _now(),
            "blocked_reason":     None,
            "completed_at":       None,
            "notes":              [],
        }

        if initial_note:
            task["notes"].append({
                "timestamp": _now(),
                "author":    origin,
                "content":   initial_note,
            })

        self._log[STATE_BACKLOG].append(task)
        self._save()
        print(f"[Tasks] Added to backlog: [{task['id']}] {title}")
        return task

    # ─────────────────────────────────────────────
    # STATE TRANSITIONS
    # ─────────────────────────────────────────────

    def start_task(self, task_id: str, note: str = None) -> dict:
        """Move a task from backlog → active."""
        task = self._find_and_remove(task_id, STATE_BACKLOG)
        if not task:
            task = self._find_and_remove(task_id, STATE_BLOCKED)
            if not task:
                raise ValueError(f"Task {task_id} not found in backlog or blocked.")

        task["state"]      = STATE_ACTIVE
        task["updated_at"] = _now()

        if note:
            task["notes"].append({
                "timestamp": _now(),
                "author":    ORIGIN_HAYEONG,
                "content":   note,
            })

        self._log[STATE_ACTIVE].append(task)
        self._save()
        print(f"[Tasks] Started: [{task_id}] {task['title']}")
        return task

    def complete_task(self, task_id: str, note: str = None) -> dict:
        """
        Move a task from active → completed.
        Completed tasks are permanent — never removed.
        For ongoing tasks, this marks a cycle complete — they can be restarted.
        """
        task = self._find_and_remove(task_id, STATE_ACTIVE)
        if not task:
            raise ValueError(f"Task {task_id} not found in active.")

        task["state"]        = STATE_COMPLETED
        task["completed_at"] = _now()
        task["updated_at"]   = _now()

        if note:
            task["notes"].append({
                "timestamp": _now(),
                "author":    ORIGIN_HAYEONG,
                "content":   f"[completed] {note}",
            })

        self._log[STATE_COMPLETED].append(task)
        self._save()
        print(f"[Tasks] Completed: [{task_id}] {task['title']}")
        return task

    def block_task(self, task_id: str, reason: str) -> dict:
        """Move a task from active → blocked. Reason is required."""
        task = self._find_and_remove(task_id, STATE_ACTIVE)
        if not task:
            raise ValueError(f"Task {task_id} not found in active.")

        task["state"]          = STATE_BLOCKED
        task["blocked_reason"] = reason
        task["updated_at"]     = _now()
        task["notes"].append({
            "timestamp": _now(),
            "author":    ORIGIN_HAYEONG,
            "content":   f"[blocked] {reason}",
        })

        self._log[STATE_BLOCKED].append(task)
        self._save()
        print(f"[Tasks] Blocked: [{task_id}] {task['title']} — {reason}")
        return task

    def unblock_task(self, task_id: str, note: str = None) -> dict:
        """Move a task from blocked → active."""
        return self.start_task(task_id, note=note or "Unblocked.")

    # ─────────────────────────────────────────────
    # NOTES
    # Append to any task in any state.
    # ─────────────────────────────────────────────

    def add_note(self, task_id: str, author: str, content: str) -> dict:
        """
        Add a note to any task regardless of state.
        author: "james" or "hayeong"
        """
        task = self._find_in_all(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found.")

        note = {
            "timestamp": _now(),
            "author":    author,
            "content":   content,
        }
        task["notes"].append(note)
        task["updated_at"] = _now()
        self._save()
        return note

    # ─────────────────────────────────────────────
    # QUERIES
    # ─────────────────────────────────────────────

    def get_active(self) -> list:
        return self._log[STATE_ACTIVE]

    def get_backlog(self) -> list:
        return self._log[STATE_BACKLOG]

    def get_blocked(self) -> list:
        return self._log[STATE_BLOCKED]

    def get_completed(self) -> list:
        """Full permanent history — oldest first."""
        return self._log[STATE_COMPLETED]

    def get_by_id(self, task_id: str) -> dict | None:
        return self._find_in_all(task_id)

    def get_high_priority(self) -> list:
        """Active + backlog tasks marked high priority."""
        return [
            t for t in self._log[STATE_ACTIVE] + self._log[STATE_BACKLOG]
            if t.get("priority") == "high"
        ]

    def get_needs_code(self) -> list:
        """Active tasks that require new or modified code."""
        return [
            t for t in self._log[STATE_ACTIVE]
            if t.get("requires_new_code")
        ]

    def summary(self) -> dict:
        """
        Quick counts for surfacing in conversation or status checks.
        """
        return {
            "active":    len(self._log[STATE_ACTIVE]),
            "backlog":   len(self._log[STATE_BACKLOG]),
            "blocked":   len(self._log[STATE_BLOCKED]),
            "completed": len(self._log[STATE_COMPLETED]),
            "needs_code": len(self.get_needs_code()),
        }

    def surface_for_conversation(self) -> str | None:
        """
        Returns a brief natural-language summary for Hayeong to mention in conversation.
        Returns None if there's nothing worth surfacing.

        This is not a status dump — it's what she'd actually bring up.
        Called by main.py at the start of a session or periodically.
        """
        active  = self._log[STATE_ACTIVE]
        blocked = self._log[STATE_BLOCKED]
        high    = self.get_high_priority()

        lines = []

        if active:
            titles = [t["title"] for t in active[:3]]
            more   = f" and {len(active) - 3} more" if len(active) > 3 else ""
            lines.append(f"Working on: {', '.join(titles)}{more}.")

        if blocked:
            lines.append(
                f"{len(blocked)} thing{'s' if len(blocked) > 1 else ''} "
                f"blocked — waiting on something."
            )

        if high and not active:
            lines.append(f"High priority in backlog: {high[0]['title']}.")

        return " ".join(lines) if lines else None

    # ─────────────────────────────────────────────
    # FORMATTING — for display in terminal or Discord
    # ─────────────────────────────────────────────

    def format_task(self, task: dict, show_notes: bool = False) -> str:
        """Format a single task for display."""
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(task.get("priority", "medium"), "⚪")
        state_icon    = {
            STATE_ACTIVE:    "▶",
            STATE_BACKLOG:   "·",
            STATE_BLOCKED:   "⏸",
            STATE_COMPLETED: "✓",
        }.get(task.get("state", ""), "?")

        origin = task.get("origin", "?")
        code_flag = " [needs code]" if task.get("requires_new_code") else ""

        lines = [
            f"{state_icon} {priority_icon} [{task['id']}] {task['title']}{code_flag}",
            f"   {task.get('description', '')[:80]}" if task.get("description") else "",
            f"   origin: {origin} | type: {task.get('type', '?')}",
        ]

        if task.get("blocked_reason"):
            lines.append(f"   blocked: {task['blocked_reason']}")

        if task.get("completed_at"):
            lines.append(f"   completed: {task['completed_at'][:10]}")

        if show_notes and task.get("notes"):
            lines.append("   notes:")
            for note in task["notes"][-5:]:  # last 5 notes
                ts     = note["timestamp"][:16].replace("T", " ")
                author = note["author"]
                lines.append(f"     [{ts}] {author}: {note['content'][:100]}")

        return "\n".join(l for l in lines if l)

    def format_list(
        self,
        state: str = None,
        show_notes: bool = False,
        limit: int = 20,
    ) -> str:
        """
        Format a list of tasks for display.
        state: "active" | "backlog" | "blocked" | "completed" | None (all)
        """
        if state:
            tasks = self._log.get(state, [])
            header = f"── {state.upper()} ──────────────────────"
        else:
            tasks  = (
                self._log[STATE_ACTIVE] +
                self._log[STATE_BLOCKED] +
                self._log[STATE_BACKLOG]
            )
            header = "── TASKS ──────────────────────────"

        if not tasks:
            return f"{header}\n  (none)"

        lines = [header]
        for task in tasks[:limit]:
            lines.append(self.format_task(task, show_notes=show_notes))
            lines.append("")

        if len(tasks) > limit:
            lines.append(f"  ... and {len(tasks) - limit} more.")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────────

    def _find_and_remove(self, task_id: str, state: str) -> dict | None:
        bucket = self._log[state]
        for i, task in enumerate(bucket):
            if task["id"] == task_id:
                return bucket.pop(i)
        return None

    def _find_in_all(self, task_id: str) -> dict | None:
        for state in [STATE_ACTIVE, STATE_BACKLOG, STATE_BLOCKED, STATE_COMPLETED]:
            for task in self._log[state]:
                if task["id"] == task_id:
                    return task
        return None


# ─────────────────────────────────────────────
# INTENT DETECTION
# Called by main.py to recognize task-related requests
# without sending them to the AI model.
# ─────────────────────────────────────────────

_TASK_SHOW_PATTERNS = [
    "what are you working on", "show tasks", "show your tasks",
    "what's on your list", "what's in your backlog", "task list",
    "what do you have to do", "show me your tasks", "show completed",
    "what have you done", "show history", "what's blocked",
]

_TASK_ADD_PATTERNS = [
    "add a task", "add task", "new task", "create a task",
    "put this on your list", "add this to your backlog",
    "i need you to", "can you work on",
]

_TASK_COMPLETE_PATTERNS = [
    "mark", "complete", "done", "finish", "finished", "close task",
]

_TASK_NOTE_PATTERNS = [
    "add a note", "note on", "note for task",
]


def detect_task_command(text: str) -> tuple[str, str] | tuple[None, None]:
    """
    Returns (command, remainder) or (None, None).
    command: "show" | "show_completed" | "show_blocked" | "add" | "complete" | "note"
    remainder: the rest of the text after the command keyword (may be empty)
    """
    t = text.lower().strip()

    if "show completed" in t or "what have you done" in t or "show history" in t:
        return "show_completed", t

    if "what's blocked" in t or "what is blocked" in t or "show blocked" in t:
        return "show_blocked", t

    for p in _TASK_SHOW_PATTERNS:
        if p in t:
            return "show", t

    for p in _TASK_ADD_PATTERNS:
        if p in t:
            return "add", t[t.index(p) + len(p):].strip()

    for p in _TASK_COMPLETE_PATTERNS:
        if t.startswith(p) or f" {p} " in t:
            return "complete", t

    for p in _TASK_NOTE_PATTERNS:
        if p in t:
            return "note", t

    return None, None


# ─────────────────────────────────────────────
# QUICK-ADD HELPER
# Used by main.py when James says something like
# "add a task: wire self_mod into main"
# Parses title and optional priority from natural language.
# ─────────────────────────────────────────────

def parse_task_from_text(text: str, origin: str = ORIGIN_JAMES) -> dict:
    """
    Parse a natural language task description into task fields.
    Returns kwargs suitable for TaskManager.add_task().

    Examples:
        "wire self_mod into main"
        "high priority: fix discord voice"
        "ongoing: check memory health daily"
    """
    priority   = "medium"
    task_type  = TYPE_TASK
    needs_code = False

    t = text.strip()

    # Priority prefix: "high: ..." or "high priority: ..."
    for word in ["high priority:", "high:", "urgent:"]:
        if t.lower().startswith(word):
            priority = "high"
            t = t[len(word):].strip()
            break
    for word in ["low priority:", "low:"]:
        if t.lower().startswith(word):
            priority = "low"
            t = t[len(word):].strip()
            break

    # Type prefix: "ongoing: ..." or "project: ..."
    if t.lower().startswith("ongoing:"):
        task_type = TYPE_ONGOING
        t = t[8:].strip()
    elif t.lower().startswith("project:"):
        task_type = TYPE_PROJECT
        t = t[8:].strip()

    # Code flag
    if any(w in t.lower() for w in ["write code", "new script", "create script",
                                      "modify code", "needs code", "add capability"]):
        needs_code = True

    return {
        "title":             t[:100],
        "description":       t,
        "origin":            origin,
        "priority":          priority,
        "task_type":         task_type,
        "requires_new_code": needs_code,
    }


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import shutil

    # Use a test file so we don't touch the real log
    TASK_LOG_PATH = BASE_DIR / "task_log_test.json"

    tm = TaskManager()
    print("=== TASK MANAGER TEST ===\n")

    # Add tasks
    t1 = tm.add_task(
        "Wire task_manager into main.py",
        description="Import TaskManager, add startup display, add intent detection.",
        origin="james",
        priority="high",
        initial_note="This is the foundation for everything else.",
    )
    t2 = tm.add_task(
        "Install deepseek-coder for code generation",
        description="Pull deepseek-coder:33b via ollama, test on a simple capability script.",
        origin="james",
        priority="high",
        requires_new_code=False,
    )
    t3 = tm.add_task(
        "Ongoing: Daily memory health check",
        description="Check long-term memory for duplicates and orphaned entries.",
        origin="hayeong",
        priority="low",
        task_type=TYPE_ONGOING,
    )

    print("\n" + tm.format_list())

    # Start and add notes
    tm.start_task(t1["id"], note="Looking at main.py structure now.")
    tm.add_note(t1["id"], "hayeong", "Found where startup sequence runs — good place to init.")
    tm.add_note(t1["id"], "james", "Make sure it shows active tasks at startup, not just a count.")

    # Block one
    tm.start_task(t2["id"])
    tm.block_task(t2["id"], "Waiting to test ollama pull — need to check VRAM first.")

    print("\n" + tm.format_list(show_notes=True))

    # Complete one
    tm.complete_task(t1["id"], note="Wired in. Startup shows tasks, intent detection works.")
    print("\n" + tm.format_list(STATE_COMPLETED, show_notes=True))

    # Surface for conversation
    msg = tm.surface_for_conversation()
    print(f"\nSurface message: {msg!r}")

    # Summary
    print(f"\nSummary: {tm.summary()}")

    # Cleanup
    TASK_LOG_PATH.unlink(missing_ok=True)
    print("\nTest complete. task_log_test.json removed.")
