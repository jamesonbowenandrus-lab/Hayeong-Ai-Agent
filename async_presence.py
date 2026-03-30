# async_presence.py
# Hayeong's async presence layer.
#
# THE PROBLEM THIS SOLVES:
#   In the synchronous loop, Hayeong blocks completely during any slow operation.
#   Web search, F5-TTS generation, LLM inference, image gen — she goes silent.
#   You can't reach her mid-task. She doesn't feel present. She feels like a tool.
#
# WHAT THIS BUILDS:
#   A two-layer architecture:
#
#   Layer 1 — Presence layer (always fast, always listening)
#     Receives incoming messages instantly.
#     Emits an immediate acknowledgment so you know she heard you.
#     Dispatches actual work to the task queue.
#     Never blocks. Never freezes. Always responsive.
#
#   Layer 2 — Task queue (slow work runs here, out of the way)
#     Processes one task at a time (GPU can't parallelize inference anyway).
#     Delivers results back to the presence layer when done.
#     If a new message arrives while a task is running, it queues cleanly.
#     Contextual awareness is fully preserved — memory/mood update normally.
#
#   The result:
#     You speak → she acknowledges immediately → task runs in background
#     → she delivers the result naturally when it's ready.
#
# CONTEXTUAL AWARENESS:
#   Fully preserved. Every message and response still goes into memory.
#   The system prompt is still built the same way each turn.
#   Async doesn't change what she remembers — only when she responds.
#   Memory is locked during writes to prevent race conditions.
#
# USAGE (from main.py or voice_server.py):
#   from async_presence import PresenceLayer
#
#   def on_result(text, emotion, audio=None):
#       # called when Hayeong's full response is ready
#       speak(text, emotion)
#
#   presence = PresenceLayer(on_result=on_result)
#   presence.start()
#   presence.submit("hey, can you look something up for me")

import threading
import queue
import time
import random
import logging
from typing import Callable, Optional

log = logging.getLogger("async_presence")

# ─────────────────────────────────────────────
# IMMEDIATE ACKNOWLEDGMENTS
# Short, in-character. She heard you. She's on it.
# Chosen randomly so they don't feel like a canned response.
# Never more than 3 words. Never announcing what she's doing.
# ─────────────────────────────────────────────

_ACK_GENERIC = [
    "Yeah.",
    "On it.",
    "Give me a second.",
    "Got it.",
    "Hold on.",
    "One sec.",
    "Mm.",
]

_ACK_SEARCH = [
    "Let me look that up.",
    "Pulling that up.",
    "One second.",
    "On it.",
]

_ACK_VISION = [
    "Let me take a look.",
    "Looking now.",
    "One sec.",
]

_ACK_TASK = [
    "On it.",
    "Got it.",
    "Sure.",
]

_ACK_INTERRUPT = [
    "Still working on it.",
    "Almost done.",
    "Give me one more second.",
    "Just finishing up.",
]

def _pick_ack(intent: str = "generic") -> str:
    if intent == "search":
        return random.choice(_ACK_SEARCH)
    elif intent == "vision":
        return random.choice(_ACK_VISION)
    elif intent == "task":
        return random.choice(_ACK_TASK)
    elif intent == "interrupt":
        return random.choice(_ACK_INTERRUPT)
    return random.choice(_ACK_GENERIC)


# ─────────────────────────────────────────────
# TASK — one unit of work
# ─────────────────────────────────────────────

class Task:
    def __init__(self, user_input: str, intent: str = "generic",
                 context: Optional[dict] = None):
        self.user_input  = user_input
        self.intent      = intent          # "generic", "search", "vision", "task", etc.
        self.context     = context or {}   # any extra context the caller wants to pass
        self.submitted   = time.time()
        self.started     = None
        self.completed   = None

    def age(self) -> float:
        return time.time() - self.submitted


# ─────────────────────────────────────────────
# PRESENCE LAYER
# ─────────────────────────────────────────────

