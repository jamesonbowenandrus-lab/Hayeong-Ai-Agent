"""
intent_detector.py
──────────────────
Replaces all scattered keyword/wake-word detection in main.py with a
single LLM-based classification step.

HOW IT WORKS
────────────
1. Every user message passes through detect_intent() first.
2. A fast, small Ollama call classifies the message into one of the
   intents defined by your capability_registry.json.
3. main.py reads the result and routes accordingly — no more missed
   keywords, no more "oops wrong function" fallthrough.

INTENTS RETURNED
────────────────
  "conversation"   → normal chat, goes straight to LLM
  "email"          → any email action (check, send, notify)
  "task"           → task list actions (show, add, complete)
  "capability"     → start/stop a subprocess (discord, minecraft, etc.)
  "self_mod"       → proposals, weekly summary, approve/deny
  "status"         → what's running, system state
  "memory"         → explicit recall ("do you remember...")
  "code"           → coding help, debugging

Each result also includes:
  action     → sub-action when relevant (e.g. "check_inbox", "add", "start")
  target     → what the action applies to (e.g. "discord", "minecraft")
  confidence → "high" | "medium" | "low"
  fallback   → True if keyword fallback was used instead of LLM

FALLBACK BEHAVIOR
─────────────────
If Ollama is unreachable or the LLM call fails, the detector falls back
to keyword matching so Hayeong keeps working — just less flexibly.
This means the system degrades gracefully instead of breaking entirely.

USAGE IN main.py
────────────────
  from intent_detector import IntentDetector
  detector = IntentDetector()

  # In your main loop, before any other checks:
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
      # send to LLM as normal
"""

import json
import re
import requests
from pathlib import Path

BASE_DIR         = Path(__file__).parent
CAPABILITY_REG   = BASE_DIR / "capability_registry.json"
OLLAMA_URL       = "http://localhost:11434/api/chat"
CLASSIFIER_MODEL = "qwen2.5:7b"   # Same as your primary — fast enough for classification

# ─────────────────────────────────────────────
# INTENT DEFINITIONS
# Describes each intent so the LLM knows what to look for.
# Also used as fallback keyword sets.
# ─────────────────────────────────────────────

INTENT_DEFINITIONS = {
    "email": {
        "description": "Anything about email: checking inbox, sending a message, notifying James, daily summary.",
        "examples": [
            "check your email",
            "did I get any emails",
            "send me a message",
            "ping me about that",
            "notify me when done",
            "anything come in",
            "send me a summary",
            "email me",
        ],
        "keywords": [
            "email", "inbox", "message", "notify", "notification",
            "ping me", "send me", "summary", "anything come in", "did i get",
        ],
    },
    "task": {
        "description": "Managing a task list: adding, showing, completing, or noting tasks.",
        "examples": [
            "what's on my task list",
            "show tasks",
            "add a task",
            "I need to remember to fix that",
            "mark that as done",
            "what are you working on",
            "what have you done",
        ],
        "keywords": [
            "task", "todo", "to-do", "backlog", "add a task", "show tasks",
            "mark done", "complete", "what are you working on", "what have you done",
        ],
    },
    "capability": {
        "description": "Starting or stopping one of Hayeong's subsystems: Discord, Minecraft, voice mic, screen observer.",
        "examples": [
            "open discord",
            "start minecraft",
            "load minecraft",
            "open your mic",
            "turn on your mic",
            "stop discord",
            "close minecraft",
            "start the screen observer",
        ],
        "keywords": [
            "discord", "minecraft", "observer", "screen observer",
            "mic", "voice mode", "open", "start", "load", "close", "stop", "launch",
        ],
    },
    "self_mod": {
        "description": "Hayeong's self-improvement system: proposals, weekly summaries, approving or denying changes.",
        "examples": [
            "show proposals",
            "what did you change this week",
            "any pending proposals",
            "approve that file",
            "deny that change",
            "weekly summary",
        ],
        "keywords": [
            "proposal", "proposals", "weekly summary", "what did you change",
            "what have you changed", "approve", "deny", "pending",
        ],
    },
    "status": {
        "description": "Asking what's currently running or the system state.",
        "examples": [
            "what's running",
            "system status",
            "what are you running",
            "are you on discord",
        ],
        "keywords": [
            "what's running", "status", "what are you running", "system",
        ],
    },
    "memory": {
        "description": "Explicitly asking Hayeong to recall something from memory.",
        "examples": [
            "do you remember when",
            "didn't we talk about",
            "what did I say about",
            "from our last conversation",
        ],
        "keywords": [
            "remember", "recall", "do you remember", "didn't we", "last time",
            "previously", "earlier", "we talked about",
        ],
    },
    "code": {
        "description": "Coding help: writing, debugging, reviewing, or explaining code.",
        "examples": [
            "write a python function",
            "debug this error",
            "can you fix this code",
            "how do I implement",
        ],
        "keywords": [
            "python", "javascript", "debug", "fix this", "code", "script",
            "function", "error", "traceback", "implement",
        ],
    },
    "web_search": {
        "description": "Looking something up on the internet: news, current events, facts, prices, specs, people, or anything that needs live information.",
        "examples": [
            "search for the best AMD GPU",
            "look up DuckDuckGo",
            "what's the latest on the RTX 5090",
            "news about ComfyUI",
            "google AMD RX 9070 XT price",
            "find out about Live2D software",
            "what is the current price of",
            "who is the CEO of",
            "is X still available",
            "how much does X cost",
        ],
        "keywords": [
            "search for", "look up", "google", "find out", "find out about",
            "latest news", "news about", "what's the latest", "what is the current",
            "current price", "how much does", "who is", "is it still",
            "search", "look it up", "check online", "check the web",
        ],
    },
    "vision": {
        "description": "Hayeong looking at James's screen or analyzing an image during conversation — not for generating images, but for understanding what's visible.",
        "examples": [
            "what's on my screen",
            "can you see my screen",
            "look at my screen",
            "what am I looking at",
            "what is this",
            "look at this image",
            "can you describe what you see",
            "what does this image show",
            "take a look at my screen",
        ],
        "keywords": [
            "what's on my screen", "look at my screen", "see my screen",
            "can you see", "look at this", "what is this image",
            "describe what you see", "what am i looking at",
            "take a look", "glance at", "check my screen",
        ],
    },
    "image_generation": {
        "description": "Any request to generate, draw, create, or visualize an image — including from text, a reference image, or the current screen.",
        "examples": [
            "generate an image of",
            "draw me",
            "create a picture of",
            "make an image",
            "visualize this",
            "show me what X looks like",
            "use what's on my screen",
            "make it realistic",
            "what would X look like",
            "turn this into a photo",
            "paint me",
        ],
        "keywords": [
            "generate", "draw", "paint", "illustrate", "image", "picture",
            "visualize", "show me what", "create art", "make her look",
            "on my screen", "from this image", "make realistic", "make it real",
            "real photo", "turn this into",
        ],
    },
    "conversation": {
        "description": "Normal conversation, questions, chat — anything that doesn't match a specific capability.",
        "examples": [],
        "keywords": [],
    },
}

