"""
context_router.py
─────────────────
Context-aware intent router. Uses Qwen 7b with recent conversation
history to understand what James is actually asking for — not just
what keywords appear in the message.

WHY THIS EXISTS
───────────────
The old intent_detector.py used keyword matching with no conversation
context. That meant "I was just asking about search information to test
your web functionality" got routed as a web_search because it contains
the word "search". A human reading the conversation would instantly know
that's a reply to a suspicion question, not a search request.

This router gives the LLM the last few messages so it understands
what's actually happening before deciding what to do.

HOW IT WORKS
────────────
1. Fast path — unambiguous imperative commands (open/close subprocesses)
   are still caught by keyword match. No LLM needed for "open discord".

2. LLM path — everything else goes to Qwen 7b with the last 3 messages
   as context. Returns structured intent JSON. Fast, deterministic (temp=0).

3. Keyword fallback — if Ollama is unreachable or times out, falls back
   to keyword matching so Hayeong keeps working.

INTENTS RETURNED
────────────────
  conversation      → normal chat, goes to main LLM
  web_search        → needs internet lookup
  vision            → look at screen or analyze image
  image_generation  → generate image via ComfyUI
  task              → task list actions
  email             → email actions
  capability        → start/stop a subprocess
  self_mod          → proposals, weekly summary

Each result includes:
  action      → sub-action (e.g. "check_inbox", "start", "add")
  target      → what the action applies to (e.g. "discord")
  confidence  → "high" | "medium" | "low"
  fallback    → True if keyword fallback was used
  reasoning   → why the LLM made this choice (useful for debugging)
"""

import json
import re
import requests
from pathlib import Path

BASE_DIR         = Path(__file__).parent
OLLAMA_URL       = "http://localhost:11434/api/chat"
ROUTER_MODEL     = "qwen2.5:7b"   # Fast, cheap, good enough for routing
ROUTER_TIMEOUT   = 20             # Seconds — 7b needs time to load alongside 14b


# ─────────────────────────────────────────────
# INTENT DEFINITIONS
# Used both in the LLM prompt and as keyword fallback.
# ─────────────────────────────────────────────

