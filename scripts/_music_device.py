"""
_music_device.py
Shared device resolution for music scripts.

Reads the confirmed device from logs/music_device.json (written by music_probe.py).
Falls back to detection if the probe has not been run yet.

All music scripts import get_music_device() from here instead of repeating detection.
"""

import json
from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent
DEVICE_JSON = BASE_DIR / "logs" / "music_device.json"


def get_music_device() -> dict:
    """
    Returns a dict with:
      device_str       — string to pass to torch.device() (e.g. 'cuda', 'cpu')
      confirmed_device — 'rocm' | 'directml' | 'cpu'
      verdict          — probe verdict string, or 'UNPROBED' if probe was not run
      directml_device  — torch_directml device object (only set when directml)
    """
    if DEVICE_JSON.exists():
        try:
            config = json.loads(DEVICE_JSON.read_text(encoding="utf-8"))
            result = {
                "device_str":       config.get("device_str", "cpu"),
                "confirmed_device": config.get("confirmed_device", "cpu"),
                "verdict":          config.get("verdict", "UNKNOWN"),
                "directml_device":  None,
            }
            if result["confirmed_device"] == "directml":
                try:
                    import torch_directml
                    result["directml_device"] = torch_directml.device()
                except Exception:
                    result["confirmed_device"] = "cpu"
                    result["device_str"] = "cpu"
            return result
        except Exception:
            pass

    # Probe not run — do a minimal live check and warn
    print("[music] WARNING: music_probe.py has not been run. Run it first.")
    print("[music] Attempting live device detection as fallback...")

    result = {
        "device_str":       "cpu",
        "confirmed_device": "cpu",
        "verdict":          "UNPROBED",
        "directml_device":  None,
    }

    try:
        import torch
        if getattr(torch.version, "hip", None):
            result["device_str"] = "cuda"
            result["confirmed_device"] = "rocm"
            print("[music] ROCm detected — using 'cuda' device string")
            return result
    except ImportError:
        pass

    try:
        import torch_directml
        result["directml_device"] = torch_directml.device()
        result["confirmed_device"] = "directml"
        result["device_str"] = "privateuseone"
        print("[music] DirectML detected")
        return result
    except ImportError:
        pass

    print("[music] No GPU compute found — falling back to CPU")
    return result


def get_torch_device(device_info: dict = None):
    """Return a torch.device (or torch_directml device) ready to pass to .to()."""
    import torch
    if device_info is None:
        device_info = get_music_device()

    if device_info["confirmed_device"] == "directml" and device_info.get("directml_device"):
        return device_info["directml_device"]
    return torch.device(device_info["device_str"])
