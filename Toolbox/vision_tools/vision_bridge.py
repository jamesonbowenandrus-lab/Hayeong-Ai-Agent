"""
vision_bridge.py
────────────────
Hayeong's conversational vision. Lets her look at James's screen or analyze
images during normal conversation — separate from ComfyUI image generation.

DESIGN PHILOSOPHY:
  - Vision output is context, not response. The description gets injected into
    Hayeong's conversation so she can reason about it naturally.
  - Two modes: fast (moondream — screen glances) and deep (llava:13b — detailed analysis).
  - Works entirely locally — no cloud, no API keys.
  - Fails gracefully if dependencies aren't installed.

CAPABILITIES:
  look_at_screen(question)        → moondream analyzes your screen (fast)
  look_at_screen_deep(question)   → llava:13b analyzes your screen (detailed)
  look_at_image(path, question)   → llava:13b analyzes an image file
  format_for_context(description) → wraps vision output for prompt injection

USAGE (from main.py):
  from vision_bridge import VisionBridge
  vision = VisionBridge()

  context = vision.look_at_screen("what is James working on?")
  system_prompt = context + "\\n\\n" + system_prompt
  # → Hayeong sees the description and responds naturally

TRIGGERS (intent detection):
  "look at my screen", "what's on my screen", "can you see my screen",
  "what is this", "look at this image", "describe what you see"

INSTALL:
  pip install Pillow   (already in requirements.txt)
"""

import os
import base64
import requests
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────
# DEPENDENCY CHECK
# ─────────────────────────────────────────────

def _check_pillow() -> bool:
    try:
        from PIL import ImageGrab  # noqa
        return True
    except ImportError:
        return False

PILLOW_AVAILABLE = _check_pillow()


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

OLLAMA_URL         = "http://localhost:11434/api/chat"
VISION_FAST        = "moondream:latest"   # Quick screen reads — very fast
VISION_DEEP        = "llava:13b"          # Detailed analysis — ~15s on 7900 XTX
BASE_DIR           = Path(__file__).parent
LOG_DIR            = BASE_DIR / "logs"
LOG_FILE           = LOG_DIR / "vision_bridge.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def _log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"[VisionBridge] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─────────────────────────────────────────────
# SCREENSHOT
# ─────────────────────────────────────────────

def _capture_screen() -> Optional[bytes]:
    """
    Take a screenshot. Returns PNG bytes or None.
    Resizes to 1280x720 to keep Ollama context manageable.
    """
    if not PILLOW_AVAILABLE:
        _log("Pillow not installed — cannot capture screen.")
        return None
    try:
        from PIL import ImageGrab, Image
        import io
        shot = ImageGrab.grab()
        shot.thumbnail((1280, 720), Image.LANCZOS)
        buf = io.BytesIO()
        shot.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        _log(f"Screenshot error: {e}")
        return None


def _save_screenshot_temp(png_bytes: bytes) -> Optional[str]:
    """Save screenshot bytes to a temp file, return path."""
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(png_bytes)
        tmp.close()
        return tmp.name
    except Exception as e:
        _log(f"Temp file error: {e}")
        return None


# ─────────────────────────────────────────────
# OLLAMA VISION CALL
# ─────────────────────────────────────────────

def _ask_vision(image_path: str, question: str, model: str) -> str:
    """
    Send an image to an Ollama vision model and get a description.
    Returns the description string, or an error message.
    """
    _log(f"Asking {model}: {question!r} → {image_path}")

    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        timeout = 90 if "llava" in model else 30

        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [{
                    "role":    "user",
                    "content": question,
                    "images":  [image_b64],
                }],
                "stream": False,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        description = resp.json()["message"]["content"].strip()
        _log(f"Vision result ({model}): {description[:120]}...")
        return description

    except requests.exceptions.ConnectionError:
        msg = "Ollama isn't reachable — make sure it's running."
        _log(msg)
        return f"(Vision unavailable: {msg})"
    except Exception as e:
        _log(f"Vision error ({model}): {e}")
        return f"(Vision analysis failed: {e})"


# ─────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────

