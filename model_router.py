"""
MODEL ROUTER
Classifies incoming messages and routes them to the right model.

A lightweight intent classifier runs before every request.
Hayeong uses the best tool for each job — conversation goes to her
main LLM, code goes to DeepSeek, memory queries pull embeddings first.

Usage:
    router = ModelRouter()
    decision = router.route("can you write me a Python function that...")
    model = decision["model"]
    needs_memory = decision["needs_memory_lookup"]
"""

import re
import json
import datetime
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
ROUTER_LOG = BASE_DIR / "logs" / "model_routing.log"
ROUTER_LOG.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# MODEL REGISTRY
# Update model names to match your Ollama setup.
# Run: ollama list   to see what's installed.
# ─────────────────────────────────────────────

# VRAM budget on RTX 3090 (24GB CUDA):
#   llama3.2:latest    ≈  2GB  (communication LLM — port 11434, always loaded)
#   deepseek-r1:latest ≈  5GB  (reasoning LLM    — port 11435, always loaded)
#   phi3:mini          ≈  2GB  (task agent        — port 11436, always loaded)
#   Kokoro TTS           ≈  2GB  (voice server)
#   Whisper              ≈  2GB  (voice input)
#   ─────────────────────────────────────────────────────────────
#   Total core           ≈ 16GB  (~8GB headroom for peaks)
#
# RX 7900 XTX (24GB AMD/ROCm) — creative compute, NOT for core LLMs:
#   Vision models, image gen, music gen, Blender — load on demand
#   James's games — always free, zero competition from Hayeong
#
# Architecture rule:
#   communication — everything James hears (voice, text responses)
#   reasoning     — all decisions, planning, capability dispatch, Minecraft

MODELS = {
    # ── Communication LLM — all James-facing output (port 11434) ──
    # llama3.2: ~2GB VRAM, fast and natural for conversation
    "communication": {
        "name":           "llama3.2:latest",
        "ollama_name":    "llama3.2:latest",
        "ollama_url":     "http://localhost:11434/api/chat",
        "description":    "Communication agent — all James-facing responses, voice, text",
        "context_window": 8192,
    },

    # ── Reasoning LLM — deep planning and decisions (port 11435) ──
    "reasoning": {
        "name":           "deepseek-r1:latest",
        "ollama_name":    "deepseek-r1:latest",
        "ollama_url":     "http://localhost:11435/api/chat",
        "description":    "Reasoning agent — planning, decisions, cross-domain thinking",
        "context_window": 8192,
    },

    # ── Task execution LLM — runs plans, controls Minecraft (port 11436) ──
    # Phi-3 Mini 3.8b: ~2GB VRAM, fast and reliable at structured execution
    "task": {
        "name":           "phi3:mini",
        "ollama_name":    "phi3:mini",
        "ollama_url":     "http://localhost:11436/api/chat",
        "description":    "Task execution agent — follows plans, runs scripts, controls Minecraft",
        "context_window": 8192,
    },

    # ── Coding specialist ──
    "coder": {
        "name":           "deepseek-coder:33b",
        "ollama_name":    "deepseek-coder:33b",
        "ollama_url":     "http://localhost:11434/api/chat",
        "description":    "Code generation, debugging, script writing",
        "context_window": 16384,
    },

    # ── Vision models ──
    "vision": {
        "name":           "llava:13b",
        "ollama_name":    "llava:13b",
        "ollama_url":     "http://localhost:11434/api/chat",
        "description":    "Vision — screen observation, image understanding, screenshot analysis",
        "context_window": 4096,
    },
    "vision_fast": {
        "name":           "moondream:latest",
        "ollama_name":    "moondream:latest",
        "ollama_url":     "http://localhost:11434/api/chat",
        "description":    "Fast vision — quick image descriptions, lightweight visual tasks",
        "context_window": 2048,
    },

    # ── Embeddings — long-term memory vector search ──
    "embeddings": {
        "name":           "nomic-embed-text",
        "ollama_name":    "nomic-embed-text",
        "ollama_url":     "http://localhost:11434/api/embeddings",
        "description":    "Embedding model for ChromaDB long-term memory vector search",
        "context_window": 8192,
        "embedding_only": True,
    },
}

