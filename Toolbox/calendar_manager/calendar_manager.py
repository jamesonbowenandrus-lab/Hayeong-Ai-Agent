"""
Toolbox/calendar_manager/calendar_manager.py

Gives Hayeong temporal awareness and planning capability.
Tracks events, schedules tasks, manages reminders.

Called via registry:
    module:   toolbox.calendar_manager.calendar_manager
    function: run

Params:
    operation  (str) — add | list | complete | delete | add_reminder | check_due
    title      (str) — event title
    date       (str) — YYYY-MM-DD or natural: tomorrow, next Thursday, in 3 days
    time       (str) — HH:MM optional
    type       (str) — james_event | hayeong_task | reminder | deadline
    notes      (str) — optional context
    event_id   (str) — for complete/delete operations
    days       (int) — how many days ahead to list (default 7)
"""

import json
from pathlib import Path
from datetime import datetime, date, timedelta

ROOT_DIR     = Path(__file__).parent.parent.parent
CALENDAR_FILE = ROOT_DIR / "Toolbox" / "calendar_manager" / "calendar.json"
REMINDER_FILE = ROOT_DIR / "Toolbox" / "calendar_manager" / "reminders.json"


def run(description: str, params: dict) -> str:
    try:
        operation = params.get("operation", "list").lower()
        if operation == "add":
            return _add_event(params)
        elif operation == "list":
            days = int(params.get("days", 7))
            return _list_events(days)
        elif operation == "complete":
            return _complete_event(params.get("event_id", ""))
        elif operation == "delete":
            return _delete_event(params.get("event_id", ""))
        elif operation == "add_reminder":
            return _add_reminder(params)
        elif operation == "check_due":
            return _check_due()
        else:
            return f"Unknown operation '{operation}'. Use: add, list, complete, delete, add_reminder, check_due"
    except Exception as e:
        return f"calendar_manager error: {e}"


def _load_calendar() -> list:
    if not CALENDAR_FILE.exists():
        return []
    try:
        return json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_calendar(events: list) -> None:
    CALENDAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_date(date_str: str) -> str:
    if not date_str:
        return date.today().isoformat()
    s = date_str.strip().lower()
    today = date.today()
    if s == "today":
        return today.isoformat()
    if s == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if s.startswith("in ") and "day" in s:
        try:
            n = int(s.split()[1])
            return (today + timedelta(days=n)).isoformat()
        except Exception:
            pass
    if s.startswith("next "):
        day_name = s.replace("next ", "").strip()
        days_map = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
                    "friday":4,"saturday":5,"sunday":6}
        if day_name in days_map:
            target = days_map[day_name]
            current = today.weekday()
            delta = (target - current + 7) % 7 or 7
            return (today + timedelta(days=delta)).isoformat()
    if s == "end of week":
        delta = 4 - today.weekday()
        if delta < 0:
            delta += 7
        return (today + timedelta(days=delta)).isoformat()
    return date_str


def _add_event(params: dict) -> str:
    events = _load_calendar()
    event_id = datetime.now().strftime("%Y%m%d%H%M%S")
    event = {
        "id":        event_id,
        "title":     params.get("title", "Untitled"),
        "date":      _parse_date(params.get("date", "")),
        "time":      params.get("time", ""),
        "type":      params.get("type", "hayeong_task"),
        "notes":     params.get("notes", ""),
        "status":    "pending",
        "created":   datetime.now().isoformat(),
    }
    events.append(event)
    _save_calendar(events)
    return f"Event added: '{event['title']}' on {event['date']} (id: {event_id})"


def _list_events(days: int = 7) -> str:
    events = _load_calendar()
    today  = date.today()
    cutoff = (today + timedelta(days=days)).isoformat()
    today_str = today.isoformat()
    upcoming = [e for e in events
                if e.get("status") == "pending"
                and today_str <= e.get("date", "") <= cutoff]
    upcoming.sort(key=lambda e: e.get("date", ""))
    if not upcoming:
        return f"No events in the next {days} days."
    lines = [f"Events in next {days} days:"]
    for e in upcoming:
        time_str = f" at {e['time']}" if e.get("time") else ""
        lines.append(f"  [{e['type']}] {e['date']}{time_str} — {e['title']} (id: {e['id']})")
    return "\n".join(lines)


def _complete_event(event_id: str) -> str:
    if not event_id:
        return "event_id required for complete operation."
    events = _load_calendar()
    for e in events:
        if e["id"] == event_id:
            e["status"] = "completed"
            e["completed_at"] = datetime.now().isoformat()
            _save_calendar(events)
            return f"Event '{e['title']}' marked complete."
    return f"Event id '{event_id}' not found."


def _delete_event(event_id: str) -> str:
    if not event_id:
        return "event_id required for delete operation."
    events = _load_calendar()
    before = len(events)
    events = [e for e in events if e["id"] != event_id]
    if len(events) == before:
        return f"Event id '{event_id}' not found."
    _save_calendar(events)
    return f"Event '{event_id}' deleted."


def _add_reminder(params: dict) -> str:
    if not REMINDER_FILE.parent.exists():
        REMINDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        reminders = json.loads(REMINDER_FILE.read_text(encoding="utf-8")) if REMINDER_FILE.exists() else []
    except Exception:
        reminders = []
    reminder = {
        "id":      datetime.now().strftime("%Y%m%d%H%M%S"),
        "title":   params.get("title", "Reminder"),
        "date":    _parse_date(params.get("date", "")),
        "time":    params.get("time", ""),
        "notes":   params.get("notes", ""),
        "status":  "pending",
    }
    reminders.append(reminder)
    REMINDER_FILE.write_text(json.dumps(reminders, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"Reminder added: '{reminder['title']}' on {reminder['date']}"


def _check_due() -> str:
    events    = _load_calendar()
    today_str = date.today().isoformat()
    due = [e for e in events
           if e.get("status") == "pending" and e.get("date", "") <= today_str]
    if not due:
        return "No events due today or overdue."
    lines = [f"{len(due)} event(s) due:"]
    for e in due:
        lines.append(f"  [{e['type']}] {e['date']} — {e['title']}")
    return "\n".join(lines)