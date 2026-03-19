"""
intent_detector.py
──────────────────
Fast keyword-based intent classifier — zero LLM overhead.

The previous version made a qwen2.5:7b API call before EVERY message,
adding 2-5 seconds of latency and sometimes getting it wrong.

This version uses instant keyword/pattern matching instead.
Hayeong's actual responses still use qwen2.5:14b — this just routes.

HOW IT WORKS
────────────
1. Every user message passes through detect() first.
2. Keywords and patterns classify the message in milliseconds.
3. main.py reads the result and routes accordingly.

INTENTS RETURNED
────────────────
  "conversation"     → normal chat, goes straight to qwen14b
  "email"            → any email action (check, send, notify)
  "task"             → task list actions (show, add, complete)
  "capability"       → start/stop a subprocess (discord, minecraft, etc.)
  "self_mod"         → proposals, weekly summary, approve/deny
  "status"           → what's running, system state
  "memory"           → explicit recall ("do you remember...")
  "code"             → coding help, debugging
  "web_search"       → look something up online
  "vision"           → look at screen or analyze an image
  "image_generation" → generate/draw/create an image

Each result also includes:
  action     → sub-action when relevant (e.g. "check_inbox", "add", "start")
  target     → what the action applies to (e.g. "discord", "minecraft")
  confidence → "high" | "medium" | "low"
  fallback   → always False now (keyword IS the method, not a fallback)

USAGE IN main.py  (unchanged from before)
────────────────
  from intent_detector import IntentDetector
  detector = IntentDetector()

  intent = detector.detect(user_input)

  if intent["intent"] == "email":
      # handle email
  elif intent["intent"] == "task":
      # handle task
  elif intent["intent"] == "capability":
      action = intent["action"]   # "start" or "stop"
      target = intent["target"]   # "discord", "minecraft", etc.
  ...
  else:  # "conversation"
      # send to qwen14b as normal
"""

import json
import re
from pathlib import Path

BASE_DIR       = Path(__file__).parent
CAPABILITY_REG = BASE_DIR / "capability_registry.json"

# ─────────────────────────────────────────────
# KEYWORD DEFINITIONS
# Each intent has keywords checked against lowercased input.
# Priority order matters — checked top to bottom.
# ─────────────────────────────────────────────

INTENT_DEFINITIONS = {
    "email": {
        "keywords": [
            "email", "inbox", "notify", "notification",
            "ping me", "send me a message", "send me a note",
            "anything come in", "did i get", "got any mail",
            "check mail", "check email", "send email",
            "send me a summary", "email summary", "new messages",
            "daily summary",
        ],
    },
    "task": {
        "keywords": [
            "task list", "task", "todo", "to-do", "backlog",
            "add a task", "show tasks", "my tasks",
            "mark done", "mark as done", "mark complete",
            "what are you working on", "what have you done",
            "what's on my list", "completed tasks", "blocked tasks",
        ],
    },
    "capability": {
        "keywords": [
            "open discord", "start discord", "close discord", "stop discord",
            "start minecraft", "load minecraft", "open minecraft", "close minecraft",
            "turn on your mic", "open your mic", "enable mic", "voice mode",
            "start screen observer", "stop screen observer",
            "turn on observer", "turn off observer",
        ],
    },
    "self_mod": {
        "keywords": [
            "proposal", "proposals", "pending proposals",
            "weekly summary", "what did you change",
            "what have you changed", "approve that", "deny that",
            "approve the", "deny the",
        ],
    },
    "status": {
        "keywords": [
            "what's running", "system status", "what are you running",
            "are you on discord", "status check",
        ],
    },
    "memory": {
        "keywords": [
            "do you remember", "don't we", "didn't we",
            "we talked about", "last time", "from our last",
            "from our previous", "what did i say about",
            "what did we say", "recall", "you said before",
        ],
    },
    "code": {
        "keywords": [
            "write a python", "write a script", "write a function",
            "write a class", "write javascript", "write bash",
            "debug this", "debug the", "fix this code", "fix this error",
            "fix this bug", "refactor", "optimize this code",
            "review this code", "syntaxerror", "traceback",
            "attributeerror", "typeerror", "indexerror",
            "how do i implement", "can you code", "can you program",
        ],
    },
    "web_search": {
        "keywords": [
            "search for", "look up", "look it up", "google",
            "find out about", "what's the latest", "latest news",
            "news about", "current price", "how much does",
            "check online", "check the web", "search the web",
            "find information on", "who is the current",
            "what is the price of",
        ],
    },
    "vision": {
        "keywords": [
            "what's on my screen", "look at my screen", "look at the screen",
            "can you see my screen", "see my screen", "take a look at my screen",
            "what am i looking at", "describe what you see",
            "what is this image", "what does this image show",
            "look at this image", "analyze this image",
            "analyze this screenshot", "read this image",
            "glance at", "check my screen",
        ],
    },
    "image_generation": {
        "keywords": [
            "generate an image", "generate a picture", "generate art",
            "draw me", "draw a", "paint me", "paint a",
            "create an image", "create a picture", "make an image",
            "make a picture", "make art", "create art",
            "illustrate", "visualize this",
            "show me what", "what would it look like",
            "make it realistic", "make it real", "turn this into a photo",
            "from this image", "use my screen to generate",
        ],
    },
    # conversation is the default — no keywords needed
    "conversation": {
        "keywords": [],
    },
}