# ─────────────────────────────────────────────
# INTENT PATTERNS
# Pattern matching for fast classification.
# Runs before any LLM call — zero latency.
# ─────────────────────────────────────────────

CODE_PATTERNS = [
    r"\bwrite\s+(a\s+)?(python|javascript|js|bash|code|script|function|class|module)\b",
    r"\b(debug|fix|refactor|optimize|review)\s+(this\s+)?(code|script|function|error|bug)\b",
    r"\b(implement|create)\s+(a\s+)?(function|method|class|module|api|endpoint)\b",
    r"\bhow\s+do\s+i\s+(code|program|implement|write)\b",
    r"\bcan\s+you\s+(code|program|write|fix|debug)\b",
    r"```[a-z]*\n",                          # Fenced code block in message
    r"\bSyntaxError\b|\bTraceback\b",        # Python error signatures
    r"\bdef\s+\w+\(|class\s+\w+[:(]",       # Python syntax
]

MEMORY_PATTERNS = [
    r"\b(remember|recall|do you remember|didn't we|we talked about)\b",
    r"\b(last time|previously|before|earlier|a while ago)\b",
    r"\bwhat did (i|we|you) say\b",
    r"\bfrom our (last|previous|earlier) (conversation|chat|session)\b",
    r"\bdo you know (my|our)\b",
]

VISION_PATTERNS = [
    r"\b(look at|look at (my|the) screen|what('s| is) on (my |the )?screen)\b",
    r"\bcan you see\b",
    r"\b(describe|analyze|read) (this |the )?(image|screenshot|screen|picture|photo)\b",
    r"\bwhat('s| is) (this|that) (in the|on the)?\b",
]

IDENTITY_PATTERNS = [
    r"\b(who are you|what are you|tell me about yourself)\b",
    r"\b(your (name|identity|personality|feelings?))\b",
    r"\b(do you feel|are you (happy|sad|okay|fine|good))\b",
    r"\b(how are you|how('s| is) it going)\b",
]

# These signal that a long message genuinely needs deeper reasoning —
# not just that the user typed a lot or said hello.
COMPLEXITY_PATTERNS = [
    r"\b(plan|planning|strategy|strategize)\b",
    r"\b(analyze|analysis|analyse|break down|break this down)\b",
    r"\b(compare|comparison|pros and cons|trade.?offs?)\b",
    r"\b(research|investigate|deep dive|thoroughly)\b",
    r"\b(design|architect|structure|framework)\b",
    r"\b(explain (in detail|thoroughly|fully|completely))\b",
    r"\b(walk me through|step by step|help me think)\b",
    r"\b(decision|deciding|should i|which (option|choice|path))\b",
    r"\b(long.?term|roadmap|milestone|goal)\b",
]

# Intents that should always stay on 14b — the tool does the heavy lifting,
# the LLM just synthesizes the result.
TOOL_INTENTS = {"web_search", "vision", "image_generation"}


