"""
Toolbox/calendar_manager/plugin.py

Injects upcoming events and temporal context into shared state.
"""

from pathlib import Path
from datetime import date, timedelta
import json

ROOT_DIR      = Path(__file__).parent.parent.parent
CALENDAR_FILE = ROOT_DIR / "Toolbox" / "calendar_manager" / "calendar.json"


def tick(state: dict) -> dict:
    try:
        if not CALENDAR_FILE.exists():
            return {}
        events  = json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))
        today   = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()
        week_end = (today + timedelta(days=7)).isoformat()
        today_str = today.isoformat()

        upcoming_24h = [e["title"] for e in events
                        if e.get("status") == "pending"
                        and today_str <= e.get("date", "") <= tomorrow]
        upcoming_week = [e["title"] for e in events
                         if e.get("status") == "pending"
                         and today_str <= e.get("date", "") <= week_end]
        overdue = [e["title"] for e in events
                   if e.get("status") == "pending"
                   and e.get("date", "") < today_str]

        return {
            "temporal_context": {
                "today":          today_str,
                "day_of_week":    today.strftime("%A"),
                "upcoming_24h":   upcoming_24h,
                "upcoming_week":  upcoming_week,
                "overdue":        overdue,
            }
        }
    except Exception:
        return {}


def get_context_injection(state: dict) -> str:
    tc = state.get("temporal_context", {})
    if not tc:
        return ""
    lines = [f"TODAY: {tc.get('day_of_week', '')} {tc.get('today', '')}"]
    if tc.get("overdue"):
        lines.append(f"OVERDUE: {', '.join(tc['overdue'])}")
    if tc.get("upcoming_24h"):
        lines.append(f"NEXT 24H: {', '.join(tc['upcoming_24h'])}")
    return "\n".join(lines)