INTENT_DEFINITIONS = {
    "web_search": {
        "description": (
            "James wants Hayeong to look something up online — specs, news, prices, facts, "
            "current events, game info, comparisons, or research. "
            "IMPORTANT: If James asks for research, a comparison, or a report on something "
            "AND mentions sending it via email, classify as web_search NOT email. "
            "Email is just the delivery method — the primary task is research."
        ),
        "examples": [
            "search for AMD RX 9070 XT specs",
            "what's the latest news on ComfyUI",
            "look up the price of the RTX 5090",
            "find out about Live2D software",
            "research whale pup and zapmander in Once Human and send me a report",
            "can you do some research on X and write me a comparison report",
            "look into both options and email me a breakdown",
        ],
        "keywords": [
            "search for", "look up", "lookup", "look it up", "google", "find out",
            "latest news", "news about", "what's the latest", "current price",
            "how much does", "check online", "check the web",
            "can you lookup", "can you look up", "can you find",
            "do some research", "research on", "comparison report",
            "write me a report", "write up a comparison", "look into",
        ],
    },
    "vision": {
        "description": "James wants Hayeong to look at his screen or analyze an image file.",
        "examples": [
            "what's on my screen",
            "can you see my screen",
            "look at my screen",
            "what am I looking at",
            "look at this image",
        ],
        "keywords": [
            "what's on my screen", "look at my screen", "see my screen",
            "can you see", "look at this image", "what am i looking at",
            "take a look", "glance at", "check my screen",
        ],
    },
    "image_collab": {
        "description": (
            "James wants to work WITH Hayeong on designing or refining an image over "
            "multiple iterations. Different from a single generation request — this is "
            "an ongoing creative session where she has opinions and engages with the output."
        ),
        "examples": [
            "let's work on your look",
            "let's design your character",
            "can we work on your image together",
            "let's iterate on this",
            "let's do a design session",
            "work with me on generating",
        ],
        "keywords": [
            "work on your look", "design session", "work together on",
            "let's design", "collaborate on", "design your character",
            "your reference sheet", "work on the image together",
        ],
    },
    "image_generation": {
        "description": "James wants Hayeong to generate, draw, or create an image.",
        "examples": [
            "generate an image of",
            "draw me",
            "create a picture of",
            "make it realistic",
            "use what's on my screen to generate",
        ],
        "keywords": [
            "generate", "draw", "paint", "illustrate", "create art",
            "make an image", "make her look", "make it realistic",
            "make it real", "real photo", "turn this into",
        ],
    },
    "task": {
        "description": "Managing a task list — adding, showing, or completing tasks.",
        "examples": [
            "what's on my task list",
            "add a task",
            "mark that as done",
            "what are you working on",
        ],
        "keywords": [
            "task list", "my tasks", "todo list", "to-do list", "backlog",
            "add a task", "add task", "show tasks", "mark done",
            "what are you working on",
        ],
    },
    "email": {
        "description": (
            "Checking inbox, sending a notification, or getting an email summary. "
            "Only use this when the PRIMARY task IS the email action itself. "
            "Do NOT use this if James is asking for research/comparison and mentions "
            "email only as a delivery method — that is web_search."
        ),
        "examples": [
            "check your email",
            "did I get any emails",
            "send me a message",
            "notify me when done",
            "send me a daily summary",
        ],
        "keywords": [
            "check your email", "check my email", "check the inbox",
            "did i get any emails", "any new emails", "inbox",
            "notify me", "ping me", "send me a daily summary",
            "anything come in", "did i get any messages",
        ],
    },
    "capability": {
        "description": "Starting or stopping one of Hayeong's subsystems like Discord or Minecraft.",
        "examples": [
            "open discord",
            "start minecraft",
            "close your mic",
            "stop the observer",
        ],
        "keywords": [
            "open discord", "start discord", "close discord",
            "start minecraft", "load minecraft", "close minecraft",
            "open your mic", "turn on your mic", "close your mic",
            "start observer", "stop observer",
        ],
    },
    "self_mod": {
        "description": "Hayeong's self-improvement system — proposals, summaries, approve/deny.",
        "examples": [
            "show proposals",
            "what did you change this week",
            "any pending proposals",
            "approve that file",
        ],
        "keywords": [
            "proposal", "proposals", "weekly summary", "what did you change",
            "approve", "deny", "pending",
        ],
    },
    "income": {
        "description": (
            "Anything related to Hayeong's income generation — proposing opportunities, "
            "checking goal progress, researching niches, approving proposals, logging sales."
        ),
        "examples": [
            "how much have you earned so far",
            "do you have any income ideas",
            "what proposals are waiting",
            "I approve that proposal",
            "how close are we to the workstation goal",
            "find a good niche for digital art sales",
            "log a sale",
        ],
        "keywords": [
            "earned", "workstation goal", "income", "income proposal", "niche research",
            "etsy", "gumroad", "listing", "product idea", "how much have you earned",
            "fund", "log a sale", "revenue", "workstation fund",
            "show earnings", "earnings report", "monthly report",
            "how did we do", "this month's income", "generate report",
            "how much this month", "income summary",
        ],
    },
    "think_together": {
        "description": (
            "The request is ambiguous, complex with multiple valid approaches, or James seems to be "
            "processing something out loud rather than asking for a specific action. "
            "Use this when it's unclear what he actually wants done — he might be thinking aloud, "
            "working through a decision, or asking for input before committing to anything. "
            "Think Together means Hayeong stays in conversation mode to align before acting, "
            "rather than guessing and firing the wrong tool."
        ),
        "examples": [
            "I've been thinking about what we should do next",
            "can you handle that thing",
            "I'm not sure what to do about the build",
            "what do you think we should do",
            "help me think through this",
            "I dunno, maybe we should just",
            "I need to figure out what to do about",
        ],
        "keywords": [
            "help me think", "think through", "not sure how", "i've been thinking",
            "what do you think we should", "help me figure out", "i don't know what to do",
            "i'm not sure what", "what should we do", "thinking about what",
            "can you handle that", "that thing we talked about", "you know what i mean",
            "figure this out", "work through this",
        ],
    },
    "conversation": {
        "description": "Normal chat, questions, reactions, replies — anything that doesn't need a specific tool.",
        "examples": [],
        "keywords": [],
    },
}

