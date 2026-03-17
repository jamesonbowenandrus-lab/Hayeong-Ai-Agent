# code_consultant.py
# Tiered code generation for Hayeong's self-modification pipeline.
#
# Hayeong uses this when a task requires new or modified code.
# She does not call it freestanding — it is always tied to a task.
#
# Tier system:
#   TIER 1 — deepseek-coder via Ollama (local, free, fast)
#             Used for: simple self-contained scripts, small modifications
#   TIER 2 — Claude API (cloud, costs ~$0.01-0.03/call, higher quality)
#             Used for: architectural changes, multi-file awareness, complex integrations
#
# The consultant decides which tier to use based on task complexity signals.
# Hayeong stays in charge of deciding WHAT to build — this is the contractor.
#
# Setup:
#   Tier 1: ollama pull deepseek-coder:6.7b   (minimum)
#           ollama pull deepseek-coder-v2:16b  (recommended — better quality)
#   Tier 2: set ANTHROPIC_API_KEY in .env

import os
import sys
import ast
import json
import datetime
import requests
import tempfile
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).parent

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

OLLAMA_URL     = "http://localhost:11434/api/chat"

# Tier 1 — local deepseek-coder models in preference order
# Will try each in order until one responds successfully.
TIER1_MODELS = [
    "deepseek-coder-v2:16b",   # best quality, needs ~10GB VRAM
    "deepseek-coder:33b",      # very good, needs ~20GB VRAM (fits your 7900 XTX)
    "deepseek-coder:6.7b",     # fallback, smaller
]

# Tier 2 — Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
CLAUDE_API_URL    = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Complexity thresholds for tier selection
TIER2_TRIGGERS = [
    "main.py",
    "self_mod_manager",
    "hayeong_architecture",
    "system_prompt_builder",
    "identity.json",
    "multiple files",
    "architectural",
    "refactor",
    "integration",
]

# Consultation log
CONSULT_LOG_PATH = BASE_DIR / "logs" / "code_consultations.log"
CONSULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# COMPLEXITY ASSESSMENT
# ─────────────────────────────────────────────

def assess_complexity(
    task_title: str,
    description: str,
    existing_code: str = None,
    related_files: list = None,
) -> tuple[int, str]:
    """
    Returns (tier, reason) where tier is 1 or 2.

    Tier 2 triggers:
    - Task or description references protected/core files
    - Multiple files need to be modified
    - Description suggests architectural work
    - existing_code is large (>200 lines)
    - ANTHROPIC_API_KEY is not set → forces tier 1
    """
    if not ANTHROPIC_API_KEY:
        return 1, "No ANTHROPIC_API_KEY set — using local model."

    text = (task_title + " " + description).lower()

    for trigger in TIER2_TRIGGERS:
        if trigger.lower() in text:
            return 2, f"Complexity trigger: '{trigger}'"

    if related_files and len(related_files) > 2:
        return 2, f"Multiple files involved: {related_files}"

    if existing_code and existing_code.count("\n") > 200:
        return 2, "Existing code is large — using higher-quality model."

    return 1, "Straightforward task — using local model."


# ─────────────────────────────────────────────
# PROMPT BUILDER
# Gives the model the context it needs to write
# code that actually fits Hayeong's architecture.
# ─────────────────────────────────────────────

def _build_prompt(
    task_title: str,
    description: str,
    existing_code: str = None,
    context_files: dict = None,
    output_filename: str = None,
) -> str:
    """
    Build a code generation prompt with architectural context.

    context_files: dict of {filename: content} for relevant existing files.
    """
    lines = [
        "You are writing Python code for Hayeong, an AI companion system.",
        "The code runs on Windows 11 with Python 3.12.",
        "Installed packages: py-cord, edge-tts, miniaudio, faster-whisper, pygame, ",
        "  numpy, sounddevice, scipy, requests, python-dotenv, chromadb, pynput.",
        "",
        "Architecture notes:",
        "  - main.py is the brain/supervisor — do not modify it directly",
        "  - New capabilities go in capabilities/scripts/generated/",
        "  - All new scripts should be self-contained with clear imports",
        "  - Use pathlib.Path for file paths, not os.path",
        "  - Logging via print() with emoji prefixes is the house style",
        "",
    ]

    if context_files:
        lines.append("RELEVANT EXISTING FILES:")
        for fname, content in context_files.items():
            lines.append(f"\n--- {fname} ---")
            # Truncate large files to keep prompt manageable
            if len(content) > 3000:
                lines.append(content[:3000] + "\n... [truncated]")
            else:
                lines.append(content)
        lines.append("")

    if existing_code:
        lines.append("EXISTING CODE TO MODIFY:")
        lines.append(existing_code)
        lines.append("")

    lines += [
        f"TASK: {task_title}",
        f"DESCRIPTION: {description}",
        "",
    ]

    if output_filename:
        lines.append(f"Write the complete contents of {output_filename}.")
    else:
        lines.append("Write the complete Python code for this task.")

    lines += [
        "Requirements:",
        "  - Complete, working code only. No placeholders or TODO comments.",
        "  - Include all necessary imports.",
        "  - Add a docstring at the top explaining what the file does.",
        "  - Output ONLY the Python code — no explanation, no markdown fences.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# TIER 1 — LOCAL DEEPSEEK-CODER
# ─────────────────────────────────────────────

def _consult_local(prompt: str) -> str | None:
    """Try each Tier 1 model in order. Returns code string or None."""
    for model in TIER1_MODELS:
        try:
            print(f"[CodeConsultant] Trying local model: {model}...")
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=120,
            )
            if response.status_code == 200:
                content = response.json()["message"]["content"].strip()
                print(f"[CodeConsultant] ✅ Got response from {model}")
                return content
        except requests.exceptions.ConnectionError:
            print(f"[CodeConsultant] Ollama not reachable — is it running?")
            return None
        except Exception as e:
            print(f"[CodeConsultant] {model} failed: {e}")
            continue

    print("[CodeConsultant] All local models failed.")
    return None