# Sub-action keywords for email and task routing
# These are used AFTER the intent is classified to determine the specific action
EMAIL_ACTION_KEYWORDS = {
    "send_summary": ["summary", "daily summary", "send me a summary", "email me a summary"],
    "check_inbox":  ["check", "inbox", "any emails", "new emails", "anything come in",
                     "did i get", "got any", "messages"],
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


# ─────────────────────────────────────────────
# INTENT DETECTOR
# ─────────────────────────────────────────────

class IntentDetector:
    """
    Single entry point for all intent classification.
    Call detect(user_input) before routing any message.
    """

    def __init__(self, use_llm: bool = True):
        self.use_llm     = use_llm
        self.capabilities = self._load_capabilities()

    def _load_capabilities(self) -> list:
        """Load active capability names from registry for context injection."""
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
        Classify a user message into an intent.

        Returns:
        {
            "intent":     str,   # e.g. "email", "task", "conversation"
            "action":     str,   # sub-action, e.g. "check_inbox", "start", "add"
            "target":     str,   # target of action, e.g. "discord", "minecraft"
            "confidence": str,   # "high" | "medium" | "low"
            "fallback":   bool,  # True if keyword fallback was used
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

        # ── Try LLM classification first ──
        if self.use_llm:
            llm_result = self._classify_with_llm(text)
            if llm_result:
                result.update(llm_result)
                result["fallback"] = False
                # Fill in sub-action and target if LLM didn't specify
                if not result["action"] or not result["target"]:
                    self._fill_sub_action(text, result)
                return result

        # ── Keyword fallback ──
        result["fallback"] = True
        keyword_result = self._classify_with_keywords(text)
        result.update(keyword_result)
        self._fill_sub_action(text, result)
        return result

    # ─────────────────────────────────────────────
    # LLM CLASSIFICATION
    # ─────────────────────────────────────────────

    def _classify_with_llm(self, text: str) -> "dict | None":
        """
        Ask the LLM to classify the intent.
        Returns a partial result dict or None on failure.
        """
        intent_list = "\n".join(
            f'  "{k}": {v["description"]}'
            for k, v in INTENT_DEFINITIONS.items()
        )
        examples = "\n".join(
            f'  "{ex}" → {k}'
            for k, v in INTENT_DEFINITIONS.items()
            for ex in v["examples"][:2]
        )

        system_prompt = f"""You are an intent classifier for an AI assistant named Hayeong.
Classify the user message into exactly one intent from this list:

{intent_list}

Examples:
{examples}

Respond with ONLY a JSON object in this exact format — no explanation, no markdown:
{{"intent": "...", "action": "...", "target": "...", "confidence": "high|medium|low"}}

Rules:
- intent must be one of the listed keys
- action is the sub-action if relevant (e.g. "check_inbox", "start", "stop", "add", "show") — else ""
- target is what the action applies to (e.g. "discord", "minecraft", "voice") — else ""
- confidence: high if very clear, medium if likely, low if uncertain
- When in doubt, use "conversation"
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": text},
        ]

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":   CLASSIFIER_MODEL,
                    "messages": messages,
                    "stream":  False,
                    "options": {"temperature": 0.0},  # deterministic classification
                },
                timeout=10,  # fast timeout — fallback if slow
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()

            # Strip markdown fences if model adds them
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()

            parsed = json.loads(content)

            # Validate the intent key
            if parsed.get("intent") not in INTENT_DEFINITIONS:
                parsed["intent"] = "conversation"

            return {
                "intent":     parsed.get("intent", "conversation"),
                "action":     parsed.get("action", ""),
                "target":     parsed.get("target", ""),
                "confidence": parsed.get("confidence", "medium"),
            }

        except Exception as e:
            print(f"⚠️  Intent LLM failed ({e}) — using keyword fallback")
            return None

    # ─────────────────────────────────────────────
    # KEYWORD FALLBACK
    # ─────────────────────────────────────────────

    def _classify_with_keywords(self, text: str) -> dict:
        """
        Fast keyword-based fallback. Less flexible than LLM but always works.
        Checks intents in priority order.
        """
        t = text.lower().strip()

        # Check each intent's keywords in priority order
        priority_order = [
            "capability", "vision", "image_generation", "web_search",
            "email", "task", "self_mod", "status", "memory", "code", "conversation"
        ]

        for intent in priority_order:
            keywords = INTENT_DEFINITIONS[intent]["keywords"]
            if any(kw in t for kw in keywords):
                return {
                    "intent":     intent,
                    "action":     "",
                    "target":     "",
                    "confidence": "medium",
                }

        return {"intent": "conversation", "action": "", "target": "", "confidence": "low"}

    # ─────────────────────────────────────────────
    # SUB-ACTION RESOLUTION
    # ─────────────────────────────────────────────

    def _fill_sub_action(self, text: str, result: dict):
        """
        Fill in action and target based on the classified intent.
        Called when LLM didn't provide them or as fallback resolution.
        """
        t      = text.lower().strip()
        intent = result["intent"]

        if intent == "email" and not result["action"]:
            for action, keywords in EMAIL_ACTION_KEYWORDS.items():
                if any(kw in t for kw in keywords):
                    result["action"] = action
                    break
            if not result["action"]:
                result["action"] = "notify"  # safe default for email intent

        elif intent == "task" and not result["action"]:
            for action, keywords in TASK_ACTION_KEYWORDS.items():
                if any(kw in t for kw in keywords):
                    result["action"] = action
                    break
            if not result["action"]:
                result["action"] = "show"  # safe default for task intent

        elif intent == "capability":
            # Determine start vs stop
            if not result["action"]:
                for action, keywords in CAPABILITY_ACTION_KEYWORDS.items():
                    if any(kw in t for kw in keywords):
                        result["action"] = action
                        break

            # Determine which capability
            if not result["target"]:
                for cap in CAPABILITY_TARGETS:
                    if cap in t:
                        # Normalize "mic" to "voice"
                        result["target"] = "voice" if cap == "mic" else cap
                        break


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    detector = IntentDetector(use_llm=True)

    test_messages = [
        # Email — these should work even without exact wake words
        "did anything come in",
        "can you ping me about that later",
        "check if I got any new messages",
        "send me a quick summary of today",

        # Task
        "what's on my task list",
        "I need to remember to fix the voice bot",
        "mark that discord fix as done",

        # Capability
        "open discord",
        "let's play minecraft",
        "turn on your mic",
        "close minecraft",

        # Self-mod
        "what did you change this week",
        "any pending proposals",

        # Conversation (should NOT get misrouted)
        "hey how are you doing",
        "what do you think about this idea",
        "tell me something interesting",
    ]

    print("=== INTENT DETECTOR TEST ===\n")
    for msg in test_messages:
        result = detector.detect(msg)
        fallback_note = " [keyword fallback]" if result["fallback"] else ""
        print(f'  "{msg}"')
        print(f'    → {result["intent"]} | action: {result["action"] or "—"} '
              f'| target: {result["target"] or "—"} '
              f'| {result["confidence"]}{fallback_note}')
        print()