class ModelRouter:
    """
    Routes incoming messages to the appropriate model.
    Runs a fast pattern-match first; falls back to LLM classification if ambiguous.
    """

    def __init__(self):
        self._load_model_availability()

    # ─────────────────────────────────────────────
    # MODEL AVAILABILITY CHECK
    # ─────────────────────────────────────────────

    def _load_model_availability(self):
        """Check which models are actually installed in Ollama."""
        self.available = {}
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.lower()
            for key, model in MODELS.items():
                model_name = model["ollama_name"].lower()
                # Check if model name appears in ollama list output
                base_name = model_name.split(":")[0]
                self.available[key] = base_name in output
        except Exception:
            # If ollama isn't reachable, assume communication model is available
            self.available = {k: (k == "communication") for k in MODELS}

    def is_available(self, model_key: str) -> bool:
        return self.available.get(model_key, False)

    # ─────────────────────────────────────────────
    # CORE ROUTING LOGIC
    # ─────────────────────────────────────────────

    def classify_intent(self, message: str) -> dict:
        """
        Fast pattern-based intent classification.
        Returns intent category and confidence.
        """
        msg_lower = message.lower()
        scores = {
            "code": 0,
            "memory": 0,
            "vision": 0,
            "identity": 0,
            "general": 1,  # Default score
        }

        for pattern in CODE_PATTERNS:
            if re.search(pattern, msg_lower, re.IGNORECASE):
                scores["code"] += 2

        for pattern in MEMORY_PATTERNS:
            if re.search(pattern, msg_lower, re.IGNORECASE):
                scores["memory"] += 2

        for pattern in VISION_PATTERNS:
            if re.search(pattern, msg_lower, re.IGNORECASE):
                scores["vision"] += 3  # Vision is distinctive

        for pattern in IDENTITY_PATTERNS:
            if re.search(pattern, msg_lower, re.IGNORECASE):
                scores["identity"] += 2

        # Determine winner
        top_intent = max(scores, key=scores.get)
        top_score = scores[top_intent]

        return {
            "intent": top_intent,
            "scores": scores,
            "confidence": "high" if top_score >= 4 else "medium" if top_score >= 2 else "low",
            "raw_message": message,
        }

    def route(self, message: str, has_image: bool = False) -> dict:
        """
        Main routing function. Returns a decision dict:
        {
            model: str               — model key to use
            model_name: str          — actual ollama model name
            intent: str              — detected intent
            needs_memory_lookup: bool — should we pull embeddings first?
            needs_vision: bool       — is there a vision component?
            fallback_used: bool      — did we fall back to main model?
            reasoning: str           — why this decision was made
        }
        """
        classification = self.classify_intent(message)
        intent = classification["intent"]

        decision = {
            "model":              "communication",
            "model_name":         MODELS["communication"]["ollama_name"],
            "intent":             intent,
            "needs_memory_lookup": False,
            "needs_vision":       has_image,
            "fallback_used":      False,
            "reasoning":          "",
            "timestamp":          datetime.datetime.now().isoformat(),
        }

        # ── TOOL-ASSISTED INTENTS — communication LLM synthesizes results ──
        if intent in TOOL_INTENTS:
            decision["reasoning"] = f"Tool intent ({intent}) — communication LLM synthesizes result."

        # ── CODE TASKS ──
        elif intent == "code" and classification["scores"]["code"] >= 2:
            if self.is_available("coder"):
                decision["model"]      = "coder"
                decision["model_name"] = MODELS["coder"]["ollama_name"]
                decision["reasoning"]  = "Code intent — routing to DeepSeek Coder 33b."
            else:
                decision["fallback_used"] = True
                decision["reasoning"]     = "Code intent — DeepSeek not available, falling back to communication LLM."

        # ── MEMORY TASKS ──
        elif intent == "memory":
            decision["needs_memory_lookup"] = True
            decision["reasoning"] = "Memory recall intent — pulling ChromaDB embeddings before LLM call."

        # ── VISION TASKS ──
        elif intent == "vision" or has_image:
            decision["needs_vision"] = True
            decision["reasoning"]    = "Vision intent — vision_bridge handles analysis, communication LLM responds."

        # ── GENERAL CONVERSATION ──
        else:
            decision["reasoning"] = f"Intent: {intent} — communication LLM (Qwen 7b)."

        print(f"[router] '{message[:50]}' → {decision['model']} ({decision['reasoning'][:60]})")
        self._log(message[:100], decision)
        return decision

    # ─────────────────────────────────────────────
    # MODEL EXECUTION
    # ─────────────────────────────────────────────

    def call_ollama(
        self,
        model_key: str,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        """
        Makes a direct Ollama API call to the correct instance for model_key.
        Returns the response text or an error string.
        """
        import urllib.request

        model_info = MODELS.get(model_key, MODELS["communication"])
        model_name = model_info["ollama_name"]
        # Use the model's own URL; fall back to /api/generate path
        base_url = model_info.get("ollama_url", "http://localhost:11434/api/chat")
        gen_url  = base_url.replace("/api/chat", "/api/generate")

        payload = {
            "model":      model_name,
            "prompt":     prompt,
            "stream":     False,
            "keep_alive": -1,
            "options":    {"num_ctx": 16384},
        }
        if system:
            payload["system"] = system

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                gen_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("response", "").strip()
        except Exception as e:
            return f"[ModelRouter error: {e}]"

    def get_embedding(self, text: str) -> list:
        """
        Get a vector embedding for the given text.
        Used for memory lookup before main LLM calls.
        Requires nomic-embed-text to be installed.
        """
        import urllib.request

        emb_info = MODELS["embeddings"]
        payload  = {"model": emb_info["ollama_name"], "prompt": text}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                emb_info["ollama_url"],
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("embedding", [])
        except Exception as e:
            print(f"[Embedding error: {e}]")
            return []

    # ─────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────

    def status(self) -> dict:
        """Returns current model availability status."""
        self._load_model_availability()  # Refresh
        return {
            "models": {
                key: {
                    "name": model["ollama_name"],
                    "available": self.available.get(key, False),
                    "description": model["description"],
                }
                for key, model in MODELS.items()
                if not model.get("embedding_only")
            },
            "embeddings_available": self.available.get("embeddings", False),
            "checked_at": datetime.datetime.now().isoformat(),
        }

    def install_instructions(self) -> str:
        """Returns install instructions for any missing models."""
        missing = []
        for key, model in MODELS.items():
            if not self.available.get(key, False):
                missing.append(f"  ollama pull {model['ollama_name']}")

        if not missing:
            return "All models installed."

        return (
            "Missing models — run these commands:\n\n"
            + "\n".join(missing)
            + "\n\nMake sure OLLAMA_MODELS=H:\\AI\\ollama\\models is set first "
            "so models download to H: drive."
        )

    # ─────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────

    def _log(self, message_preview: str, decision: dict):
        entry = {
            "ts": decision["timestamp"],
            "msg": message_preview,
            "routed_to": decision["model"],
            "intent": decision["intent"],
            "memory": decision["needs_memory_lookup"],
            "fallback": decision["fallback_used"],
            "reason": decision["reasoning"],
        }
        try:
            with open(ROUTER_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Log failure is non-fatal


# ─────────────────────────────────────────────
# MAIN — status check and test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    router = ModelRouter()

    print("=== MODEL ROUTER STATUS ===\n")
    status = router.status()
    for key, info in status["models"].items():
        installed = "✓" if info["available"] else "✗"
        print(f"  [{installed}] {key:14s} — {info['name']:25s} — {info['description']}")

    embedding_ok = "✓" if status["embeddings_available"] else "✗"
    print(f"  [{embedding_ok}] embeddings     — {MODELS['embeddings']['ollama_name']}\n")

    if not all(info["available"] for info in status["models"].values()):
        print(router.install_instructions())

    print("\n=== ROUTING TESTS ===\n")
    test_messages = [
        "hey, how are you doing today?",
        "can you write a Python function that scrapes a webpage?",
        "do you remember when we talked about my sister?",
        "what's on my screen right now?",
        "I need to debug this error: AttributeError: 'NoneType' object has no attribute 'get' "
        "which occurs on line 47 of my script when trying to parse the response",
        "I've been thinking a lot about what we talked about last week regarding my goals and "
        "career direction. I feel like I need to make some big decisions soon and I'm not sure "
        "which path makes the most sense. Can you help me think through this carefully? "
        "There are a lot of factors involved including my current job, my finances, and what "
        "I actually want long term.",
    ]

    for msg in test_messages:
        decision = router.route(msg)
        print(f'  "{msg[:65]}{"..." if len(msg) > 65 else ""}"')
        print(f'    → {decision["model"]:12s} | intent: {decision["intent"]:10s} | {decision["reasoning"][:70]}')
        print()