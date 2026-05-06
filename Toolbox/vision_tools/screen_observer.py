"""
SCREEN OBSERVER
Hayeong observes James's screen to learn from how he works.

Not passive capture — active understanding.
Teaching mode: James narrates, Hayeong builds structured knowledge.
Privacy controls: app blacklist, private mode, local storage only.

Usage:
    observer = ScreenObserver()
    observer.start()                    # Begin passive observation
    observer.start_teaching("blender") # Start teaching mode for a task
    observer.stop_teaching()           # End session, save knowledge
    observer.private_mode_on()         # Pause everything
"""

import os
import re
import json
import time
import base64
import datetime
import threading
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
OBSERVER_DIR    = BASE_DIR / "screen_observer_data"
CAPTURES_DIR    = OBSERVER_DIR / "captures"
LEARNED_DIR     = BASE_DIR / "capabilities" / "learned"
OBSERVER_LOG    = BASE_DIR / "logs" / "screen_observer.log"
PRIVACY_FILE    = BASE_DIR / "privacy_registry.json"

for d in [OBSERVER_DIR, CAPTURES_DIR, LEARNED_DIR, BASE_DIR / "logs"]:
    d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# DEFAULT PRIVACY BLACKLIST
# Apps/window titles she never captures.
# Add to this list freely — it only grows.
# ─────────────────────────────────────────────

DEFAULT_APP_BLACKLIST = {
    # Financial
    "chase", "paypal", "venmo", "robinhood", "coinbase", "bank",
    "mint", "turbotax", "quicken",
    # Passwords / security
    "lastpass", "1password", "bitwarden", "keepass", "dashlane",
    "keychain", "credential", "password",
    # Private browsing
    "private", "incognito",
    # Personal/medical
    "medical", "hospital", "pharmacy", "health",
    # Communication (personal)
    "tinder", "bumble", "hinge",
}

CAPTURE_INTERVAL_SECONDS = 30      # Passive: capture every 30s
TEACHING_INTERVAL_SECONDS = 10     # Teaching mode: capture every 10s


# ─────────────────────────────────────────────
# DEPENDENCY CHECK
# ─────────────────────────────────────────────

def _check_dependencies() -> dict:
    """Check which optional screen capture libraries are available."""
    deps = {}
    try:
        import PIL.ImageGrab
        deps["pillow"] = True
    except ImportError:
        deps["pillow"] = False

    try:
        import pygetwindow
        deps["pygetwindow"] = True
    except ImportError:
        deps["pygetwindow"] = False

    return deps


DEPS = _check_dependencies()


def _install_hint() -> str:
    missing = []
    if not DEPS["pillow"]:
        missing.append("pip install Pillow")
    if not DEPS["pygetwindow"]:
        missing.append("pip install pygetwindow")
    if missing:
        return "Install missing dependencies:\n  " + "\n  ".join(missing)
    return "All dependencies installed."


# ─────────────────────────────────────────────
# SCREEN CAPTURE
# ─────────────────────────────────────────────

def capture_screen() -> Optional[bytes]:
    """
    Captures a screenshot of the primary monitor.
    Returns PNG bytes, or None if capture is not available.
    Requires: pip install Pillow
    """
    if not DEPS["pillow"]:
        print(f"[ScreenObserver] Pillow not installed. {_install_hint()}")
        return None

    try:
        from PIL import ImageGrab, Image
        import io
        screenshot = ImageGrab.grab()
        # Resize to reduce storage / LLM context usage
        screenshot.thumbnail((1280, 720), Image.LANCZOS)
        buffer = io.BytesIO()
        screenshot.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except Exception as e:
        print(f"[ScreenObserver] Capture error: {e}")
        return None


def get_active_window_title() -> str:
    """Returns the title of the currently active window, or empty string."""
    if not DEPS["pygetwindow"]:
        return ""
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        return win.title if win else ""
    except Exception:
        return ""


# ─────────────────────────────────────────────
# PRIVACY GUARD
# ─────────────────────────────────────────────