# ─────────────────────────────────────────────
# SUB-ACTION KEYWORDS
# Used after intent is classified to fill action/target fields.
# ─────────────────────────────────────────────

EMAIL_ACTION_KEYWORDS = {
    "send_summary": ["summary", "daily summary", "send me a summary", "email me a summary"],
    "check_inbox":  ["check", "inbox", "any emails", "new emails", "anything come in",
                     "did i get", "got any", "messages", "new messages"],
    "notify":       ["email me", "send me a message", "notify me", "send me a note",
                     "ping me", "message me"],
}

TASK_ACTION_KEYWORDS = {
    "show":           ["show tasks", "task list", "what's on", "backlog",
                       "what are you working on", "show me tasks", "my tasks"],
    "show_completed": ["what have you done", "completed", "show history", "show completed"],
    "show_blocked":   ["what's blocked", "blocked tasks", "show blocked"],
    "add":            ["add a task", "add task", "remember to", "i need to", "put on the list"],
    "complete":       ["mark done", "mark as done", "complete", "finished", "done with"],
}

CAPABILITY_ACTION_KEYWORDS = {
    "start": ["open", "start", "load", "launch", "enable", "turn on",
              "get on", "connect", "join", "go on"],
    "stop":  ["close", "stop", "leave", "disconnect", "disable",
              "turn off", "mute", "shut down"],
}

CAPABILITY_TARGETS = ["discord", "minecraft", "voice", "mic", "observer", "screen observer"]

# Priority order — checked top to bottom, first match wins.
# capability must come early to avoid "open discord" matching nothing
# vision/image_generation before conversation to avoid swallowing them
PRIORITY_ORDER = [
    "capability",
    "vision",
    "image_generation",
    "web_search",
    "email",
    "task",
    "self_mod",
    "status",
    "memory",
    "code",
    "conversation",
]


# ─────────────────────────────────────────────
# INTENT DETECTOR
# ─────────────────────────────────────────────

