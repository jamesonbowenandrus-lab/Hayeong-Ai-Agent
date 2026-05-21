"""
script_tool.py
Runs arbitrary Python scripts on behalf of Hayeong.
"""
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent


def run(description: str, params: dict) -> str:
    try:
        script = params.get("script", "")
        if not script:
            return "[ERROR] No script specified."
        proc = subprocess.run(
            ["python", str(BASE_DIR / script)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return f"[ERROR] Script failed: {proc.stderr or f'exit code {proc.returncode}'}"
        return f"[SUCCESS] {proc.stdout.strip() or 'Script completed'}"
    except Exception as e:
        return f"[ERROR] script_tool: {e}"