class PrivacyGuard:
    """Enforces the app blacklist and private mode."""

    def __init__(self):
        self.blacklist = set(DEFAULT_APP_BLACKLIST)
        self._private_mode = False
        self._load_custom_blacklist()

    def _load_custom_blacklist(self):
        """Load any user-added blacklist entries from privacy_registry.json."""
        if PRIVACY_FILE.exists():
            try:
                with open(PRIVACY_FILE, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                custom = registry.get("screen_observer_blacklist", [])
                self.blacklist.update(w.lower() for w in custom)
            except Exception:
                pass

    def is_blocked(self, window_title: str) -> bool:
        """Returns True if this window title should not be captured."""
        if self._private_mode:
            return True
        title_lower = window_title.lower()
        return any(term in title_lower for term in self.blacklist)

    def set_private_mode(self, on: bool):
        self._private_mode = on
        status = "ON — all observation paused" if on else "OFF — observation resumed"
        print(f"[ScreenObserver] Private mode {status}")

    @property
    def private_mode(self) -> bool:
        return self._private_mode

    def add_to_blacklist(self, term: str):
        """Add a term to the capture blacklist."""
        self.blacklist.add(term.lower())
        # Persist to privacy_registry.json
        if PRIVACY_FILE.exists():
            try:
                with open(PRIVACY_FILE, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                registry.setdefault("screen_observer_blacklist", [])
                if term not in registry["screen_observer_blacklist"]:
                    registry["screen_observer_blacklist"].append(term)
                with open(PRIVACY_FILE, "w", encoding="utf-8") as f:
                    json.dump(registry, f, indent=2)
            except Exception:
                pass
        print(f"[ScreenObserver] Added '{term}' to capture blacklist.")


# ─────────────────────────────────────────────
# VISION ANALYSIS
# Calls the vision model (when available) to understand what's on screen.
# Falls back to window title analysis when vision model not installed.
# ─────────────────────────────────────────────

def analyze_screen(image_bytes: bytes, window_title: str, narration: str = "") -> dict:
    """
    Analyzes a screenshot using the vision model (llava or similar via Ollama).
    Falls back to title-based heuristic if vision model not available.

    Returns:
    {
        "app": str,           — detected application
        "task": str,          — what James appears to be doing
        "description": str,   — brief description of screen content
        "method": str,        — "vision_model" | "heuristic"
        "narration": str,     — any narration provided by James
    }
    """
    # Try vision model first
    vision_result = _try_vision_model(image_bytes, window_title, narration)
    if vision_result:
        return vision_result

    # Fall back to window title heuristic
    return _heuristic_analysis(window_title, narration)


def _try_vision_model(image_bytes: bytes, window_title: str, narration: str) -> Optional[dict]:
    """Attempt analysis via Ollama vision model (llava:13b or similar)."""
    import urllib.request

    prompt = (
        f"The active window is: '{window_title}'.\n"
        f"{'Narration from James: ' + narration if narration else ''}\n\n"
        "Describe in 2-3 sentences: (1) what application this is, "
        "(2) what task the user appears to be doing, "
        "(3) any notable UI state or content visible. "
        "Be concise and specific."
    )

    img_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": "llava:13b",
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            text = result.get("response", "").strip()
            if text:
                return {
                    "app": window_title.split(" - ")[-1] if " - " in window_title else window_title,
                    "task": text[:200],
                    "description": text,
                    "method": "vision_model",
                    "narration": narration,
                }
    except Exception:
        pass  # Vision model not available — fall through
    return None


def _heuristic_analysis(window_title: str, narration: str) -> dict:
    """Title-based heuristic when no vision model is available."""
    title_lower = window_title.lower()

    # App detection
    app_patterns = {
        "Visual Studio Code": ["visual studio code", "vscode"],
        "Blender": ["blender"],
        "Minecraft": ["minecraft"],
        "Chrome": ["chrome", "google chrome"],
        "Firefox": ["firefox"],
        "Discord": ["discord"],
        "Photoshop": ["photoshop"],
        "Terminal": ["terminal", "cmd", "powershell", "bash"],
        "Explorer": ["file explorer", "windows explorer"],
        "Excel": ["excel"],
        "Word": ["word"],
        "Notepad": ["notepad"],
    }

    detected_app = "Unknown"
    for app, patterns in app_patterns.items():
        if any(p in title_lower for p in patterns):
            detected_app = app
            break

    task_hint = narration if narration else f"Working in {detected_app}"
    return {
        "app": detected_app,
        "task": task_hint,
        "description": f"Window: {window_title} | {task_hint}",
        "method": "heuristic",
        "narration": narration,
    }


# ─────────────────────────────────────────────
# TEACHING MODE — KNOWLEDGE CAPTURE
# ─────────────────────────────────────────────

class TeachingSession:
    """
    Manages a teaching mode session.
    James narrates steps, Hayeong captures and structures the knowledge.
    """

    def __init__(self, task_name: str):
        self.task_name = re.sub(r"[^\w\s-]", "", task_name).strip().replace(" ", "_").lower()
        self.started_at = datetime.datetime.now().isoformat()
        self.steps = []
        self.questions_asked = []
        self.active = True

        self.save_path = LEARNED_DIR / f"{self.task_name}.json"
        print(f"\n[TeachingMode] Session started: '{task_name}'")
        print("[TeachingMode] I'm watching and listening. Narrate as you go.")
        print("[TeachingMode] Say 'Teaching mode off' or call stop_teaching() when done.\n")

    def add_step(
        self,
        description: str,
        screen_analysis: dict,
        step_number: Optional[int] = None,
    ):
        """Add a documented step to this teaching session."""
        step = {
            "step": step_number or len(self.steps) + 1,
            "timestamp": datetime.datetime.now().isoformat(),
            "narration": description,
            "app": screen_analysis.get("app", "Unknown"),
            "observed_task": screen_analysis.get("task", ""),
            "method": screen_analysis.get("method", "heuristic"),
        }
        self.steps.append(step)
        print(f"[TeachingMode] Step {step['step']} captured: {description[:60]}")
        return step

    def add_question(self, question: str):
        """Log a clarifying question Hayeong asked during teaching."""
        self.questions_asked.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "question": question,
        })

    def save(self) -> dict:
        """Save the teaching session as a structured knowledge file."""
        knowledge = {
            "task_name": self.task_name,
            "taught_by": "james",
            "session_started": self.started_at,
            "session_ended": datetime.datetime.now().isoformat(),
            "step_count": len(self.steps),
            "steps": self.steps,
            "questions_asked": self.questions_asked,
            "summary": self._generate_summary(),
            "version": 1,
        }

        # If file exists, merge / increment version
        if self.save_path.exists():
            with open(self.save_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            knowledge["version"] = existing.get("version", 1) + 1
            knowledge["previous_sessions"] = existing.get("previous_sessions", [])
            knowledge["previous_sessions"].append({
                "version": existing["version"],
                "date": existing["session_started"],
                "step_count": existing["step_count"],
            })

        with open(self.save_path, "w", encoding="utf-8") as f:
            json.dump(knowledge, f, indent=2, ensure_ascii=False)

        print(f"\n[TeachingMode] Session saved: {self.save_path}")
        print(f"[TeachingMode] {len(self.steps)} steps documented for '{self.task_name}'")
        return knowledge

    def _generate_summary(self) -> str:
        if not self.steps:
            return "No steps captured."
        apps = set(s["app"] for s in self.steps)
        return (
            f"{len(self.steps)}-step workflow in {', '.join(apps)}. "
            f"First step: {self.steps[0]['narration'][:80]}. "
            f"Last step: {self.steps[-1]['narration'][:80]}."
        )


# ─────────────────────────────────────────────
# MAIN SCREEN OBSERVER CLASS
# ─────────────────────────────────────────────

class ScreenObserver:
    """
    Main observer class. Manages passive observation and teaching sessions.
    """

    def __init__(self):
        self.privacy = PrivacyGuard()
        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._teaching_session: Optional[TeachingSession] = None
        self._capture_history = []
        self._MAX_HISTORY = 20

    # ─────────────────────────────────────────────
    # PASSIVE OBSERVATION
    # ─────────────────────────────────────────────

    def start(self):
        """Start passive screen observation in a background thread."""
        if not DEPS["pillow"]:
            print(f"[ScreenObserver] Cannot start — {_install_hint()}")
            return

        self._active = True
        self._thread = threading.Thread(target=self._observe_loop, daemon=True)
        self._thread.start()
        print("[ScreenObserver] Passive observation started.")

    def stop(self):
        """Stop passive observation."""
        self._active = False
        print("[ScreenObserver] Observation stopped.")

    def _observe_loop(self):
        """Background loop: capture → analyze → log, respecting privacy guard."""
        while self._active:
            try:
                window_title = get_active_window_title()

                if not self.privacy.is_blocked(window_title):
                    image_bytes = capture_screen()
                    if image_bytes:
                        analysis = analyze_screen(image_bytes, window_title)
                        self._record_capture(analysis, image_bytes)

                interval = (
                    TEACHING_INTERVAL_SECONDS
                    if self._teaching_session and self._teaching_session.active
                    else CAPTURE_INTERVAL_SECONDS
                )
                time.sleep(interval)

            except Exception as e:
                self._log_error(str(e))
                time.sleep(CAPTURE_INTERVAL_SECONDS)

    def _record_capture(self, analysis: dict, image_bytes: bytes):
        """Store the capture in memory and log it."""
        ts = datetime.datetime.now().isoformat()

        entry = {
            "timestamp": ts,
            "app": analysis["app"],
            "task": analysis["task"],
            "method": analysis["method"],
        }

        self._capture_history.append(entry)
        if len(self._capture_history) > self._MAX_HISTORY:
            self._capture_history.pop(0)

        # Save PNG to captures dir (rolling — keeps last 50)
        saves = sorted(CAPTURES_DIR.glob("*.png"))
        while len(saves) >= 50:
            saves[0].unlink()
            saves = saves[1:]

        safe_ts = ts.replace(":", "-").replace(".", "-")
        img_path = CAPTURES_DIR / f"capture_{safe_ts}.png"
        with open(img_path, "wb") as f:
            f.write(image_bytes)

        self._log_capture(entry)

    # ─────────────────────────────────────────────
    # TEACHING MODE
    # ─────────────────────────────────────────────

    def start_teaching(self, task_name: str):
        """Begin a teaching session for a named task."""
        if self._teaching_session and self._teaching_session.active:
            print("[ScreenObserver] A teaching session is already active. Stop it first.")
            return

        if not self._active:
            self.start()

        self._teaching_session = TeachingSession(task_name)

    def narrate(self, step_description: str):
        """
        James narrates a step during teaching mode.
        Captures the current screen state and logs it with the narration.
        """
        if not self._teaching_session or not self._teaching_session.active:
            print("[ScreenObserver] No active teaching session. Call start_teaching() first.")
            return

        window_title = get_active_window_title()
        analysis = {"app": "Unknown", "task": step_description, "method": "narration"}

        if not self.privacy.is_blocked(window_title):
            image_bytes = capture_screen()
            if image_bytes:
                analysis = analyze_screen(image_bytes, window_title, narration=step_description)

        self._teaching_session.add_step(step_description, analysis)

    def ask_clarification(self, question: str):
        """
        Hayeong asks a clarifying question during teaching.
        Logs the question for the knowledge file.
        """
        if self._teaching_session:
            self._teaching_session.add_question(question)
            print(f"[Hayeong] {question}")

    def stop_teaching(self) -> Optional[dict]:
        """End the teaching session and save the knowledge."""
        if not self._teaching_session:
            print("[ScreenObserver] No active teaching session.")
            return None

        self._teaching_session.active = False
        knowledge = self._teaching_session.save()
        self._teaching_session = None
        return knowledge

    # ─────────────────────────────────────────────
    # PRIVACY CONTROLS
    # ─────────────────────────────────────────────

    def private_mode_on(self):
        """Pause all observation immediately."""
        self.privacy.set_private_mode(True)

    def private_mode_off(self):
        """Resume observation."""
        self.privacy.set_private_mode(False)

    def block_app(self, term: str):
        """Add an app name or window title keyword to the permanent blacklist."""
        self.privacy.add_to_blacklist(term)

    # ─────────────────────────────────────────────
    # STATUS & INSPECTION
    # ─────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "active": self._active,
            "private_mode": self.privacy.private_mode,
            "teaching_session": self._teaching_session.task_name if self._teaching_session else None,
            "captures_in_memory": len(self._capture_history),
            "learned_tasks": self.list_learned_tasks(),
            "dependencies": DEPS,
            "install_hint": _install_hint() if not all(DEPS.values()) else "All deps OK",
        }

    def list_learned_tasks(self) -> list:
        """Returns a list of all saved knowledge files."""
        return [f.stem for f in LEARNED_DIR.glob("*.json")]

    def get_learned_task(self, task_name: str) -> Optional[dict]:
        """Load a saved knowledge file by task name."""
        path = LEARNED_DIR / f"{task_name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def recent_activity(self, n: int = 5) -> list:
        """Returns the last n captures from memory."""
        return self._capture_history[-n:]

    # ─────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────

    def _log_capture(self, entry: dict):
        try:
            with open(OBSERVER_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def _log_error(self, error: str):
        entry = {"timestamp": datetime.datetime.now().isoformat(), "error": error}
        try:
            with open(OBSERVER_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass


# ─────────────────────────────────────────────
# MAIN — status check
# ─────────────────────────────────────────────

if __name__ == "__main__":
    observer = ScreenObserver()

    print("=== SCREEN OBSERVER STATUS ===\n")
    status = observer.status()

    for key, val in status.items():
        print(f"  {key}: {val}")

    print("\n=== DEPENDENCY STATUS ===")
    print(_install_hint())

    print("\n=== LEARNED TASKS ===")
    tasks = observer.list_learned_tasks()
    if tasks:
        for t in tasks:
            print(f"  - {t}")
    else:
        print("  None yet — teach Hayeong something with start_teaching()")

    print("\n=== USAGE EXAMPLE ===")
    print("""
  observer = ScreenObserver()
  observer.start()                          # Passive observation on

  observer.start_teaching("build in blender")
  observer.narrate("Opening Blender, starting a new project")
  observer.narrate("Adding a cube with Shift+A → Mesh → Cube")
  observer.ask_clarification("Are you using the metric or imperial units?")
  observer.narrate("Scaling the cube to 2x on the X axis with S → X → 2")
  knowledge = observer.stop_teaching()     # Save session

  observer.private_mode_on()               # Pause everything
  observer.private_mode_off()              # Resume

  observer.block_app("my bank app")        # Never capture this
""")
