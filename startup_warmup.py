"""
startup_warmup.py
Pre-loads both LLMs into VRAM before Hayeong starts.
Called by start_hayeong.bat at step 4.

A cold model on first call adds 15-30 seconds of delay.
This ensures both models are resident in VRAM and ready.
"""

import sys
import time
import requests

COMMUNICATION_URL   = "http://localhost:11434/api/generate"
REASONING_URL       = "http://localhost:11435/api/generate"
COMMUNICATION_MODEL = "llama3.2:latest"
REASONING_MODEL     = "deepseek-r1:latest"
WARMUP_TIMEOUT      = 120  # seconds — 14b can be slow to load


def warm_model(url: str, model: str, name: str) -> bool:
    """Send a minimal prompt to load the model into VRAM."""
    print(f"    Warming {name}...", end=" ", flush=True)
    try:
        start = time.time()
        resp  = requests.post(
            url,
            json={
                "model":  model,
                "prompt": "hi",
                "stream": False,
            },
            timeout=WARMUP_TIMEOUT,
        )
        resp.raise_for_status()
        elapsed = round(time.time() - start, 1)
        print(f"ready in {elapsed}s")
        return True
    except requests.exceptions.Timeout:
        print(f"TIMEOUT after {WARMUP_TIMEOUT}s")
        return False
    except Exception as e:
        print(f"FAILED -- {e}")
        return False


def verify_vram(port: int, model: str, name: str) -> bool:
    """Confirm the model is fully on GPU after warmup."""
    try:
        resp = requests.get(f"http://localhost:{port}/api/ps", timeout=5)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        for m in models:
            if model.split(":")[0] in m.get("name", ""):
                size_total = m.get("size", 0)
                size_vram  = m.get("size_vram", 0)
                on_gpu     = size_vram == size_total and size_total > 0
                vram_gb    = round(size_vram / 1e9, 1)
                if on_gpu:
                    print(f"    {name}: {vram_gb}GB fully on GPU")
                else:
                    ram_gb = round((size_total - size_vram) / 1e9, 1)
                    print(f"    {name}: WARNING -- {ram_gb}GB spilling to RAM")
                    print(f"    Fix: ensure OLLAMA_NUM_GPU=99 is set in the bat file")
                return on_gpu
        print(f"    {name}: model not found in loaded list")
        return False
    except Exception as e:
        print(f"    {name}: VRAM check failed -- {e}")
        return False


if __name__ == "__main__":
    print("  Warming up models into VRAM:")

    comm_ok = warm_model(COMMUNICATION_URL, COMMUNICATION_MODEL, "Communication LLM (7b)")
    reas_ok = warm_model(REASONING_URL,     REASONING_MODEL,     "Reasoning LLM (14b)")

    print("  Verifying VRAM placement:")
    comm_vram = verify_vram(11434, COMMUNICATION_MODEL, "Communication LLM")
    reas_vram = verify_vram(11435, REASONING_MODEL,     "Reasoning LLM")

    if not (comm_ok and reas_ok):
        print("\n  ERROR -- one or more models failed to warm up")
        sys.exit(1)

    if not (comm_vram and reas_vram):
        print("\n  WARNING -- models loaded but not fully on GPU")
        print("  Performance will be degraded. Check OLLAMA_NUM_GPU setting.")
        # Don't exit 1 — degraded is still functional, warn and continue
        sys.exit(0)

    print("\n  Both models ready. VRAM confirmed.")
    sys.exit(0)
