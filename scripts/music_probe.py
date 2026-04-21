"""
music_probe.py
Hardware probe — run this ONCE before any other music script.

Confirms whether the AMD 7900 can run Stable Audio Open and LP-MusicCaps
on Windows via ROCm or DirectML. Writes results to:
  logs/music_probe_results.txt  — human-readable full report
  logs/music_device.json        — machine-readable device config for other scripts

Run:
  python scripts/music_probe.py

Read the FULL output before proceeding. If verdict is NOT USABLE, stop.
Do not build music_generate.py or music_analyze.py until this passes.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent
LOG_DIR     = BASE_DIR / "logs"
RESULTS_TXT = LOG_DIR / "music_probe_results.txt"
DEVICE_JSON = LOG_DIR / "music_device.json"

LOG_DIR.mkdir(parents=True, exist_ok=True)

_lines = []


def _log(line: str = ""):
    print(line)
    _lines.append(line)


def _save_results():
    RESULTS_TXT.write_text("\n".join(_lines), encoding="utf-8")
    _log(f"\nFull results saved to: {RESULTS_TXT}")


# ─────────────────────────────────────────────
# SECTION 1 — GPU / device detection
# ─────────────────────────────────────────────

def probe_device() -> dict:
    _log("=" * 60)
    _log("SECTION 1 — GPU / Device Detection")
    _log("=" * 60)

    result = {
        "torch_available": False,
        "rocm_available": False,
        "directml_available": False,
        "confirmed_device": None,
        "device_str": None,
    }

    try:
        import torch
        result["torch_available"] = True
        _log(f"  PyTorch version : {torch.__version__}")

        # ROCm check
        hip_version = getattr(torch.version, "hip", None)
        if hip_version:
            result["rocm_available"] = True
            _log(f"  ROCm (HIP)      : {hip_version}")
        else:
            _log("  ROCm (HIP)      : not available")

        # CUDA check (expect False on 7900 AMD-only machine)
        if torch.cuda.is_available():
            _log(f"  CUDA            : available ({torch.cuda.get_device_name(0)})")
        else:
            _log("  CUDA            : not available (expected on AMD-only system)")

        # DirectML check
        try:
            import torch_directml
            dml_device = torch_directml.device()
            result["directml_available"] = True
            result["directml_device_obj"] = dml_device
            _log(f"  DirectML        : available — {dml_device}")
        except ImportError:
            _log("  DirectML        : not available (pip install torch-directml to enable)")
        except Exception as e:
            _log(f"  DirectML        : import error — {e}")

        # Decide which device to use — ROCm preferred, DirectML fallback
        if result["rocm_available"]:
            result["confirmed_device"] = "rocm"
            result["device_str"] = "cuda"   # ROCm exposes itself as 'cuda' in PyTorch
            _log("\n  → Using ROCm (via 'cuda' device string in PyTorch)")
        elif result["directml_available"]:
            result["confirmed_device"] = "directml"
            result["device_str"] = "privateuseone"   # torch_directml device
            _log("\n  → Using DirectML")
        else:
            result["confirmed_device"] = "cpu"
            result["device_str"] = "cpu"
            _log("\n  → Falling back to CPU (no GPU compute available)")

    except ImportError:
        _log("  ERROR: PyTorch not installed. Run: pip install torch torchaudio")

    _log("")
    return result


# ─────────────────────────────────────────────
# SECTION 2 — Basic compute test
# ─────────────────────────────────────────────

def probe_compute(device_info: dict) -> bool:
    _log("=" * 60)
    _log("SECTION 2 — Basic Compute Test")
    _log("=" * 60)

    if not device_info["torch_available"]:
        _log("  SKIP — PyTorch not available")
        return False

    import torch

    device_str = device_info["device_str"]
    _log(f"  Testing device: {device_str}")

    try:
        if device_info["confirmed_device"] == "directml":
            import torch_directml
            device = torch_directml.device()
        else:
            device = torch.device(device_str)

        t0 = time.time()
        a = torch.randn(1024, 1024, device=device)
        b = torch.randn(1024, 1024, device=device)
        c = torch.matmul(a, b)
        _ = c.sum().item()   # force sync
        elapsed = time.time() - t0

        _log(f"  Matrix multiply 1024x1024 : {elapsed*1000:.1f}ms  ✓")
        _log("")
        return True
    except Exception as e:
        _log(f"  FAILED: {e}")
        _log("")
        return False


# ─────────────────────────────────────────────
# SECTION 3 — Stable Audio Open compatibility
# ─────────────────────────────────────────────

def probe_stable_audio(device_info: dict) -> bool:
    _log("=" * 60)
    _log("SECTION 3 — Stable Audio Open Compatibility")
    _log("=" * 60)

    try:
        import torch
        from stable_audio_tools import get_pretrained_model
        from stable_audio_tools.inference.generation import generate_diffusion_cond
        _log("  stable-audio-tools imported  ✓")
    except ImportError as e:
        _log(f"  SKIP — stable-audio-tools not installed: {e}")
        _log("  Install: pip install stable-audio-tools")
        _log("")
        return False

    device_str = device_info["device_str"]
    if device_info["confirmed_device"] == "directml":
        import torch_directml
        device = torch_directml.device()
    else:
        import torch
        device = torch.device(device_str)

    try:
        _log("  Loading stabilityai/stable-audio-open-1.0 ...")
        t0 = time.time()
        model, model_config = get_pretrained_model("stabilityai/stable-audio-open-1.0")
        model = model.to(device)
        model.eval()
        load_time = time.time() - t0
        _log(f"  Model loaded in {load_time:.1f}s  ✓")
    except Exception as e:
        _log(f"  Model load FAILED: {e}")
        _log("")
        return False

    try:
        import torch
        _log("  Running 3-second test generation (steps=20)...")
        sample_rate = model_config["sample_rate"]
        sample_size = model_config["sample_size"]

        t0 = time.time()
        conditioning = [{"prompt": "soft ambient pad", "seconds_start": 0, "seconds_total": 3}]
        with torch.no_grad():
            output = generate_diffusion_cond(
                model,
                steps=20,
                cfg_scale=7,
                conditioning=conditioning,
                sample_size=sample_size,
                sigma_min=0.3,
                sigma_max=500,
                sampler_type="dpmpp-3m-sde",
                device=device,
            )
        gen_time = time.time() - t0
        _log(f"  Test generation complete in {gen_time:.1f}s  ✓")
        _log(f"  Output shape: {output.shape}")
        _log("")
        del model
        return True
    except Exception as e:
        _log(f"  Generation FAILED: {e}")
        _log("")
        return False


# ─────────────────────────────────────────────
# SECTION 4 — LP-MusicCaps compatibility
# ─────────────────────────────────────────────

def probe_lp_musiccaps(device_info: dict) -> bool:
    _log("=" * 60)
    _log("SECTION 4 — LP-MusicCaps Compatibility")
    _log("=" * 60)

    # LP-MusicCaps HuggingFace model ID — verify at:
    # https://huggingface.co/seungheondoh/LP-music-caps
    LP_MUSICCAPS_MODEL = "seungheondoh/LP-music-caps"

    try:
        import torch
        import numpy as np
        from transformers import pipeline as hf_pipeline
        _log("  transformers imported  ✓")
    except ImportError as e:
        _log(f"  SKIP — transformers not installed: {e}")
        _log("  Install: pip install transformers")
        _log("")
        return False

    try:
        import librosa
        _log("  librosa imported  ✓")
    except ImportError:
        _log("  WARNING: librosa not installed — audio preprocessing unavailable")
        _log("  Install: pip install librosa")

    device_str = device_info["device_str"]
    # HuggingFace pipeline device arg: int GPU index for CUDA/ROCm, "cpu" for CPU
    hf_device = 0 if device_info["confirmed_device"] in ("rocm", "cuda") else -1

    try:
        _log(f"  Loading {LP_MUSICCAPS_MODEL} ...")
        t0 = time.time()
        captioner = hf_pipeline(
            "text-generation",
            model=LP_MUSICCAPS_MODEL,
            device=hf_device,
        )
        load_time = time.time() - t0
        _log(f"  Model loaded in {load_time:.1f}s  ✓")
    except Exception as e:
        _log(f"  Model load FAILED: {e}")
        _log(f"  Note: Verify model name at https://huggingface.co/seungheondoh/LP-music-caps")
        _log("")
        return False

    try:
        import numpy as np
        _log("  Running inference on synthetic silent clip (1 second, 22050hz mono)...")
        # Generate a short synthetic sine wave as test audio
        sr = 22050
        test_audio = np.sin(2 * np.pi * 440 * np.linspace(0, 1, sr)).astype(np.float32)

        t0 = time.time()
        result = captioner({"array": test_audio, "sampling_rate": sr}, max_new_tokens=100)
        inf_time = time.time() - t0
        _log(f"  Inference complete in {inf_time:.1f}s  ✓")
        _log(f"  Sample output: {str(result)[:120]}")
        _log("")
        del captioner
        return True
    except Exception as e:
        _log(f"  Inference FAILED: {e}")
        _log("")
        return False


# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────

def summarize_and_save(device_info: dict, compute_ok: bool, stable_audio_ok: bool, lp_musiccaps_ok: bool):
    _log("=" * 60)
    _log("SUMMARY")
    _log("=" * 60)

    _log(f"  Device          : {device_info.get('confirmed_device', 'unknown')} "
         f"(PyTorch string: '{device_info.get('device_str', 'unknown')}')")
    _log(f"  Basic compute   : {'✓ PASS' if compute_ok else '✗ FAIL'}")
    _log(f"  Stable Audio    : {'✓ PASS' if stable_audio_ok else '✗ FAIL'}")
    _log(f"  LP-MusicCaps    : {'✓ PASS' if lp_musiccaps_ok else '✗ FAIL'}")

    if stable_audio_ok and lp_musiccaps_ok:
        verdict = "READY"
        _log("\n  VERDICT: READY — both models work on the 7900")
        _log("  You can proceed to build music_generate.py and music_analyze.py")
    elif stable_audio_ok and not lp_musiccaps_ok:
        verdict = "PARTIAL"
        _log("\n  VERDICT: PARTIAL — Stable Audio works, LP-MusicCaps does not")
        _log("  music_generate.py (from text prompt) will work")
        _log("  music_analyze.py (reference track analysis) will not work")
    elif not stable_audio_ok and lp_musiccaps_ok:
        verdict = "PARTIAL"
        _log("\n  VERDICT: PARTIAL — LP-MusicCaps works, Stable Audio does not")
        _log("  Reference track analysis works, but cannot generate audio")
    else:
        verdict = "NOT USABLE"
        _log("\n  VERDICT: NOT USABLE — neither model runs on the 7900")
        _log("  Options:")
        _log("    1. Run on 3090 instead (competes with LLM VRAM — document tradeoff)")
        _log("    2. Investigate ROCm/DirectML driver issues and retry")
        _log("  Do NOT build music_generate.py or music_analyze.py until this passes.")

    _log("")

    # Write machine-readable device config for other scripts to read
    device_config = {
        "probe_date":        datetime.now().isoformat(),
        "verdict":           verdict,
        "confirmed_device":  device_info.get("confirmed_device"),
        "device_str":        device_info.get("device_str"),
        "stable_audio_ok":   stable_audio_ok,
        "lp_musiccaps_ok":   lp_musiccaps_ok,
        "rocm_available":    device_info.get("rocm_available", False),
        "directml_available": device_info.get("directml_available", False),
    }
    DEVICE_JSON.write_text(json.dumps(device_config, indent=2), encoding="utf-8")
    _log(f"  Device config saved to: {DEVICE_JSON}")

    return verdict


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def run():
    _log(f"Hayeong Music Probe — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _log(f"Python: {sys.version}")
    _log("")

    device_info    = probe_device()
    compute_ok     = probe_compute(device_info)
    stable_audio_ok = probe_stable_audio(device_info)
    lp_musiccaps_ok = probe_lp_musiccaps(device_info)
    verdict         = summarize_and_save(device_info, compute_ok, stable_audio_ok, lp_musiccaps_ok)

    _save_results()
    return verdict


if __name__ == "__main__":
    verdict = run()
    sys.exit(0 if verdict != "NOT USABLE" else 1)