# Sub-action keyword maps (used after intent is classified)
EMAIL_ACTIONS = {
    "send_summary": ["summary", "daily summary", "send me a summary"],
    "check_inbox":  ["check", "inbox", "any emails", "anything come in", "did i get"],
    "search":       [
        "find email", "search email", "search my email", "find that email",
        "look for email", "email about", "email from", "did i get an email",
        "find me an email", "search for email",
    ],
    "notify":       ["email me", "notify me", "ping me", "message me"],
}
TASK_ACTIONS = {
    "show":           ["show tasks", "task list", "what's on", "backlog", "my tasks"],
    "show_completed": ["what have you done", "completed", "show completed"],
    "show_blocked":   ["what's blocked", "blocked tasks"],
    "add":            ["add a task", "remember to", "i need to", "put on the list"],
    "complete":       ["mark done", "mark as done", "finished", "done with"],
}
CAPABILITY_ACTIONS = {
    "start": ["open", "start", "load", "launch", "enable", "turn on", "get on"],
    "stop":  ["close", "stop", "leave", "disconnect", "disable", "turn off"],
}
CAPABILITY_TARGETS = ["discord", "minecraft", "voice", "mic", "observer"]


# ─────────────────────────────────────────────
# FAST PATH — unambiguous imperative commands
# Caught before any LLM call.
# ─────────────────────────────────────────────

_CAPABILITY_PHRASES = {
    # (action, target): [phrases]
    ("start", "discord"):   ["open discord", "start discord", "connect discord",
                             "get on discord", "launch discord", "go on discord"],
    ("stop",  "discord"):   ["close discord", "stop discord", "leave discord"],
    ("start", "voice"):     ["open your mic", "open mic", "start voice", "voice mode",
                             "turn on your mic", "enable voice", "start listening"],
    ("stop",  "voice"):     ["close your mic", "mute", "stop voice", "turn off your mic",
                             "disable voice", "stop listening"],
    ("start", "minecraft"): [
        "load minecraft", "start minecraft", "open minecraft",
        "let's play minecraft", "join minecraft", "play minecraft",
        "let's play", "want to play minecraft", "boot up minecraft",
    ],
    ("stop",  "minecraft"): [
        "close minecraft", "stop minecraft", "leave minecraft",
        "done playing", "quit minecraft", "shut down minecraft",
    ],
    ("start", "observer"):  ["start observer", "start screen observer", "start watching",
                             "enable observer"],
    ("stop",  "observer"):  ["stop observer", "stop watching", "disable observer",
                             "turn off observer"],
}

def _fast_capability_check(text: str) -> dict | None:
    """
    Returns a capability intent dict if the message is an unambiguous
    start/stop command, or None if it needs LLM routing.
    These are so distinctive that keyword matching is reliable.
    """
    t = text.lower().strip()
    for (action, target), phrases in _CAPABILITY_PHRASES.items():
        if any(p in t for p in phrases):
            return {
                "intent":     "capability",
                "action":     action,
                "target":     target,
                "confidence": "high",
                "fallback":   False,
                "reasoning":  f"Fast path: clear capability command ({action} {target})",
            }
    return None


# ─────────────────────────────────────────────
# LLM ROUTER
# ─────────────────────────────────────────────