# ─────────────────────────────────────────────
# TIER 2 — CLAUDE API
# ─────────────────────────────────────────────

def _consult_claude(prompt: str) -> str | None:
    """Call Claude API for complex tasks. Returns code string or None."""
    if not ANTHROPIC_API_KEY:
        print("[CodeConsultant] No ANTHROPIC_API_KEY — cannot use Tier 2.")
        return None

    try:
        print(f"[CodeConsultant] Consulting Claude API ({CLAUDE_MODEL})...")
        headers = {
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type":      "application/json",
        }
        body = {
            "model":      CLAUDE_MODEL,
            "max_tokens": 4096,
            "messages":   [{"role": "user", "content": prompt}],
        }
        response = requests.post(CLAUDE_API_URL, headers=headers, json=body, timeout=60)

        if response.status_code == 200:
            content = response.json()["content"][0]["text"].strip()
            print("[CodeConsultant] ✅ Got response from Claude API")
            return content
        else:
            print(f"[CodeConsultant] Claude API error {response.status_code}: {response.text[:200]}")
            return None

    except Exception as e:
        print(f"[CodeConsultant] Claude API failed: {e}")
        return None


# ─────────────────────────────────────────────
# CODE SAFETY CHECK
# Basic validation before any generated code
# touches the filesystem.
# ─────────────────────────────────────────────

