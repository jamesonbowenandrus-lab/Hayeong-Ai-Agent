# capabilities/tasks_cap.py
# Task management capability — migrated out of main.py.
#
# Handles: task_show, task_add actions from context_router
# Uses TaskManager — creates its own instance lazily.
# State is shared via task_log.json so all references stay in sync.

from capability_loader import result

ACTIONS = ["task_show", "task_add"]

# ─────────────────────────────────────────────
# LAZY IMPORT
# ─────────────────────────────────────────────

_tasks = None

def _get_tasks():
    global _tasks
    if _tasks is None:
        try:
            from task_manager import TaskManager
            _tasks = TaskManager()
        except ImportError:
            pass
    return _tasks


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    tasks = _get_tasks()
    if tasks is None:
        return result(
            success=False,
            speak="Task manager isn't available right now.",
        )

    if action == "task_show":
        return _handle_show(tasks, context)
    elif action == "task_add":
        return _handle_add(tasks, user_input, context)

    return result(success=False, data={"reason": "unknown_action"})


# ─────────────────────────────────────────────
# SHOW TASKS
# ─────────────────────────────────────────────

def _handle_show(tasks, context: dict) -> dict:
    # Reload from disk — another instance (e.g. startup display) may have updated it
    tasks._log = tasks._load()

    active  = tasks._log.get("active",  [])
    backlog = tasks._log.get("backlog", [])
    blocked = tasks._log.get("blocked", [])

    if not active and not backlog and not blocked:
        return result(
            success=True,
            response="[TASKS]: No tasks in the log yet.",
            speak="Nothing on the list.",
        )

    lines = ["[TASK LOG]"]

    if active:
        lines.append(f"\nActive ({len(active)}):")
        for t in active:
            pri = t.get("priority", "medium")
            lines.append(f"  [{t['id']}] {t['title']}  ({pri})")

    if backlog:
        lines.append(f"\nBacklog ({len(backlog)}):")
        for t in backlog[:5]:   # cap at 5 to keep prompt lean
            pri = t.get("priority", "medium")
            lines.append(f"  [{t['id']}] {t['title']}  ({pri})")
        if len(backlog) > 5:
            lines.append(f"  ... and {len(backlog) - 5} more")

    if blocked:
        lines.append(f"\nBlocked ({len(blocked)}):")
        for t in blocked:
            reason = t.get("blocked_reason", "")
            lines.append(f"  [{t['id']}] {t['title']}" + (f"  — {reason}" if reason else ""))

    response_ctx = "\n".join(lines)
    return result(
        success=True,
        response=response_ctx,
        speak="Here's what's on the list.",
        data={"active": len(active), "backlog": len(backlog), "blocked": len(blocked)},
    )


# ─────────────────────────────────────────────
# ADD TASK
# ─────────────────────────────────────────────

def _handle_add(tasks, user_input: str, context: dict) -> dict:
    decision  = context.get("decision", {})
    task_text = decision.get("task_text") or user_input

    if not task_text or len(task_text.strip()) < 3:
        return result(
            success=False,
            speak="What should I add to the list?",
        )

    try:
        task = tasks.add_task(
            title=task_text.strip(),
            origin="james",
            priority="medium",
        )
    except Exception as e:
        return result(
            success=False,
            speak="I couldn't add that to the list.",
            data={"error": str(e)},
        )

    return result(
        success=True,
        response=f"[TASK ADDED]: [{task['id']}] {task['title']}. Acknowledge that you've added it to the backlog.",
        speak="Added.",
        data={"task_id": task["id"], "title": task["title"]},
    )