def _build_router_prompt(message: str, recent_history: list[dict]) -> str:
    """
    Builds the classification prompt including recent conversation context.
    recent_history: last 2-3 turns as [{"role": "user"|"AI", "content": "..."}]
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

    # Format recent history so the LLM has conversational context
    history_lines = []
    for turn in recent_history[-3:]:
        role = "Hayeong" if turn["role"] == "AI" else "James"
        content = turn["content"][:200]  # truncate long entries
        history_lines.append(f"  {role}: {content}")
    history_text = "\n".join(history_lines) if history_lines else "  (start of conversation)"

    return f"""You are Hayeong's intent router. Your only job is to classify what James is asking for.

Recent conversation:
{history_text}

James just said: "{message}"

Classify into exactly one intent:
{intent_list}

Examples:
{examples}

CRITICAL RULES:
- Read the FULL conversation context, not just the new message in isolation.
- If James is replying to something Hayeong said (a question, a suspicion check, a result),
  that reply is almost always "conversation" — not a tool request.
- Only classify as web_search/vision/image_generation if James is CLEARLY requesting that tool.
- RESEARCH + EMAIL: If James asks for research, a comparison, or a report on a topic AND
  mentions email as the delivery method, classify as web_search (NOT email).
  Email is just how she delivers it — the task is research. Example: "look up X and email
  me the report" = web_search, not email.
- EMAIL ONLY: Only classify as email if the primary task IS the email action itself
  (check inbox, send a notification, get a summary of emails).
- THINK TOGETHER: If James is thinking aloud, processing a decision, or the request is
  ambiguous with multiple valid interpretations — classify as think_together, NOT a tool.
  Hayeong should align with him conversationally before acting. Better to ask than to guess
  and fire the wrong capability. Example: "I've been thinking about what we should do" or
  "can you handle that thing" = think_together.
- When in doubt, use "conversation".

Respond with ONLY this JSON — no explanation, no markdown:
{{"intent": "...", "action": "...", "target": "...", "confidence": "high|medium|low", "reasoning": "one sentence"}}

Rules:
- intent must be one of the listed keys
- action: sub-action if relevant ("check_inbox", "start", "add", "show") else ""
- target: what the action applies to ("discord", "minecraft") else ""
- reasoning: one short sentence explaining why"""


def _classify_with_llm(message: str, recent_history: list[dict]) -> dict | None:
    """
    Ask Qwen 7b to classify the intent with conversation context.
    Returns a result dict or None on failure/timeout.
    """
    prompt = _build_router_prompt(message, recent_history)

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   ROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a JSON-only intent classifier. Output only valid JSON."},
                    {"role": "user",   "content": prompt},
                ],
                "stream":  False,
                "options": {"temperature": 0.0},
            },
            timeout=ROUTER_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"].strip()

        # Strip markdown fences if model adds them
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$",       "", content)
        content = content.strip()

        parsed = json.loads(content)

        # Validate intent key
        if parsed.get("intent") not in INTENT_DEFINITIONS:
            parsed["intent"] = "conversation"

        return {
            "intent":     parsed.get("intent",    "conversation"),
            "action":     parsed.get("action",    ""),
            "target":     parsed.get("target",    ""),
            "confidence": parsed.get("confidence","medium"),
            "reasoning":  parsed.get("reasoning", ""),
            "fallback":   False,
        }

    except Exception as e:
        print(f"   [Router] LLM failed ({e}) — using keyword fallback")
        return None


# ─────────────────────────────────────────────
# KEYWORD FALLBACK
# ─────────────────────────────────────────────

def _classify_with_keywords(text: str) -> dict:
    """Fast keyword fallback when LLM is unavailable."""
    t = text.lower().strip()

    priority = [
        "capability", "vision", "image_collab", "image_generation", "web_search",
        "email", "task", "income", "self_mod", "think_together", "conversation",
    ]

    for intent in priority:
        keywords = INTENT_DEFINITIONS[intent]["keywords"]
        if any(kw in t for kw in keywords):
            return {
                "intent":     intent,
                "action":     "",
                "target":     "",
                "confidence": "medium",
                "reasoning":  "keyword fallback",
                "fallback":   True,
            }

    return {
        "intent":     "conversation",
        "action":     "",
        "target":     "",
        "confidence": "low",
        "reasoning":  "no keywords matched",
        "fallback":   True,
    }


# ─────────────────────────────────────────────
# SUB-ACTION RESOLUTION
# ─────────────────────────────────────────────

def _fill_sub_action(text: str, result: dict):
    """Fill in action and target if LLM didn't provide them."""
    t      = text.lower().strip()
    intent = result["intent"]

    if intent == "email" and not result["action"]:
        for action, keywords in EMAIL_ACTIONS.items():
            if any(kw in t for kw in keywords):
                result["action"] = action
                break
        if not result["action"]:
            result["action"] = "notify"

    elif intent == "task" and not result["action"]:
        for action, keywords in TASK_ACTIONS.items():
            if any(kw in t for kw in keywords):
                result["action"] = action
                break
        if not result["action"]:
            result["action"] = "show"

    elif intent == "capability":
        if not result["action"]:
            for action, keywords in CAPABILITY_ACTIONS.items():
                if any(kw in t for kw in keywords):
                    result["action"] = action
                    break
        if not result["target"]:
            for cap in CAPABILITY_TARGETS:
                if cap in t:
                    result["target"] = "voice" if cap == "mic" else cap
                    break


