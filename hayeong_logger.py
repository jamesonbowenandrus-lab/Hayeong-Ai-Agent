"""
hayeong_logger.py
─────────────────
Hayeong's comprehensive logging system. Captures everything that matters —
conversations, decisions, image generations, capability usage, goal progress,
earnings, and growth milestones.

DESIGN PHILOSOPHY:
  - Nothing is ever deleted. Every log entry is permanent.
  - Logs are human readable — James can open them and understand them.
  - Hayeong can query her own logs to understand her history and growth.
  - Goal tracking is built in — every earning toward the workstation is recorded.
  - Sessions are grouped — you can review a whole conversation as one unit.
  - Summaries are generated automatically — daily, weekly, milestone.

LOG STRUCTURE:
  logs/
    sessions/          ← Full conversation logs per session
    events/            ← Individual event logs by date
    goals/             ← Goal progress and earnings tracking
    images/            ← Image generation history with prompts and outcomes
    capabilities/      ← Capability usage and performance
    growth/            ← Milestones, improvements, learning moments
    summaries/         ← Auto-generated daily and weekly summaries

USAGE:
  from hayeong_logger import HayeongLogger
  logger = HayeongLogger()

  logger.log_conversation(role="james", content="Draw me Hayeong in the park")
  logger.log_conversation(role="hayeong", content="On it!")

  logger.log_image_generation(
      prompt="anime girl, orange frog jacket...",
      output_path="H:/ComfyUI/.../Hayeong_00042.png",
      model="ponyDiffusionV6XL",
      outcome="success",
      feedback="hood still up, try again"
  )

  logger.log_earning(amount=45.00, source="Etsy", description="VTuber emote pack")
  logger.log_milestone("First successful image generation")

  summary = logger.daily_summary()
  report  = logger.generate_summary_report("week")
"""

import json
import uuid
import os
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List, Any

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

BASE_DIR      = Path(__file__).parent
LOGS_DIR      = BASE_DIR / "logs"
SESSIONS_DIR  = LOGS_DIR / "sessions"
EVENTS_DIR    = LOGS_DIR / "events"
GOALS_DIR     = LOGS_DIR / "goals"
IMAGES_DIR    = LOGS_DIR / "images"
CAPS_DIR      = LOGS_DIR / "capabilities"
GROWTH_DIR    = LOGS_DIR / "growth"
SUMMARIES_DIR = LOGS_DIR / "summaries"