def _clean_code(raw: str) -> str:
    """Strip markdown fences if the model wrapped the code."""
    raw = raw.strip()
    if raw.startswith("```python"):
        raw = raw[9:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _syntax_check(code: str) -> tuple[bool, str]:
    """
    Parse the code with ast.parse to catch syntax errors.
    Returns (ok, error_message).
    """
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"


def _safety_check(code: str) -> tuple[bool, str]:
    """
    Basic safety checks — refuse code that does dangerous things.
    Returns (ok, reason_if_failed).

    This is not exhaustive — it's a first line of defense.
    James still reviews anything that goes into protected files.
    """
    dangerous = [
        ("os.system(",      "os.system call"),
        ("subprocess.call(","subprocess.call"),
        ("eval(",           "eval()"),
        ("exec(",           "exec()"),
        ("__import__(",     "__import__"),
        ("shutil.rmtree(",  "shutil.rmtree — recursive delete"),
        ("open(IDENTITY_FILE, 'w'", "direct write to identity.json"),
        ("open('identity.json', 'w'", "direct write to identity.json"),
    ]

    for pattern, label in dangerous:
        if pattern in code:
            return False, f"Refused: contains {label}"

    return True, ""


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def _log_consultation(
    task_title: str,
    tier: int,
    model: str,
    success: bool,
    error: str = None,
    output_filename: str = None,
):
    entry = {
        "timestamp":       datetime.datetime.now().isoformat(),
        "task":            task_title,
        "tier":            tier,
        "model":           model,
        "success":         success,
        "output_filename": output_filename,
        "error":           error,
    }
    try:
        with open(CONSULT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────
# MAIN INTERFACE
# ─────────────────────────────────────────────

class ConsultationResult:
    def __init__(
        self,
        code: str | None,
        tier: int,
        model: str,
        syntax_ok: bool,
        safety_ok: bool,
        error: str = None,
    ):
        self.code      = code
        self.tier      = tier
        self.model     = model
        self.syntax_ok = syntax_ok
        self.safety_ok = safety_ok
        self.error     = error
        self.ok        = code is not None and syntax_ok and safety_ok

    def __repr__(self):
        status = "✅ OK" if self.ok else f"❌ {self.error}"
        return f"ConsultationResult(tier={self.tier}, model={self.model}, {status})"


def consult(
    task_title: str,
    description: str,
    existing_code: str = None,
    context_files: dict = None,
    related_files: list = None,
    output_filename: str = None,
    force_tier: int = None,
) -> ConsultationResult:
    """
    Generate code for a task.

    task_title:      Short name of the task (from task_manager).
    description:     What the code needs to do.
    existing_code:   Current version of the file being modified, if any.
    context_files:   Dict of {filename: content} for relevant existing files.
    related_files:   List of filenames being touched (used for tier selection).
    output_filename: What the output file will be named (helps the model).
    force_tier:      1 or 2 to override automatic tier selection.

    Returns ConsultationResult.
    """
    # Determine tier
    if force_tier in (1, 2):
        tier, tier_reason = force_tier, "forced"
    else:
        tier, tier_reason = assess_complexity(
            task_title, description, existing_code, related_files
        )

    print(f"[CodeConsultant] Task: {task_title!r}")
    print(f"[CodeConsultant] Tier {tier} — {tier_reason}")

    # Build prompt
    prompt = _build_prompt(
        task_title     = task_title,
        description    = description,
        existing_code  = existing_code,
        context_files  = context_files,
        output_filename = output_filename,
    )

    # Call the appropriate tier
    raw_code = None
    model_used = "unknown"

    if tier == 2:
        raw_code   = _consult_claude(prompt)
        model_used = CLAUDE_MODEL
        if raw_code is None:
            print("[CodeConsultant] Claude unavailable — falling back to Tier 1.")
            tier     = 1
            raw_code = _consult_local(prompt)
            for m in TIER1_MODELS:
                model_used = m
                break
    else:
        raw_code = _consult_local(prompt)
        for m in TIER1_MODELS:
            model_used = m
            break

    if raw_code is None:
        result = ConsultationResult(
            code=None, tier=tier, model=model_used,
            syntax_ok=False, safety_ok=False,
            error="No model returned a response."
        )
        _log_consultation(task_title, tier, model_used, False, result.error, output_filename)
        return result

    # Clean and validate
    code      = _clean_code(raw_code)
    syn_ok, syn_err  = _syntax_check(code)
    safe_ok, safe_err = _safety_check(code)

    error = syn_err or safe_err or None

    if not syn_ok:
        print(f"[CodeConsultant] ⚠️  Syntax error: {syn_err}")
    if not safe_ok:
        print(f"[CodeConsultant] 🚫 Safety check failed: {safe_err}")

    result = ConsultationResult(
        code      = code if (syn_ok and safe_ok) else None,
        tier      = tier,
        model     = model_used,
        syntax_ok = syn_ok,
        safety_ok = safe_ok,
        error     = error,
    )

    _log_consultation(task_title, tier, model_used, result.ok, error, output_filename)

    if result.ok:
        print(f"[CodeConsultant] ✅ Code ready ({len(code)} chars, {code.count(chr(10))} lines)")
    else:
        print(f"[CodeConsultant] ❌ Code generation failed: {error}")

    return result


# ─────────────────────────────────────────────
# CONVENIENCE — load context files for common tasks
# ─────────────────────────────────────────────

def load_context(filenames: list) -> dict:
    """
    Load file contents for use as context_files in consult().
    Skips files that don't exist or are too large.
    """
    context = {}
    MAX_SIZE = 8000  # chars

    for fname in filenames:
        path = BASE_DIR / fname
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                if len(content) <= MAX_SIZE:
                    context[fname] = content
                else:
                    # Include just the first part — structure + imports
                    context[fname] = content[:MAX_SIZE] + "\n... [truncated]"
            except Exception:
                pass

    return context


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=== CODE CONSULTANT TEST ===\n")

    # Test tier assessment
    tier, reason = assess_complexity(
        "Write a weather checker script",
        "Fetch current weather for a city and return a summary string."
    )
    print(f"Simple task → Tier {tier}: {reason}")

    tier, reason = assess_complexity(
        "Modify main.py to add task surfacing",
        "Update the main loop in main.py to show active tasks at startup."
    )
    print(f"Complex task → Tier {tier}: {reason}")

    # Test syntax check
    good_code = "def hello():\n    return 'hi'\n"
    bad_code  = "def hello(\n    return 'hi'\n"

    ok, err = _syntax_check(good_code)
    print(f"\nSyntax check good code: {ok}")
    ok, err = _syntax_check(bad_code)
    print(f"Syntax check bad code: {ok} — {err}")

    # Test safety check
    dangerous_code = "import os\nos.system('rm -rf /')\n"
    ok, err = _safety_check(dangerous_code)
    print(f"Safety check dangerous code: {ok} — {err}")

    safe_code = "def greet(name):\n    return f'Hello {name}'\n"
    ok, err = _safety_check(safe_code)
    print(f"Safety check safe code: {ok}")

    # Live generation test (needs Ollama running)
    print("\n--- Live generation test (requires Ollama + deepseek-coder) ---")
    print("Skipping unless you run: python code_consultant.py --live\n")

    if "--live" in sys.argv:
        result = consult(
            task_title  = "Test: simple greeting function",
            description = "Write a Python function called greet(name: str) -> str that returns a warm greeting. Include a short docstring.",
            output_filename = "test_greet.py",
        )
        print(f"\nResult: {result}")
        if result.ok:
            print("\nGenerated code:")
            print("─" * 40)
            print(result.code)
