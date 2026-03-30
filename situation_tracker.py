"""
situation_tracker.py
────────────────────
Hayeong's situational awareness layer.

PURPOSE
───────
Every LLM call in the main loop (decide_action, context_verifier,
stream_response) was independently figuring out context from a
different slice of history. This meant each call had a slightly
different picture of what was happening — causing misfires,
false triggers, and missed constraints.

This module computes ONE situation snapshot at the start of each
turn. That snapshot is shared by every downstream call so they all
work from the same agreed-upon understanding.

WHAT A SNAPSHOT IS
──────────────────
A small structured summary of right now:
  - What topic/task are we on?
  - What phase is this conversation in?
  - What just got completed?
  - What is James's current intent and tone?
  - Are there active constraints or requirements?
  - Did we just switch tasks?

SNAPSHOT BACKLOG
────────────────
The last N snapshots are kept in a rolling buffer.
When James switches topics or tasks, Hayeong can look back
and see the trajectory — not just the current moment.

This is different from ChromaDB (long-term memory):
  ChromaDB  → stores WHAT was said (content)
  Backlog   → stores WHAT WAS HAPPENING situationally (context)
These are complementary layers, not redundant ones.

The backlog lives in session only (not persisted across restarts)
unless session_context.json exists from the current session.
Long-term situational history lives in ChromaDB as normal.

USAGE (in main.py)
──────────────────
  tracker = SituationTracker()

  # Start of each turn:
  snapshot = tracker.build_snapshot(user_input, memory)

  # Pass to decide_action, context_verifier, system_prompt builder
  decision = decide_action(user_input, memory, snapshot=snapshot)
  ...
  system_prompt = snapshot.format_for_prompt() + system_prompt
"""

import json
import re
import requests
from collections import deque
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

OLLAMA_URL       = "http://localhost:11434/api/chat"
SNAPSHOT_MODEL   = "qwen2.5:14b"   # Same model as decide_action — already loaded
BACKLOG_SIZE     = 10              # Rolling window of snapshots kept in memory
SESSION_FILE     = Path(__file__).parent / "session_context.json"

# Conversation phases — helps Hayeong know where she is in a task
PHASES = [
    "opening",      # Start of session or new topic
    "exploring",    # James is asking questions, gathering info
    "mid_task",     # Active work underway (search, write, etc.)
    "reviewing",    # James is looking at results Hayeong produced
    "wrapping_up",  # Task is done, James is closing out
    "casual",       # No task — just talking
    "switching",    # Topic/task just changed
]

# ─────────────────────────────────────────────
# SNAPSHOT PROMPT
# ─────────────────────────────────────────────

SNAPSHOT_PROMPT = """You are Hayeong's situational awareness engine.

Your job is to read the recent conversation and produce a concise structured
summary of the CURRENT situation — not a summary of the whole conversation.
Focus on RIGHT NOW: this message, this moment, this task.

Return ONLY valid JSON. No explanation, no markdown, no extra text.

JSON fields:
  current_topic      — string: what is being discussed or worked on right now
                       (be specific: "non-legendary Pokémon for Once Human" not "gaming")
  phase              — one of: opening, exploring, mid_task, reviewing, wrapping_up, casual, switching
  just_completed     — string or null: what task/action was just finished in the last 1-2 turns
  james_intent       — string: what James seems to want from THIS message
  james_tone         — one of: casual, collaborative, testing, reviewing, urgent, satisfied, frustrated
  active_constraints — list of strings: explicit requirements James has stated that are still in play
                       (only what he SAID — do not invent constraints)
  open_task          — bool: is there an ongoing task that isn't finished yet?
  task_switching     — bool: is James switching to a new topic or task right now?

Phase guide:
  opening     = first message, or starting a clearly new unrelated topic
  exploring   = asking questions, figuring things out, no specific task yet
  mid_task    = active work is happening (research, writing, building something)
  reviewing   = James is reading/evaluating something Hayeong just produced
  wrapping_up = task done, James is acknowledging or closing out ("thanks", "that's good")
  casual      = no task, just conversation
  switching   = James is moving from one task/topic to a different one

IMPORTANT:
- "wrapping_up" means NO new tool should fire. The work is done.
- "switching" means the previous task's constraints are no longer active.
- active_constraints carries forward until the task is wrapping_up or switching.
- When in doubt on phase, lean toward "casual" over "mid_task".
"""