# ─────────────────────────────────────────────
# DELIVERY MODE DETECTION
# For web_search intents — determines whether the response
# should be conversational (quick answer in her voice) or
# a document (formatted breakdown emailed or saved).
# ─────────────────────────────────────────────

_DOCUMENT_SIGNALS = [
    "compare", "comparison", "vs", "versus", "difference between",
    "full breakdown", "break it down", "spec sheet", "full list",
    "detailed", "everything about", "all the specs", "all the details",
    "give me a report", "write a report", "research", "full comparison",
    "summarize everything", "full summary", "put it in a document",
    "send me", "email me", "save it", "write it up",
    "side by side", "pros and cons", "full analysis",
    # List requests — data-heavy, better as a document
    "give me a list", "can you list", "list of", "a good list",
    "list them", "list some", "list out", "show me a list",
    "what are some", "what are the best", "what are the top",
    "options for", "recommendations for", "suggestions for",
]

_CONVERSATIONAL_SIGNALS = [
    "what do you think", "your opinion", "do you think",
    "quick question", "is it good", "is it worth", "should i",
    "do you recommend", "what's better", "which is better",
    "quick answer", "just curious", "wondering if",
]

def _detect_delivery_mode(message: str) -> str:
    """
    Returns "document" or "conversational" based on signal words in the message.
    Document mode = data-heavy, formatted, emailed/saved.
    Conversational mode = quick answer in Hayeong's voice.
    Defaults to "conversational" when unclear — less disruptive than
    generating a document nobody asked for.
    """
    t = message.lower()
    if any(sig in t for sig in _DOCUMENT_SIGNALS):
        return "document"
    if any(sig in t for sig in _CONVERSATIONAL_SIGNALS):
        return "conversational"
    # Default: conversational. Better to talk and offer a document
    # than to generate one unprompted.
    return "conversational"




