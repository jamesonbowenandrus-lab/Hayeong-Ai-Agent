# capabilities/tasks_cap.py
# Task manager capability — show and add tasks.

import re
from capability_loader import result

ACTIONS = ["task_show", "task_add"]


def handle(action: str, user_input: str, context: dict) -> dict:
    tasks    = context.get("tasks")
    decision = context.get("decision", {})

    if tasks is None:
        return result(success=False, speak="Task manager isn't available right now.")

    try:
        if action == "task_show":
            task_list = tasks.format_list()
            return result(success=True, response=f"[TASKS]\n{task_list}")

        elif action == "task_add":
            task_text = decision.get("task_text") or re.sub(
                r'(?i)(add a task|add task|remember to|i need to)[:\s]*', '', user_input
            ).strip() or user_input

            try:
                from task_manager import parse_task_from_text
                kwargs = parse_task_from_text(task_text, origin="james")
            except ImportError:
                kwargs = {"title": task_text}

            new_task = tasks.add_task(**kwargs)
            return result(success=True, response=f"[TASK ADDED] {new_task['title']}")

    except Exception as e:
        return result(success=False, data={"error": str(e)})