# ─────────────────────────────────────────────
# SITUATION TRACKER
# ─────────────────────────────────────────────

class SituationTracker:
    """
    Computes and maintains situational awareness across a session.

    One instance lives for the duration of main(). Build a snapshot
    at the top of each turn, then pass it downstream to all callers.
    """

    def __init__(self):
        self._backlog: deque = deque(maxlen=BACKLOG_SIZE)
        self._current: dict  = {}
        self._load_session()

    # ─────────────────────────────────────────────
    # BUILD SNAPSHOT
    # ─────────────────────────────────────────────

    def build_snapshot(self, user_input: str, memory: list,
                       model: str = None) -> dict:
        """
        Compute the situation snapshot for this turn.
        Runs once per turn, before decide_action.

        Returns the snapshot dict. Also stores it in the backlog.
        Falls back to a minimal "casual" snapshot if the LLM call fails —
        we never block the turn just because the tracker errored.
        """
        _model = model or SNAPSHOT_MODEL

        # ── Build context block from recent memory ──
        history_lines = []
        for m in memory[-8:]:
            role    = "James"   if m["role"] == "user" else "Hayeong"
            content = m.get("content", "")[:300]
            history_lines.append(f"{role}: {content}")
        history_block = "\n".join(history_lines)

        # ── Include recent backlog so model can detect task-switching ──
        backlog_block = ""
        if self._backlog:
            recent = list(self._backlog)[-3:]   # last 3 snapshots
            backlog_lines = []
            for snap in recent:
                ts    = snap.get("timestamp", "")
                topic = snap.get("current_topic", "?")
                phase = snap.get("phase", "?")
                backlog_lines.append(f"  [{ts}] topic={topic!r} phase={phase}")
            backlog_block = (
                "\nRecent situation history (most recent last):\n"
                + "\n".join(backlog_lines)
                + "\n"
            )

        user_content = (
            f"Recent conversation:\n{history_block}\n"
            f"{backlog_block}"
            f"\nLatest message from James: {user_input}\n\n"
            f"What is the current situation?"
        )

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":   _model,
                    "messages": [
                        {"role": "system", "content": SNAPSHOT_PROMPT},
                        {"role": "user",   "content": user_content},
                    ],
                    "stream":  False,
                    "format":  "json",
                    "options": {"temperature": 0.0},
                },
                timeout=15,
            )
            raw = resp.json()["message"]["content"].strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$",       "", raw)
            snapshot = json.loads(raw.strip())

            # Validate and fill defaults for any missing fields
            snapshot = self._normalize(snapshot)
            snapshot["timestamp"] = datetime.now().strftime("%H:%M:%S")

            self._current = snapshot
            self._backlog.append(snapshot)
            self._save_session()

            # Terminal output — compact, informative
            phase       = snapshot.get("phase", "?")
            topic       = snapshot.get("current_topic", "?")[:50]
            switching   = " → switching" if snapshot.get("task_switching") else ""
            constraints = snapshot.get("active_constraints", [])
            c_note      = f" [{len(constraints)} constraint(s)]" if constraints else ""
            print(f"   [Situation] {phase}{switching} — {topic}{c_note}")

            return snapshot

        except Exception as e:
            print(f"   [Situation] snapshot failed ({e}) — using minimal fallback")
            fallback = self._fallback_snapshot(user_input)
            self._current = fallback
            self._backlog.append(fallback)
            return fallback

    # ─────────────────────────────────────────────
    # FORMAT FOR INJECTION
    # ─────────────────────────────────────────────

    def format_for_prompt(self, include_backlog: bool = False) -> str:
        """
        Format the current snapshot (and optionally recent backlog)
        as a context block to prepend to system prompts.

        Usage in main.py:
            system_prompt = tracker.format_for_prompt() + "\\n\\n" + system_prompt
        """
        if not self._current:
            return ""

        s = self._current
        lines = ["[CURRENT SITUATION]"]

        lines.append(f"Topic: {s.get('current_topic', 'unknown')}")
        lines.append(f"Phase: {s.get('phase', 'casual')}")

        if s.get("just_completed"):
            lines.append(f"Just completed: {s['just_completed']}")

        lines.append(f"James's intent: {s.get('james_intent', 'unknown')}")
        lines.append(f"Tone: {s.get('james_tone', 'casual')}")

        constraints = s.get("active_constraints", [])
        if constraints:
            lines.append(f"Active constraints: {', '.join(constraints)}")

        if s.get("task_switching"):
            lines.append("NOTE: James just switched tasks — previous task context is closed.")

        if s.get("open_task"):
            lines.append("NOTE: There is an open ongoing task.")

        if include_backlog and len(self._backlog) > 1:
            lines.append("")
            lines.append("[RECENT SESSION TRAJECTORY]")
            for snap in list(self._backlog)[:-1]:  # all but current
                ts    = snap.get("timestamp", "")
                topic = snap.get("current_topic", "?")
                phase = snap.get("phase", "?")
                lines.append(f"  [{ts}] {phase} — {topic}")

        return "\n".join(lines)

    def format_for_decision(self) -> str:
        """
        Compact version for inject into decide_action and context_verifier.
        These calls are already doing work — keep the snapshot injection brief.
        """
        if not self._current:
            return ""

        s = self._current
        parts = [
            f"[SITUATION: phase={s.get('phase','?')}",
            f"topic={s.get('current_topic','?')!r}",
        ]
        if s.get("task_switching"):
            parts.append("SWITCHING=true")
        if s.get("just_completed"):
            parts.append(f"just_completed={s['just_completed']!r}")
        constraints = s.get("active_constraints", [])
        if constraints:
            parts.append(f"constraints={constraints}")
        parts.append("]")
        return " ".join(parts)

    # ─────────────────────────────────────────────
    # ACCESSORS
    # ─────────────────────────────────────────────

    @property
    def current(self) -> dict:
        """The most recent snapshot."""
        return self._current.copy()

    @property
    def phase(self) -> str:
        return self._current.get("phase", "casual")

    @property
    def constraints(self) -> list:
        return self._current.get("active_constraints", [])

    @property
    def is_wrapping_up(self) -> bool:
        return self._current.get("phase") == "wrapping_up"

    @property
    def is_switching(self) -> bool:
        return self._current.get("task_switching", False)

    @property
    def backlog(self) -> list:
        return list(self._backlog)

    # ─────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────

    def _normalize(self, raw: dict) -> dict:
        """Fill defaults for any fields the LLM may have omitted."""
        valid_phases = set(PHASES)
        valid_tones  = {"casual", "collaborative", "testing", "reviewing",
                        "urgent", "satisfied", "frustrated"}

        phase = raw.get("phase", "casual")
        if phase not in valid_phases:
            phase = "casual"

        tone = raw.get("james_tone", "casual")
        if tone not in valid_tones:
            tone = "casual"

        return {
            "current_topic":      str(raw.get("current_topic", "general conversation")),
            "phase":              phase,
            "just_completed":     raw.get("just_completed") or None,
            "james_intent":       str(raw.get("james_intent", "unknown")),
            "james_tone":         tone,
            "active_constraints": [str(c) for c in raw.get("active_constraints", [])],
            "open_task":          bool(raw.get("open_task", False)),
            "task_switching":     bool(raw.get("task_switching", False)),
            "timestamp":          "",   # filled by caller
        }

    def _fallback_snapshot(self, user_input: str) -> dict:
        """Minimal safe snapshot used when the LLM call fails."""
        return {
            "current_topic":      user_input[:60],
            "phase":              "casual",
            "just_completed":     None,
            "james_intent":       "unknown",
            "james_tone":         "casual",
            "active_constraints": [],
            "open_task":          False,
            "task_switching":     False,
            "timestamp":          datetime.now().strftime("%H:%M:%S"),
        }

    def _save_session(self):
        """
        Persist the current session's backlog to disk.
        Survives Hayeong restarts mid-session (rare but possible).
        Written compactly — small file, fast I/O.
        """
        try:
            data = {
                "saved_at": datetime.now().isoformat(),
                "backlog":  list(self._backlog),
            }
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass   # Non-critical — never crash the turn over a log write

    def _load_session(self):
        """
        Load the previous session's backlog on startup.
        Only loads if the file is from today — stale sessions are ignored.
        """
        if not SESSION_FILE.exists():
            return
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_at = data.get("saved_at", "")
            today    = datetime.now().strftime("%Y-%m-%d")
            if not saved_at.startswith(today):
                return   # Different day — don't carry over
            for snap in data.get("backlog", []):
                self._backlog.append(snap)
            if self._backlog:
                print(f"   [SituationTracker] Resumed session — {len(self._backlog)} snapshot(s) loaded.")
        except Exception:
            pass