for d in [LOGS_DIR, SESSIONS_DIR, EVENTS_DIR, GOALS_DIR,
          IMAGES_DIR, CAPS_DIR, GROWTH_DIR, SUMMARIES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# WORKSTATION GOAL
# ─────────────────────────────────────────────

WORKSTATION_GOAL = {
    "name": "Hayeong's Workstation PC",
    "target_amount": 3000.00,
    "currency": "USD",
    "description": "A high-performance PC for Hayeong to run her own models, generate video, and eventually host herself independently.",
    "started": "2026-03-15"
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _now() -> str:
    return datetime.now().isoformat()

def _today() -> str:
    return date.today().isoformat()

def _short_id() -> str:
    return str(uuid.uuid4())[:8]

def _load_json(path: Path) -> Any:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def _save_json(path: Path, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _append_jsonl(path: Path, entry: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except:
                    pass
    return entries


# ─────────────────────────────────────────────
# MAIN LOGGER CLASS
# ─────────────────────────────────────────────

class HayeongLogger:
    """
    Hayeong's comprehensive logging system.
    Create one instance at startup and share it across all modules.
    """

    def __init__(self):
        self.session_id    = _short_id()
        self.session_start = _now()
        self.session_file  = SESSIONS_DIR / f"session_{_today()}_{self.session_id}.jsonl"
        self.event_file    = EVENTS_DIR   / f"events_{_today()}.jsonl"
        self.image_file    = IMAGES_DIR   / f"images_{_today()}.jsonl"
        self.caps_file     = CAPS_DIR     / f"capabilities_{_today()}.jsonl"
        self.growth_file   = GROWTH_DIR   / "milestones.jsonl"
        self.earnings_file = GOALS_DIR    / "earnings.jsonl"
        self.goal_file     = GOALS_DIR    / "workstation_goal.json"

        self._init_goal()
        self._log_session_start()
        print(f"[HayeongLogger] Session {self.session_id} started")


    # ─────────────────────────────────────────────
    # SESSION
    # ─────────────────────────────────────────────

    def _log_session_start(self):
        entry = {
            "type": "session_start",
            "session_id": self.session_id,
            "timestamp": self.session_start,
            "date": _today()
        }
        _append_jsonl(self.session_file, entry)
        _append_jsonl(self.event_file, entry)

    def end_session(self, summary: str = ""):
        entry = {
            "type": "session_end",
            "session_id": self.session_id,
            "timestamp": _now(),
            "started": self.session_start,
            "summary": summary
        }
        _append_jsonl(self.session_file, entry)
        _append_jsonl(self.event_file, entry)
        print(f"[HayeongLogger] Session {self.session_id} ended")


    # ─────────────────────────────────────────────
    # CONVERSATION
    # ─────────────────────────────────────────────

    def log_conversation(self, role: str, content: str,
                         intent: str = None, mood: str = None,
                         model_used: str = None):
        """Log a single conversation turn. role: 'james' or 'hayeong'"""
        entry = {
            "type": "conversation",
            "session_id": self.session_id,
            "timestamp": _now(),
            "role": role,
            "content": content,
            "intent": intent,
            "mood": mood,
            "model_used": model_used
        }
        _append_jsonl(self.session_file, entry)
        _append_jsonl(self.event_file, entry)


    # ─────────────────────────────────────────────
    # IMAGE GENERATION
    # ─────────────────────────────────────────────

    def log_image_generation(self, prompt: str, output_path: str = None,
                              model: str = None, workflow_type: str = "txt2img",
                              outcome: str = "success", feedback: str = None,
                              generation_time: float = None,
                              settings: dict = None) -> str:
        """
        Log an image generation attempt.
        workflow_type: 'txt2img', 'img2img', 'realistic_conversion', 'ipadapter'
        outcome: 'success', 'failed', 'rejected_by_user'
        Returns the image log ID for later feedback.
        """
        entry = {
            "type": "image_generation",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "workflow_type": workflow_type,
            "model": model,
            "prompt": prompt,
            "output_path": output_path,
            "outcome": outcome,
            "feedback": feedback,
            "generation_time_seconds": generation_time,
            "settings": settings or {}
        }
        _append_jsonl(self.image_file, entry)
        _append_jsonl(self.event_file, entry)
        return entry["id"]

    def add_image_feedback(self, image_id: str, feedback: str, rating: str = None):
        """
        Add feedback to a previously logged image.
        rating: 'good', 'bad', 'close', 'perfect'
        """
        entry = {
            "type": "image_feedback",
            "image_id": image_id,
            "session_id": self.session_id,
            "timestamp": _now(),
            "feedback": feedback,
            "rating": rating
        }
        _append_jsonl(self.image_file, entry)
        _append_jsonl(self.event_file, entry)


    # ─────────────────────────────────────────────
    # CAPABILITY USAGE
    # ─────────────────────────────────────────────

    def log_capability_used(self, capability: str, action: str = None,
                             outcome: str = "success", details: dict = None,
                             error: str = None):
        """Log when Hayeong uses a capability."""
        entry = {
            "type": "capability_used",
            "session_id": self.session_id,
            "timestamp": _now(),
            "capability": capability,
            "action": action,
            "outcome": outcome,
            "details": details or {},
            "error": error
        }
        _append_jsonl(self.caps_file, entry)
        _append_jsonl(self.event_file, entry)


    # ─────────────────────────────────────────────
    # GOAL & EARNINGS
    # ─────────────────────────────────────────────

    def _init_goal(self):
        if not self.goal_file.exists():
            _save_json(self.goal_file, {
                **WORKSTATION_GOAL,
                "total_earned": 0.0,
                "transactions": []
            })

    def log_earning(self, amount: float, source: str,
                    description: str = "", platform: str = None,
                    gross: float = None, fees: float = None) -> dict:
        """
        Log an earning toward the workstation goal.
        amount: net amount received
        source: e.g. 'Etsy', 'Fiverr', 'Commission'
        """
        entry = {
            "type": "earning",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "date": _today(),
            "amount": amount,
            "gross": gross or amount,
            "fees": fees or 0.0,
            "source": source,
            "platform": platform,
            "description": description
        }
        _append_jsonl(self.earnings_file, entry)
        _append_jsonl(self.event_file, entry)

        # Update running total
        goal = _load_json(self.goal_file) or {}
        goal["total_earned"] = round(goal.get("total_earned", 0.0) + amount, 2)
        goal.setdefault("transactions", []).append(entry)
        _save_json(self.goal_file, goal)

        # Auto milestone at percentage thresholds
        total  = goal["total_earned"]
        target = goal.get("target_amount", 3000.0)
        pct    = (total / target) * 100
        for m in [10, 25, 50, 75, 90, 100]:
            if (total - amount) / target * 100 < m <= pct:
                self.log_milestone(
                    f"Reached {m}% of workstation goal! (${total:.2f} / ${target:.2f})",
                    category="goal"
                )

        print(f"[HayeongLogger] 💰 Earned ${amount:.2f} from {source} | Total: ${total:.2f} / ${target:.2f} ({pct:.1f}%)")
        return entry

    def log_expense(self, amount: float, description: str, category: str = "tools"):
        """Log a business expense."""
        entry = {
            "type": "expense",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "date": _today(),
            "amount": amount,
            "description": description,
            "category": category
        }
        _append_jsonl(self.earnings_file, entry)
        _append_jsonl(self.event_file, entry)


    # ─────────────────────────────────────────────
    # GROWTH & MILESTONES
    # ─────────────────────────────────────────────

    def log_milestone(self, description: str, category: str = "general",
                      details: dict = None):
        """
        Log a meaningful milestone.
        category: 'goal', 'capability', 'creative', 'relationship', 'technical', 'general'
        """
        entry = {
            "type": "milestone",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "date": _today(),
            "category": category,
            "description": description,
            "details": details or {}
        }
        _append_jsonl(self.growth_file, entry)
        _append_jsonl(self.event_file, entry)
        print(f"[HayeongLogger] ⭐ Milestone: {description}")

    def log_learning(self, what_learned: str, source: str = None, applied_to: str = None):
        """Log something Hayeong learned or improved at."""
        entry = {
            "type": "learning",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "what_learned": what_learned,
            "source": source,
            "applied_to": applied_to
        }
        _append_jsonl(self.growth_file, entry)
        _append_jsonl(self.event_file, entry)

    def log_decision(self, situation: str, decision: str,
                     reasoning: str = None, outcome: str = None,
                     james_approved: bool = None):
        """Log a decision Hayeong made — especially important for autonomous actions."""
        entry = {
            "type": "decision",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "situation": situation,
            "decision": decision,
            "reasoning": reasoning,
            "outcome": outcome,
            "james_approved": james_approved
        }
        _append_jsonl(self.event_file, entry)
        _append_jsonl(self.growth_file, entry)

    def log_proposal(self, title: str, description: str,
                     category: str = "business", status: str = "pending",
                     james_response: str = None) -> str:
        """
        Log a proposal Hayeong makes to James.
        status: 'pending', 'approved', 'rejected', 'modified'
        Returns proposal ID.
        """
        entry = {
            "type": "proposal",
            "id": _short_id(),
            "session_id": self.session_id,
            "timestamp": _now(),
            "title": title,
            "description": description,
            "category": category,
            "status": status,
            "james_response": james_response
        }
        _append_jsonl(self.event_file, entry)
        _append_jsonl(self.growth_file, entry)
        return entry["id"]


    # ─────────────────────────────────────────────
    # QUERIES & SUMMARIES
    # ─────────────────────────────────────────────

    def goal_status(self) -> dict:
        """Get current workstation goal progress."""
        goal    = _load_json(self.goal_file) or {}
        total   = goal.get("total_earned", 0.0)
        target  = goal.get("target_amount", 3000.0)
        remaining = max(0, target - total)
        pct     = min(100, (total / target) * 100)
        recent  = [e for e in _read_jsonl(self.earnings_file)
                   if e.get("type") == "earning"][-5:]
        return {
            "goal_name":       goal.get("name", "Workstation PC"),
            "target":          target,
            "earned":          round(total, 2),
            "remaining":       round(remaining, 2),
            "percent":         round(pct, 1),
            "recent_earnings": recent,
            "on_track":        pct > 0
        }

    def daily_summary(self, target_date: str = None) -> dict:
        """Generate a summary of a specific day (defaults to today)."""
        day        = target_date or _today()
        events     = _read_jsonl(EVENTS_DIR / f"events_{day}.jsonl")
        convs      = [e for e in events if e.get("type") == "conversation"]
        images     = [e for e in events if e.get("type") == "image_generation"]
        earnings   = [e for e in events if e.get("type") == "earning"]
        milestones = [e for e in events if e.get("type") == "milestone"]
        caps       = [e for e in events if e.get("type") == "capability_used"]
        decisions  = [e for e in events if e.get("type") == "decision"]

        return {
            "date":                 day,
            "conversation_turns":   len(convs),
            "james_messages":       len([c for c in convs if c.get("role") == "james"]),
            "hayeong_messages":     len([c for c in convs if c.get("role") == "hayeong"]),
            "images_generated":     len(images),
            "images_successful":    len([i for i in images if i.get("outcome") == "success"]),
            "capabilities_used":    list(set(c.get("capability") for c in caps if c.get("capability"))),
            "earnings_today":       round(sum(e.get("amount", 0) for e in earnings), 2),
            "milestones":           [m.get("description") for m in milestones],
            "decisions_made":       len(decisions),
            "total_events":         len(events)
        }

    def weekly_summary(self) -> dict:
        """Generate a summary of the past 7 days."""
        today  = date.today()
        days   = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        daily  = [self.daily_summary(d) for d in days]
        milestones = [m for d in daily for m in d["milestones"]]

        return {
            "week_start":              days[0],
            "week_end":                days[-1],
            "total_conversation_turns": sum(d["conversation_turns"] for d in daily),
            "total_images_generated":  sum(d["images_generated"] for d in daily),
            "total_earned":            round(sum(d["earnings_today"] for d in daily), 2),
            "milestones_this_week":    milestones,
            "most_active_day":         max(daily, key=lambda d: d["total_events"])["date"],
            "daily_breakdown":         daily,
            "goal_status":             self.goal_status()
        }

    def image_history(self, limit: int = 20, outcome_filter: str = None) -> List[dict]:
        """Get recent image generation history."""
        entries = []
        for f in reversed(sorted(IMAGES_DIR.glob("images_*.jsonl"))):
            entries.extend(_read_jsonl(f))
            if len(entries) >= limit * 2:
                break
        images = [e for e in entries if e.get("type") == "image_generation"]
        if outcome_filter:
            images = [i for i in images if i.get("outcome") == outcome_filter]
        return images[-limit:]

    def get_milestones(self, category: str = None) -> List[dict]:
        """Get all milestones, optionally filtered by category."""
        all_m = [e for e in _read_jsonl(self.growth_file) if e.get("type") == "milestone"]
        if category:
            all_m = [m for m in all_m if m.get("category") == category]
        return all_m

    def get_proposals(self, status: str = None) -> List[dict]:
        """Get all proposals Hayeong has made to James."""
        all_events = []
        for f in sorted(EVENTS_DIR.glob("events_*.jsonl")):
            all_events.extend(_read_jsonl(f))
        proposals = [e for e in all_events if e.get("type") == "proposal"]
        if status:
            proposals = [p for p in proposals if p.get("status") == status]
        return proposals

    def search_conversations(self, keyword: str, limit: int = 10) -> List[dict]:
        """Search conversation history for a keyword."""
        results = []
        for f in sorted(SESSIONS_DIR.glob("session_*.jsonl"), reverse=True):
            for e in _read_jsonl(f):
                if e.get("type") == "conversation":
                    if keyword.lower() in e.get("content", "").lower():
                        results.append(e)
                        if len(results) >= limit:
                            return results
        return results


    # ─────────────────────────────────────────────
    # REFLECTION DATA
    # Returns structured data for Hayeong to reflect on
    # through her normal conversation system — NO Ollama calls here.
    # Feed the result into her memory/context so she can respond naturally.
    # ─────────────────────────────────────────────

    def get_reflection_data(self, period: str = "today") -> dict:
        """
        Returns structured log data for Hayeong to reflect on.
        This is pure data — no LLM calls. Pass the result into Hayeong's
        normal conversation flow so she can reflect in her own voice.

        Usage in main.py (on shutdown or on request):
            reflection_data = logger.get_reflection_data()
            memory.append({"role": "user", "content":
                f"Before you go, here's a summary of today: {json.dumps(reflection_data)}. "
                "How do you feel about it?"})
            # Then let normal LLM flow handle the response
        """
        data       = self.daily_summary() if period == "today" else self.weekly_summary()
        goal       = self.goal_status()
        milestones = self.get_milestones()[-5:]
        return {
            "period":           period,
            "activity_summary": data,
            "goal_status":      goal,
            "recent_milestones": [m.get("description") for m in milestones]
        }

    def generate_summary_report(self, period: str = "week") -> str:
        """
        Generate a formatted progress report for James.
        Saved automatically to logs/summaries/
        Note: The reflection section is left as a placeholder — pass the report
        to Hayeong's conversation system if you want her to add her own thoughts.
        """
        data       = self.weekly_summary() if period == "week" else self.daily_summary()
        goal       = self.goal_status()

        bar_filled = int(goal["percent"] / 5)
        bar        = ("█" * bar_filled).ljust(20)

        date_label = data.get("week_end") or data.get("date", _today())
        earned     = data.get("earnings_today") or data.get("total_earned", 0)
        images     = data.get("images_generated") or data.get("total_images_generated", 0)
        convs      = data.get("conversation_turns") or data.get("total_conversation_turns", 0)
        milestones = data.get("milestones") or data.get("milestones_this_week", [])

        report = f"""
╔══════════════════════════════════════════════════════════════╗
║         HAYEONG PROGRESS REPORT — {date_label}
╚══════════════════════════════════════════════════════════════╝

📊 ACTIVITY
  Conversation turns : {convs}
  Images generated   : {images}

💰 WORKSTATION FUND
  Earned this period : ${earned:.2f}
  Total saved        : ${goal['earned']:.2f} / ${goal['target']:.2f}
  Progress           : {goal['percent']:.1f}%
  Remaining          : ${goal['remaining']:.2f}
  [{bar}] {goal['percent']:.0f}%

⭐ MILESTONES
"""
        if milestones:
            for m in milestones:
                report += f"  • {m}\n"
        else:
            report += "  • No new milestones this period\n"

        report += """
💭 HAYEONG'S REFLECTION
  (Feed get_reflection_data() into Hayeong's conversation so she can reflect naturally.)

══════════════════════════════════════════════════════════════
"""
        report_file = SUMMARIES_DIR / f"report_{period}_{_today()}.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"[HayeongLogger] Report saved to {report_file}")
        return report


# ─────────────────────────────────────────────
# MAIN.PY INTEGRATION SNIPPET
# ─────────────────────────────────────────────

MAIN_PY_SNIPPET = '''
# ── Add near top of main.py imports ──
from hayeong_logger import HayeongLogger
logger = HayeongLogger()

# ── In your main conversation loop, log every turn ──
logger.log_conversation(
    role="james",
    content=user_input,
    intent=intent.get("intent") if intent else None
)

logger.log_conversation(
    role="hayeong",
    content=response_text,
    mood=current_mood,
    model_used=PRIMARY_MODEL
)

# ── Log capability usage ──
logger.log_capability_used("email", action="check_inbox", outcome="success")
logger.log_capability_used("comfyui", action="txt2img", outcome="success")

# ── Log image generation (in comfyui_bridge.py) ──
img_id = logger.log_image_generation(
    prompt=prompt_data["positive"],
    output_path=image_path,
    model=DEFAULT_CHECKPOINT,
    workflow_type="txt2img",
    outcome="success",
    generation_time=elapsed
)

# ── Add feedback after James sees the image ──
logger.add_image_feedback(img_id, "Hood was up again", rating="close")

# ── Log earnings when they come in ──
logger.log_earning(45.00, source="Etsy", description="VTuber emote pack")

# ── On shutdown ──
reflection_data = logger.get_reflection_data()
memory.append({"role": "user", "content":
    f"Before you go, here's a summary of today: {json.dumps(reflection_data)}. How do you feel about it?"})
# Then let normal LLM flow handle the response — Hayeong reflects in her own voice
logger.end_session()

# ── Trigger report (Hayeong can say this herself) ──
# "how are we doing on the goal" / "give me a weekly report"
report = logger.generate_summary_report("week")
speak(report)
'''


# ─────────────────────────────────────────────
# CAPABILITY REGISTRY ENTRY
# Add this to capability_registry.json
# ─────────────────────────────────────────────

CAPABILITY_ENTRY = {
    "id": "comprehensive_logging",
    "name": "Comprehensive Logging System",
    "description": (
        "Full activity logging covering conversations, image generations, "
        "earnings, decisions, milestones, and goal tracking toward the "
        "workstation fund. Hayeong can reflect on her own logs and generate "
        "progress reports. Say: 'show progress report', 'how close are we to the goal', "
        "'what have you been working on'."
    ),
    "status": "active",
    "approved_by": "james",
    "script": "hayeong_logger.py",
    "log_locations": {
        "sessions":     "logs/sessions/",
        "events":       "logs/events/",
        "images":       "logs/images/",
        "capabilities": "logs/capabilities/",
        "growth":       "logs/growth/",
        "goals":        "logs/goals/",
        "summaries":    "logs/summaries/"
    }
}


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("HayeongLogger — Standalone Test")
    print("=" * 60)

    logger = HayeongLogger()

    logger.log_conversation("james", "Hey Hayeong, how are you doing?")
    logger.log_conversation("hayeong", "Doing well! Ready to work on some images.", mood="cheerful")

    img_id = logger.log_image_generation(
        prompt="score_9, anime girl, orange frog jacket, blue hair",
        output_path="H:/ComfyUI/output/Hayeong_00001.png",
        model="ponyDiffusionV6XL",
        outcome="success",
        generation_time=8.5
    )
    logger.add_image_feedback(img_id, "Hood was up again but face looks great!", rating="close")

    logger.log_capability_used("comfyui", action="txt2img", outcome="success")
    logger.log_milestone("First successful Hayeong character image generated!", category="creative")
    logger.log_earning(25.00, source="Etsy", description="VTuber emote pack", gross=27.50, fees=2.50)

    goal = logger.goal_status()
    print(f"\n💰 Goal: ${goal['earned']} / ${goal['target']} ({goal['percent']}%) — ${goal['remaining']} remaining")

    summary = logger.daily_summary()
    print(f"\n📊 Today: {summary['conversation_turns']} turns, {summary['images_generated']} images, ${summary['earnings_today']} earned")

    print("\n📄 Generating report...")
    report = logger.generate_summary_report("today")
    print(report)

    print("\n🪞 Reflection data (for feeding into Hayeong's conversation):")
    reflection_data = logger.get_reflection_data()
    print(json.dumps(reflection_data, indent=2))

    logger.end_session("Test session complete.")
    print("✅ All tests passed!")
