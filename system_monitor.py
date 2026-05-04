"""
system_monitor.py
Hayeong's self-awareness of her own hardware and software health.

Runs as a background thread. Checks all components every 30 seconds.
Writes results to:
  - shared state (state_manager) — for LLMs to read
  - state/system_state.json     — for energy_manager to read

This is not a status dashboard — it's information Hayeong feels and acts on.
If her GPU is running hot, that's real information that affects how she operates.
"""

import threading
import time
import json
import subprocess
import requests
import psutil
from datetime import datetime
from pathlib import Path

try:
    import pynvml
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception:
    NVML_AVAILABLE = False

BASE_DIR          = Path(__file__).parent
SYSTEM_STATE_FILE = BASE_DIR / "state" / "system_state.json"

CHECK_INTERVAL_FAST = 30    # seconds — LLMs, voice, CPU, RAM, GPU
CHECK_INTERVAL_SLOW = 300   # seconds — disk, network

_stop_event = threading.Event()
_thread     = None
_last_state: dict = {}


# ─────────────────────────────────────────────
# COMPONENT CHECKS
# ─────────────────────────────────────────────

def _check_ollama(port: int, model_name: str) -> dict:
    """Check if an Ollama instance is running and has the expected model loaded."""
    try:
        resp = requests.get(f"http://localhost:{port}/api/ps", timeout=3)
        resp.raise_for_status()
        models = resp.json().get("models", [])

        if not models:
            return {
                "status":  "online_no_model",
                "healthy": False,
                "detail":  f"Ollama running on {port} but no model loaded",
                "vram_gb": 0,
                "on_gpu":  False,
            }

        for m in models:
            if model_name in m.get("name", ""):
                size_total = m.get("size", 0)
                size_vram  = m.get("size_vram", 0)
                on_gpu     = size_vram == size_total and size_total > 0
                return {
                    "status":  "healthy" if on_gpu else "degraded",
                    "healthy": on_gpu,
                    "detail":  "fully on GPU" if on_gpu else f"{round((size_total - size_vram) / 1e9, 1)}GB in RAM",
                    "vram_gb": round(size_vram / 1e9, 1),
                    "on_gpu":  on_gpu,
                }

        return {
            "status":  "wrong_model",
            "healthy": False,
            "detail":  f"Different model loaded on port {port}",
            "vram_gb": 0,
            "on_gpu":  False,
        }

    except requests.exceptions.ConnectionError:
        return {
            "status":  "offline",
            "healthy": False,
            "detail":  f"Ollama not reachable on port {port}",
            "vram_gb": 0,
            "on_gpu":  False,
        }
    except Exception as e:
        return {
            "status":  "error",
            "healthy": False,
            "detail":  str(e),
            "vram_gb": 0,
            "on_gpu":  False,
        }


