"""
Toolbox/sensor_tool/sensor_tool.py

Gives Hayeong awareness of her own hardware state.
GPU temps, VRAM usage, CPU load, RAM, disk space.

Called via registry:
    module:   toolbox.sensor_tool.sensor_tool
    function: run

Params:
    operation  (str) — status | check_gpu | check_vram_headroom
    gpu        (str) — 3090 | 7900xtx | all
"""

from pathlib import Path
from datetime import datetime
import json

ROOT_DIR = Path(__file__).parent.parent.parent


def run(description: str, params: dict) -> str:
    try:
        operation = params.get("operation", "status").lower()
        gpu       = params.get("gpu", "all").lower()

        if operation == "status":
            return _full_status()
        elif operation == "check_gpu":
            return _gpu_status(gpu)
        elif operation == "check_vram_headroom":
            return _vram_headroom(gpu)
        else:
            return f"Unknown operation '{operation}'. Use: status, check_gpu, check_vram_headroom"
    except Exception as e:
        return f"sensor_tool error: {e}"


def _full_status() -> str:
    lines = ["Hardware Status:"]
    lines.append(_gpu_status("all"))
    lines.append(_cpu_ram_status())
    lines.append(_disk_status())
    return "\n".join(lines)


def _gpu_status(gpu: str) -> str:
    results = []
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem    = pynvml.nvmlDeviceGetMemoryInfo(handle)
        temp   = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        util   = pynvml.nvmlDeviceGetUtilizationRates(handle)
        used   = round(mem.used / 1024**3, 1)
        total  = round(mem.total / 1024**3, 1)
        results.append(
            f"  RTX 3090: VRAM {used}/{total}GB | Temp {temp}C | GPU util {util.gpu}%"
        )
    except Exception as e:
        results.append(f"  RTX 3090: unavailable ({e})")

    try:
        import pyamdgpuinfo
        gpu_amd = pyamdgpuinfo.get_gpu(0)
        vram    = round(gpu_amd.query_vram_usage() / 1024**3, 1)
        total   = round(gpu_amd.memory_info["vram_size"] / 1024**3, 1)
        temp    = gpu_amd.query_temperature()
        results.append(
            f"  RX 7900 XTX: VRAM {vram}/{total}GB | Temp {round(temp, 1)}C"
        )
    except Exception as e:
        results.append(f"  RX 7900 XTX: unavailable ({e})")

    return "\n".join(results)


def _vram_headroom(gpu: str) -> str:
    results = []
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem    = pynvml.nvmlDeviceGetMemoryInfo(handle)
        free   = round(mem.free / 1024**3, 1)
        total  = round(mem.total / 1024**3, 1)
        results.append(f"RTX 3090 free VRAM: {free}/{total}GB")
    except Exception as e:
        results.append(f"RTX 3090 VRAM check failed: {e}")
    return "\n".join(results)


def _cpu_ram_status() -> str:
    try:
        import psutil
        cpu  = psutil.cpu_percent(interval=0.5)
        ram  = psutil.virtual_memory()
        used = round(ram.used / 1024**3, 1)
        total = round(ram.total / 1024**3, 1)
        return f"  CPU: {cpu}% | RAM: {used}/{total}GB"
    except Exception as e:
        return f"  CPU/RAM: unavailable ({e})"


def _disk_status() -> str:
    try:
        import psutil
        results = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                free  = round(usage.free / 1024**3, 1)
                total = round(usage.total / 1024**3, 1)
                results.append(f"  Disk {part.device}: {free}/{total}GB free")
            except Exception:
                pass
        return "\n".join(results) if results else "  Disk: unavailable"
    except Exception as e:
        return f"  Disk: unavailable ({e})"