class ContextRouter:
    """
    Context-aware intent router.
    Drop-in replacement for IntentDetector — same interface.

    Usage in main.py:
        from context_router import ContextRouter
        router = ContextRouter()

        # In main loop, pass recent memory for context:
        intent = router.route(user_input, memory[-4:])
    """

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm

    def route(self, message: str, recent_history: list[dict] = None) -> dict:
        """
        Classify the intent of a message with optional conversation context.

        message:        The user's current message
        recent_history: Last few memory entries [{"role": ..., "content": ...}]
                        Pass memory[-4:] from main.py for best results.
        """
        recent_history = recent_history or []

        # ── Fast path: unambiguous capability commands ──
        fast = _fast_capability_check(message)
        if fast:
            _fill_sub_action(message, fast)
            return fast

        # ── Fast path: pure single or two-word acknowledgments ──
        # "yeah", "ok", "thanks", "got it" are unambiguously conversation.
        # Short imperatives like "ok find it" or "hey search that" are NOT caught here —
        # they must reach decide_action() so the LLM can reason about them.
        words = message.strip().split()
        _PURE_ACKS = {
            "ok", "okay", "yeah", "yep", "nope", "no", "yes", "sure",
            "thanks", "thank", "cool", "nice", "good", "great", "awesome",
            "alright", "lol", "haha", "hmm", "hm",
            "hey", "hi", "hello", "sup", "yo", "heya", "hiya",
            "got it", "sounds good", "makes sense", "understood",
        }
        if len(words) == 1 and words[0].lower().rstrip("!?,. ") in _PURE_ACKS:
            return {
                "intent":     "conversation",
                "action":     "",
                "target":     "",
                "confidence": "high",
                "reasoning":  "pure acknowledgment — no routing needed",
                "fallback":   False,
            }
        if len(words) == 2:
            phrase = " ".join(w.lower().rstrip("!?,. ") for w in words)
            if phrase in _PURE_ACKS:
                return {
                    "intent":     "conversation",
                    "action":     "",
                    "target":     "",
                    "confidence": "high",
                    "reasoning":  "pure acknowledgment — no routing needed",
                    "fallback":   False,
                }

        # ── Fast path: rest/recharge commands ──
        # Handled by main.py's rest handler, not ProcessManager.
        # Must not be routed as a capability.
        _REST_PHRASES = [
            "take a rest", "go rest", "get some rest", "rest up",
            "recharge", "take a break", "you can rest",
            "rest for a bit", "go to sleep",
        ]
        t = message.lower().strip()
        if any(p in t for p in _REST_PHRASES):
            return {
                "intent":     "conversation",
                "action":     "",
                "target":     "",
                "confidence": "high",
                "reasoning":  "rest/recharge command — handled by energy manager",
                "fallback":   False,
            }

        # ── LLM path: context-aware classification ──
        if self.use_llm:
            result = _classify_with_llm(message, recent_history)
            if result:
                _fill_sub_action(message, result)
                # Add delivery mode for web_search intents
                if result["intent"] == "web_search":
                    result["delivery_mode"] = _detect_delivery_mode(message)
                if result.get("reasoning"):
                    mode_note = f" [{result.get('delivery_mode', '')}]" if result["intent"] == "web_search" else ""
                    print(f"   [Router] {result['intent']}{mode_note} — {result['reasoning']}")
                return result

        # ── Keyword fallback ──
        result = _classify_with_keywords(message)
        _fill_sub_action(message, result)
        if result["intent"] == "web_search":
            result["delivery_mode"] = _detect_delivery_mode(message)
        return result


# ─────────────────────────────────────────────
# GPU STATUS CHECK
# Quick check whether Ollama models are running on GPU or spilling to RAM.
# ─────────────────────────────────────────────

