# Toolbox/sensor_tool

Gives Hayeong hardware awareness — GPU temps, VRAM, CPU, RAM, disk.

## Calling This Tool

    action: sensor_tool
    params: operation=status

    action: sensor_tool
    params: operation=check_vram_headroom, gpu=3090

## Operations

- status — full hardware report
- check_gpu — GPU-specific metrics
- check_vram_headroom — how much VRAM is free

## Dependencies

- pynvml — NVIDIA GPU metrics (pip install pynvml)
- psutil — CPU/RAM/disk (pip install psutil)
- pyamdgpuinfo — AMD GPU metrics (optional, degrades gracefully if missing)

## Plugin

plugin.py injects hardware state into shared state every heartbeat.
Hayeong reads this before starting compute-heavy tasks.