class PresenceLayer:
    """
    Two-layer async presence for Hayeong.

    Submit a message → immediate ack fires → task queues → result delivered via callback.
    All of this happens without blocking the caller.

    Parameters
    ----------
    on_ack : callable(text: str)
        Called immediately when a message is received.
        Use this to speak/print the acknowledgment.

    on_result : callable(text: str, emotion: str)
        Called when Hayeong's full response is ready.
        Use this to speak/print/send the actual response.

    on_busy_ack : callable(text: str) | None
        Called when a message arrives while a task is running.
        Defaults to on_ack if not provided.

    process_fn : callable(task: Task) -> tuple[str, str]
        The actual AI processing function.
        Should return (response_text, emotion_key).
        This is what runs in the background thread.
        Plug your existing main.py pipeline in here.
    """

    def __init__(
        self,
        on_ack:      Callable[[str], None],
        on_result:   Callable[[str, str], None],
        process_fn:  Callable[["Task"], tuple],
        on_busy_ack: Optional[Callable[[str], None]] = None,
    ):
        self.on_ack      = on_ack
        self.on_result   = on_result
        self.on_busy_ack = on_busy_ack or on_ack
        self.process_fn  = process_fn

        self._task_queue  = queue.Queue()
        self._worker      = None
        self._running     = False
        self._busy        = False          # True while a task is being processed
        self._memory_lock = threading.Lock()
        self._current_task: Optional[Task] = None

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def start(self):
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._worker  = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        log.info("Presence layer started")

    def stop(self):
        """Gracefully shut down the worker."""
        self._running = False
        self._task_queue.put(None)  # sentinel to unblock the worker
        if self._worker:
            self._worker.join(timeout=5)
        log.info("Presence layer stopped")

    def submit(self, user_input: str, intent: str = "generic",
               context: Optional[dict] = None):
        """
        Submit a message for processing.

        Immediately fires an acknowledgment (via on_ack or on_busy_ack),
        then queues the actual work for background processing.

        This returns immediately. The caller is never blocked.
        """
        if not user_input or not user_input.strip():
            return

        task = Task(user_input=user_input, intent=intent, context=context or {})

        # Immediate acknowledgment — fires before anything else
        if self._busy:
            ack = _pick_ack("interrupt")
            self.on_busy_ack(ack)
        else:
            ack = _pick_ack(intent)
            self.on_ack(ack)

        self._task_queue.put(task)
        log.debug(f"Task queued: {user_input[:60]!r} (intent={intent})")

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def queue_depth(self) -> int:
        return self._task_queue.qsize()

    def memory_lock(self):
        """
        Context manager for safe memory writes.
        Use this when updating shared memory from outside the worker.
        """
        return self._memory_lock

    # ─────────────────────────────────────────
    # WORKER LOOP
    # Runs in a background thread.
    # Processes one task at a time.
    # ─────────────────────────────────────────

    def _worker_loop(self):
        log.info("Worker thread running")
        while self._running:
            try:
                task = self._task_queue.get(timeout=1)
            except queue.Empty:
                continue

            if task is None:
                break  # sentinel — shut down

            self._busy        = True
            self._current_task = task
            task.started       = time.time()

            log.debug(f"Processing: {task.user_input[:60]!r}")

            try:
                result = self.process_fn(task)

                # process_fn should return (text, emotion)
                if isinstance(result, tuple) and len(result) >= 2:
                    text, emotion = result[0], result[1]
                elif isinstance(result, str):
                    text, emotion = result, "neutral"
                else:
                    text, emotion = str(result), "neutral"

                task.completed = time.time()
                elapsed = round(task.completed - task.started, 2)
                log.debug(f"Task done in {elapsed}s: {text[:60]!r}")

                # Deliver result via callback
                # This runs in the worker thread — on_result should be thread-safe
                self.on_result(text, emotion)

            except Exception as e:
                log.error(f"Task processing error: {e}")
                self.on_result("Something went wrong on my end.", "neutral")

            finally:
                self._busy         = False
                self._current_task = None
                self._task_queue.task_done()

        log.info("Worker thread stopped")


# ─────────────────────────────────────────────
# INTENT DETECTOR
# Quick pre-LLM classification of what kind of
# task is coming in, so the right ack fires.
# Fast keyword match — not an LLM call.
# ─────────────────────────────────────────────

_SEARCH_SIGNALS  = [
    "look up", "search", "find", "what is", "who is", "how does",
    "latest", "news", "price", "compare", "tell me about",
    "what's", "whats", "can you find", "research"
]
_VISION_SIGNALS  = [
    "look at", "what do you see", "can you see", "look at my screen",
    "what's on my screen", "look at this", "analyze this"
]
_TASK_SIGNALS    = [
    "add a task", "add task", "remember to", "i need to",
    "put on my list", "show tasks", "show my tasks",
    "what are you working on"
]

def detect_intent(text: str) -> str:
    """
    Quick intent classification for presence layer ack selection.
    Returns one of: "search", "vision", "task", "generic"
    """
    t = text.lower().strip()
    if any(s in t for s in _VISION_SIGNALS):
        return "vision"
    if any(s in t for s in _SEARCH_SIGNALS):
        return "search"
    if any(s in t for s in _TASK_SIGNALS):
        return "task"
    return "generic"


# ─────────────────────────────────────────────
# INTEGRATION HELPERS
# Convenience wrappers for plugging into
# main.py and voice_server.py
# ─────────────────────────────────────────────

def build_process_fn(
    chat_fn,
    build_prompt_fn,
    load_memory_fn,
    save_memory_fn,
    load_mood_fn,
    save_json_fn,
    load_identity_fn,
    adjust_mood_fn,
    mood_file: str,
    dynamic_traits: dict,
    memory_lock: threading.Lock,
):
    """
    Factory that returns a process_fn compatible with PresenceLayer.

    Wraps the existing main.py pipeline so it can run in a background thread.
    Memory is protected by memory_lock — safe for concurrent reads from main loop.

    Returns: callable(task: Task) -> tuple[str, str]
    """
    # These are loaded fresh per-call so they stay in sync with file state
    def process(task: Task) -> tuple:
        with memory_lock:
            memory     = load_memory_fn()
            mood_state = load_mood_fn()
            identity   = load_identity_fn()

        user_input = task.user_input
        adjust_mood_fn(user_input, mood_state)

        prompt   = build_prompt_fn(identity, memory, user_input, dynamic_traits, mood_state)
        response = chat_fn(prompt)
        emotion  = "neutral"  # future: extract from response metadata

        with memory_lock:
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI",   "content": response})
            save_memory_fn(memory)
            save_json_fn(mood_file, mood_state)

        return response, emotion

    return process