def check_gpu_status() -> dict:
    """
    Checks Ollama's /api/ps endpoint for loaded models and their VRAM usage.
    Returns a dict with model info and a summary string for printing.

    Call this at startup or any time you want to verify GPU health.
    """
    try:
        resp = requests.get("http://localhost:11434/api/ps", timeout=5)
        resp.raise_for_status()
        data   = resp.json()
        models = data.get("models", [])

        if not models:
            return {
                "ok":      True,
                "models":  [],
                "summary": "No models currently loaded in Ollama.",
            }

        results  = []
        any_warn = False

        for m in models:
            name       = m.get("name", "unknown")
            size_total = m.get("size",      0)
            size_vram  = m.get("size_vram", 0)
            size_ram   = size_total - size_vram

            pct_gpu = (size_vram / size_total * 100) if size_total > 0 else 0
            on_gpu  = size_ram == 0

            if not on_gpu:
                any_warn = True

            results.append({
                "name":       name,
                "total_gb":   round(size_total / 1e9, 1),
                "vram_gb":    round(size_vram  / 1e9, 1),
                "ram_gb":     round(size_ram   / 1e9, 1),
                "pct_gpu":    round(pct_gpu, 1),
                "fully_gpu":  on_gpu,
            })

        lines = ["GPU STATUS:"]
        for r in results:
            status = "✅ fully on GPU" if r["fully_gpu"] else f"⚠️  {r['ram_gb']}GB spilling to RAM"
            lines.append(
                f"  {r['name']}: {r['vram_gb']}GB VRAM / {r['total_gb']}GB total — {status}"
            )

        if any_warn:
            lines.append("")
            lines.append("  ⚠️  Some layers are in RAM — responses will be slower.")
            lines.append("  Fix: set OLLAMA_NUM_GPU=99 and restart Ollama.")
        else:
            lines.append("  All models fully on GPU.")

        return {
            "ok":      not any_warn,
            "models":  results,
            "summary": "\n".join(lines),
        }

    except requests.exceptions.ConnectionError:
        return {
            "ok":      False,
            "models":  [],
            "summary": "⚠️  Ollama not reachable — is it running?",
        }
    except Exception as e:
        return {
            "ok":      False,
            "models":  [],
            "summary": f"⚠️  GPU check failed: {e}",
        }


def print_gpu_status():
    """Convenience function — print GPU status to console."""
    status = check_gpu_status()
    print(status["summary"])
    return status["ok"]


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ContextRouter — Standalone Test")
    print("=" * 60)

    # GPU check first
    print()
    print_gpu_status()
    print()

    router = ContextRouter(use_llm=True)

    # Simulate the exact conversation that broke the old router
    test_cases = [
        {
            "desc":    "Reply to suspicion question (was misrouted as web_search)",
            "history": [
                {"role": "AI",   "content": "Something feels a little off. Mind if I ask — is this James I'm talking to?"},
            ],
            "message": "Yeah this is me, why? What makes you think this isn't me? I was just asking about search information cause I'm trying to test your web functionality.",
            "expect":  "conversation",
        },
        {
            "desc":    "Clear web search request",
            "history": [{"role": "user", "content": "hey hayeong!"}],
            "message": "can you look up the specs for the AMD RX 9070 XT?",
            "expect":  "web_search",
        },
        {
            "desc":    "Greeting — should never route to a tool",
            "history": [],
            "message": "hi hayeong, how are you doing today?",
            "expect":  "conversation",
        },
        {
            "desc":    "Capability command — fast path",
            "history": [],
            "message": "open discord",
            "expect":  "capability",
        },
        {
            "desc":    "Thanks after search result (was misrouted before)",
            "history": [
                {"role": "user", "content": "look up AMD 9070 XT specs"},
                {"role": "AI",   "content": "According to technical.city, the RX 9070 XT has 16GB GDDR6..."},
            ],
            "message": "Great work Hayeong, thanks!",
            "expect":  "conversation",
        },
        {
            "desc":    "News search",
            "history": [],
            "message": "what's the latest news on ComfyUI updates?",
            "expect":  "web_search",
        },
        {
            "desc":    "Screen vision",
            "history": [],
            "message": "hey can you take a look at my screen real quick?",
            "expect":  "vision",
        },
    ]

    print("── ROUTING TESTS ──\n")
    passed = 0
    for tc in test_cases:
        result = router.route(tc["message"], tc["history"])
        ok     = result["intent"] == tc["expect"]
        passed += ok
        status = "✅" if ok else "❌"
        fb     = " [fallback]" if result["fallback"] else ""
        print(f"{status}  {tc['desc']}")
        print(f"     Message:  {tc['message'][:70]}")
        print(f"     Expected: {tc['expect']} | Got: {result['intent']} ({result['confidence']}){fb}")
        if result.get("reasoning"):
            print(f"     Reason:   {result['reasoning']}")
        print()

    print(f"Result: {passed}/{len(test_cases)} passed")