class VisionBridge:
    """
    Hayeong's conversational vision interface.
    Create one instance at startup and share it.

    All methods return a context string — no synthesis here.
    Feed the result into the system_prompt for the turn so
    Hayeong can respond naturally about what she sees.
    """

    def __init__(self):
        if not PILLOW_AVAILABLE:
            print("⚠️  [VisionBridge] Pillow not installed — screen capture unavailable.")
            print("   Run: pip install Pillow")
        else:
            _log("VisionBridge ready.")

    def is_available(self) -> bool:
        return PILLOW_AVAILABLE

    # ─────────────────────────────────────────────
    # SCREEN VISION
    # ─────────────────────────────────────────────

    def look_at_screen(self, question: str = None) -> str:
        """
        Take a screenshot and analyze it with moondream (fast).
        Best for: quick glances, "what are you working on", status checks.

        Returns a description string for context injection.
        Returns an error message string if capture fails.
        """
        if not question:
            question = (
                "Briefly describe what's on this screen. "
                "What application is open? What is the user doing? "
                "Mention any notable text, code, or content visible."
            )

        png = _capture_screen()
        if png is None:
            return "[VISION: Screenshot failed — Pillow may not be installed correctly.]"

        path = _save_screenshot_temp(png)
        if not path:
            return "[VISION: Could not save screenshot to temp file.]"

        try:
            description = _ask_vision(path, question, VISION_FAST)
            return self.format_for_context(description, mode="screen", model=VISION_FAST)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def look_at_screen_deep(self, question: str = None) -> str:
        """
        Take a screenshot and analyze it with llava:13b (detailed, ~15s).
        Best for: "explain what's in this code", detailed UI analysis.

        Returns a description string for context injection.
        """
        if not question:
            question = (
                "Describe this screen in detail. What application is open? "
                "What content is visible? If there's code, describe what it does. "
                "If there's a UI, describe the layout and state. Be thorough."
            )

        png = _capture_screen()
        if png is None:
            return "[VISION: Screenshot failed — Pillow may not be installed correctly.]"

        path = _save_screenshot_temp(png)
        if not path:
            return "[VISION: Could not save screenshot to temp file.]"

        try:
            description = _ask_vision(path, question, VISION_DEEP)
            return self.format_for_context(description, mode="screen", model=VISION_DEEP)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # IMAGE FILE VISION
    # ─────────────────────────────────────────────

    def look_at_image(self, image_path: str, question: str = None) -> str:
        """
        Analyze an image file with llava:13b (detailed).
        Best for: reviewing generated images, analyzing uploaded files,
        discussing art or reference material.

        Returns a description string for context injection.
        """
        if not os.path.exists(image_path):
            return f"[VISION: Image not found at {image_path}]"

        if not question:
            question = (
                "Describe this image in detail. Focus on: what's depicted, "
                "colors, composition, style, any text visible, and overall quality. "
                "Be specific and thorough."
            )

        description = _ask_vision(image_path, question, VISION_DEEP)
        return self.format_for_context(description, mode="image",
                                       model=VISION_DEEP, source=image_path)

    # ─────────────────────────────────────────────
    # CONTEXT FORMATTER
    # Wraps vision output for injection into Hayeong's system prompt.
    # ─────────────────────────────────────────────

    @staticmethod
    def format_for_context(description: str, mode: str = "screen",
                           model: str = None, source: str = None) -> str:
        """
        Wrap a vision description as a context block for prompt injection.

        Usage in main.py:
            context = vision.look_at_screen(user_input)
            system_prompt = context + "\\n\\n" + system_prompt
        """
        if mode == "screen":
            header = "[VISION — SCREEN CAPTURE]"
            note   = "You can see James's screen. Respond naturally about what you observe."
        elif mode == "image":
            src    = f" ({source})" if source else ""
            header = f"[VISION — IMAGE{src}]"
            note   = "You have analyzed the image above. Respond naturally about what you see."
        else:
            header = "[VISION]"
            note   = "Respond naturally based on what you observed."

        model_note = f" via {model}" if model else ""

        return (
            f"{header}{model_note}\n"
            f"{description}\n\n"
            f"{note}"
        )


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("VisionBridge — Standalone Test")
    print("=" * 60)

    if not PILLOW_AVAILABLE:
        print("❌ Pillow not installed.")
        print("   Run: pip install Pillow")
        exit(1)

    vision = VisionBridge()

    print("\n📸 Taking a screenshot and analyzing with moondream (fast)...")
    result = vision.look_at_screen()
    print("\n── CONTEXT OUTPUT ──")
    print(result)

    choice = input("\nRun deep analysis with llava:13b? (takes ~15s) [y/N]: ").strip().lower()
    if choice == "y":
        print("\n📸 Running deep analysis...")
        result_deep = vision.look_at_screen_deep()
        print("\n── DEEP CONTEXT OUTPUT ──")
        print(result_deep)

    img_path = input("\nEnter an image path to analyze (or press Enter to skip): ").strip()
    if img_path and os.path.exists(img_path):
        print(f"\n🖼️ Analyzing: {img_path}")
        result_img = vision.look_at_image(img_path)
        print("\n── IMAGE CONTEXT OUTPUT ──")
        print(result_img)
    elif img_path:
        print(f"File not found: {img_path}")

    print("\n✅ Test complete.")
