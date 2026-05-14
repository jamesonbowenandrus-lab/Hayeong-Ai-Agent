"""
script_tool.py
Runs arbitrary Python scripts on behalf of Hayeong.
"""
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent


def run(description: str, params: dict) -> str:
    script = params.get("script", "")
    if not script:
        raise ValueError("No script specified")
    proc = subprocess.run(
        ["python", str(BASE_DIR / script)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or f"Script exited with code {proc.returncode}")
    return proc.stdout or "Script completed"