class IntentDetector:
    """
    Single entry point for all intent classification.
    Call detect(user_input) before routing any message.
    Instant — no LLM calls, no network requests.
    """

    def __init__(self, use_llm: bool = False):
        # use_llm param kept for backwards compatibility — ignored.
        # Keyword matching is fast enough and more reliable.
        self.capabilities = self._load_capabilities()

    def _load_capabilities(self) -> list:
        """Load active capability names from registry."""
        if not CAPABILITY_REG.exists():
            return []
        try:
            with open(CAPABILITY_REG, "r", encoding="utf-8") as f:
                reg = json.load(f)
            return [
                c["name"]
                for c in reg.get("built_in_capabilities", {}).get("capabilities", [])
                if c.get("status") == "active"
            ]
        except Exception:
            return []

    # ─────────────────────────────────────────────
    # MAIN ENTRY POINT
    # ─────────────────────────────────────────────

    def detect(self, text: str) -> dict:
        """
        Classify a user message into an intent instantly via keywords.

        Returns:
        {
            "intent":     str,   # e.g. "email", "task", "conversation"
            "action":     str,   # sub-action, e.g. "check_inbox", "start", "add"
            "target":     str,   # target of action, e.g. "discord", "minecraft"
            "confidence": str,   # "high" | "medium" | "low"
            "fallback":   bool,  # always False — keywords ARE the method
            "raw":        str,   # original user text
        }
        """
        result = {
            "intent":     "conversation",
            "action":     "",
            "target":     "",
            "confidence": "low",
            "fallback":   False,
            "raw":        text,
        }

        keyword_result = self._classify_with_keywords(text)
        result.update(keyword_result)
        self._fill_sub_action(text, result)
        return result

    # ─────────────────────────────────────────────
    # KEYWORD CLASSIFICATION
    # ─────────────────────────────────────────────

    def _classify_with_keywords(self, text: str) -> dict:
        """
        Instant keyword-based classification.
        Checks intents in PRIORITY_ORDER — first match wins.
        """
        t = text.lower().strip()

        for intent in PRIORITY_ORDER:
            keywords = INTENT_DEFINITIONS[intent]["keywords"]
            matched = [kw for kw in keywords if kw in t]
            if matched:
                # Confidence: high if 2+ keywords matched, medium if 1
                confidence = "high" if len(matched) >= 2 else "medium"
                return {
                    "intent":     intent,
                    "action":     "",
                    "target":     "",
                    "confidence": confidence,
                }

        # Default fallback — plain conversation
        return {
            "intent":     "conversation",
            "action":     "",
            "target":     "",
            "confidence": "low",
        }

    # ─────────────────────────────────────────────
    # SUB-ACTION RESOLUTION
    # ─────────────────────────────────────────────

    def _fill_sub_action(self, text: str, result: dict):
        """
        Fill in action and target based on the classified intent.
        """
        t      = text.lower().strip()
        intent = result["intent"]

        if intent == "email" and not result["action"]:
            for action, keywords in EMAIL_ACTION_KEYWORDS.items():
                if any(kw in t for kw in keywords):
                    result["action"] = action
                    break
            if not result["action"]:
                result["action"] = "notify"

        elif intent == "task" and not result["action"]:
            for action, keywords in TASK_ACTION_KEYWORDS.items():
                if any(kw in t for kw in keywords):
                    result["action"] = action
                    break
            if not result["action"]:
                result["action"] = "show"

        elif intent == "capability":
            if not result["action"]:
                for action, keywords in CAPABILITY_ACTION_KEYWORDS.items():
                    if any(kw in t for kw in keywords):
                        result["action"] = action
                        break

            if not result["target"]:
                for cap in CAPABILITY_TARGETS:
                    if cap in t:
                        result["target"] = "voice" if cap == "mic" else cap
                        break


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    detector = IntentDetector()

    test_messages = [
        # Email
        "did anything come in",
        "can you ping me about that later",
        "check if I got any new emails",
        "send me a daily summary",

        # Task
        "what's on my task list",
        "I need to remember to fix the voice bot",
        "mark that discord fix as done",

        # Capability
        "open discord",
        "start discord",
        "let's load minecraft",
        "turn on your mic",
        "close minecraft",

        # Self-mod
        "what did you change this week",
        "any pending proposals",

        # Web search
        "search for the latest AMD GPU benchmarks",
        "look up the price of the RTX 5090",

        # Vision
        "what's on my screen right now",
        "look at my screen",

        # Image generation
        "draw me a picture of a sunset",
        "generate an image of Hayeong",

        # Code
        "debug this traceback",
        "write a python function to parse JSON",

        # Conversation (should NOT get misrouted)
        "hey how are you doing",
        "what do you think about this idea",
        "tell me something interesting",
        "I've been feeling kind of tired today",
    ]

    print("=== INTENT DETECTOR TEST (keyword-only, instant) ===\n")
    for msg in test_messages:
        result = detector.detect(msg)
        print(f'  "{msg}"')
        print(f'    → {result["intent"]:20s} | action: {result["action"] or "—":15s} '
              f'| target: {result["target"] or "—":10s} | {result["confidence"]}')
        print()