def _check_voice_server() -> dict:
    """Check if the voice server is healthy."""
    try:
        resp = requests.get("http://localhost:8765/health", timeout=3)
        if resp.status_code == 200:
            return {"status": "healthy", "healthy": True, "detail": "voice server responding"}
        return {"status": "degraded", "healthy": False, "detail": f"HTTP {resp.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"status": "offline", "healthy": False, "detail": "voice server not reachable"}
    except Exception as e:
        return {"status": "error", "healthy": False, "detail": str(e)}


def _check_cpu() -> dict:
    """CPU usage and temperature."""
    usage = psutil.cpu_percent(interval=1)
    temp  = None

    try:
        import wmi
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        for s in w.Sensor():
            if s.SensorType == "Temperature" and "CPU" in s.Name:
                temp = s.Value
                break
    except Exception:
        pass  # wmi/OpenHardwareMonitor not available

    status = "healthy"
    if usage > 90:
        status = "high_load"
    if temp and temp > 85:
        status = "hot"

    return {
        "status":    status,
        "healthy":   status == "healthy",
        "usage_pct": usage,
        "temp_c":    temp,
        "detail":    f"{usage:.0f}% load" + (f", {temp:.0f}°C" if temp else ""),
    }


def _check_ram() -> dict:
    """RAM usage."""
    mem   = psutil.virtual_memory()
    usage = mem.percent
    avail = round(mem.available / 1e9, 1)

    status = "healthy"
    if usage > 85:
        status = "high"
    if usage > 95:
        status = "critical"

    return {
        "status":    status,
        "healthy":   usage < 85,
        "usage_pct": usage,
        "avail_gb":  avail,
        "detail":    f"{usage:.0f}% used, {avail}GB free",
    }


def _check_gpu_nvidia() -> dict:
    """NVIDIA GPU stats via pynvml — 3090 specific."""
    if not NVML_AVAILABLE:
        return {"status": "unavailable", "healthy": True, "detail": "pynvml not available — install after 3090"}

    try:
        handle     = pynvml.nvmlDeviceGetHandleByIndex(0)
        name       = pynvml.nvmlDeviceGetName(handle)
        temp       = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        mem        = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util       = pynvml.nvmlDeviceGetUtilizationRates(handle)

        vram_used  = round(mem.used  / 1e9, 1)
        vram_total = round(mem.total / 1e9, 1)
        vram_free  = round(mem.free  / 1e9, 1)
        load_pct   = util.gpu

        status = "healthy"
        if temp > 83:
            status = "hot"
        if temp > 90:
            status = "very_hot"
        if vram_free < 2:
            status = "vram_tight"

        return {
            "status":     status,
            "healthy":    status == "healthy",
            "name":       name,
            "temp_c":     temp,
            "load_pct":   load_pct,
            "vram_used":  vram_used,
            "vram_free":  vram_free,
            "vram_total": vram_total,
            "detail":     f"{temp}°C, {load_pct}% load, {vram_used}/{vram_total}GB VRAM",
        }
    except Exception as e:
        return {"status": "error", "healthy": False, "detail": str(e)}


def _check_disk() -> dict:
    """Disk space on H: drive."""
    try:
        usage   = psutil.disk_usage("H:\\")
        free_gb = round(usage.free / 1e9, 1)
        pct     = usage.percent

        status = "healthy"
        if pct > 85:
            status = "low"
        if pct > 95:
            status = "critical"

        return {
            "status":   status,
            "healthy":  pct < 85,
            "free_gb":  free_gb,
            "used_pct": pct,
            "detail":   f"{free_gb}GB free ({pct:.0f}% used)",
        }
    except Exception as e:
        return {"status": "error", "healthy": False, "detail": str(e)}


def _check_network() -> dict:
    """Basic network reachability via ping."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", "8.8.8.8"],
            capture_output=True, timeout=5,
        )
        reachable = result.returncode == 0
        return {
            "status":  "healthy" if reachable else "offline",
            "healthy": reachable,
            "detail":  "network reachable" if reachable else "no network connection",
        }
    except Exception:
        return {"status": "unknown", "healthy": True, "detail": "network check failed"}


# ─────────────────────────────────────────────
# MAIN CHECK LOOP
# ─────────────────────────────────────────────

def _run_checks(include_slow: bool = False) -> dict:
    """Run all health checks and return a complete snapshot."""
    state = {
        "timestamp": datetime.now().isoformat(),
        "components": {
            "communication_llm": _check_ollama(11434, "llama3.2"),
            "reasoning_llm":     _check_ollama(11435, "deepseek-r1"),
            "voice_server":      _check_voice_server(),
            "cpu":               _check_cpu(),
            "ram":               _check_ram(),
            "gpu":               _check_gpu_nvidia(),
        },
    }

    if include_slow:
        state["components"]["disk"]    = _check_disk()
        state["components"]["network"] = _check_network()
    else:
        prev = _last_state.get("components", {})
        if "disk"    in prev:
            state["components"]["disk"]    = prev["disk"]
        if "network" in prev:
            state["components"]["network"] = prev["network"]

    critical = [k for k, v in state["components"].items() if not v.get("healthy", True)]
    state["overall_healthy"]     = len(critical) == 0
    state["critical_components"] = critical

    return state


def _write_system_state(state: dict):
    """Write health state to system_state.json for energy_manager."""
    SYSTEM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_to_shared_state(state: dict):
    """Write key health indicators to shared state for both LLMs to read."""
    try:
        from state_manager import update_health
        components = state.get("components", {})
        for component in ["communication_llm", "reasoning_llm", "voice_server"]:
            if component in components:
                update_health(component, components[component].get("status", "unknown"))
    except Exception as e:
        print(f"[system_monitor] Failed to write shared state: {e}")


def _check_for_critical_changes(new_state: dict, old_state: dict) -> list:
    """
    Compare new and old state. Return list of alert strings for transitions only.
    Never re-flags a condition that was already known — only flags changes.
    """
    alerts = []
    new_components = new_state.get("components", {})
    old_components = old_state.get("components", {})

    for name, new in new_components.items():
        old         = old_components.get(name, {})
        old_healthy = old.get("healthy", True)
        new_healthy = new.get("healthy", True)

        if old_healthy and not new_healthy:
            alerts.append(f"{name} just went {new.get('status', 'offline')}: {new.get('detail', '')}")
        elif not old_healthy and new_healthy:
            alerts.append(f"{name} recovered — back to healthy")

    return alerts


# ─────────────────────────────────────────────
# BACKGROUND THREAD
# ─────────────────────────────────────────────

def _monitor_loop():
    global _last_state
    print("[system_monitor] Started.")
    tick = 0

    while not _stop_event.is_set():
        try:
            include_slow = (tick % (CHECK_INTERVAL_SLOW // CHECK_INTERVAL_FAST) == 0)
            new_state    = _run_checks(include_slow=include_slow)
            alerts       = _check_for_critical_changes(new_state, _last_state)

            _write_system_state(new_state)
            _write_to_shared_state(new_state)

            if alerts:
                try:
                    from state_manager import flag_priority
                    for alert in alerts:
                        print(f"[system_monitor] ALERT: {alert}")
                        flag_priority(f"System health alert: {alert}", level="high")
                except Exception:
                    pass

            _last_state = new_state
            tick += 1

        except Exception as e:
            print(f"[system_monitor] Check error: {e}")

        _stop_event.wait(timeout=CHECK_INTERVAL_FAST)

    print("[system_monitor] Stopped.")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def start_monitor():
    """Start the health monitor background thread. Call once at startup."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_monitor_loop, daemon=True, name="system-monitor")
    _thread.start()


def stop_monitor():
    """Stop the health monitor."""
    _stop_event.set()


def get_status() -> dict:
    """Return the last known health state synchronously. Safe to call from any thread."""
    return _last_state or {}


def format_for_prompt() -> str:
    """
    Format health state for injection into LLM system prompt.
    Returns empty string when all healthy — don't inject noise into every prompt.
    Only reports issues worth knowing about.
    """
    state = get_status()
    if not state:
        return ""

    components = state.get("components", {})
    issues     = []

    gpu = components.get("gpu", {})
    if gpu.get("temp_c") and gpu["temp_c"] > 75:
        issues.append(f"GPU running warm at {gpu['temp_c']}°C")

    ram = components.get("ram", {})
    if ram.get("usage_pct") and ram["usage_pct"] > 80:
        issues.append(f"RAM usage at {ram['usage_pct']:.0f}%")

    for name in ["communication_llm", "reasoning_llm", "voice_server"]:
        comp = components.get(name, {})
        if not comp.get("healthy", True):
            issues.append(f"{name.replace('_', ' ')} is {comp.get('status', 'offline')}")

    if not issues:
        return ""

    return "[SYSTEM HEALTH]\n" + "\n".join(f"  • {i}" for i in issues) + "\n"
