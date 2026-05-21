"""
toolbox/comfyui/comfyui_tool.py

Hayeong's ComfyUI control layer.
Sends image generation requests to a locally running ComfyUI instance via HTTP API.
Targets AMD RX 7900 XTX — no CUDA dependency.

Called via registry:
    module:   toolbox.comfyui.comfyui_tool
    function: run

Params:
    workflow        (str)   — workflow filename without .json (default: txt2img_default)
    prompt          (str)   — positive prompt text (required)
    negative        (str)   — negative prompt (optional)
    width           (int)   — image width (optional)
    height          (int)   — image height (optional)
    steps           (int)   — sampling steps (optional)
    cfg             (float) — CFG scale (optional)
    seed            (int)   — seed, -1 for random (optional)
    output_prefix   (str)   — filename prefix for output (default: hayeong)

Returns:
    str — result message (never raises — always returns a clean string)
"""

import copy
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import requests

from brain.config import (
    COMFYUI_URL,
    COMFYUI_TIMEOUT,
    COMFYUI_POLL_INTERVAL,
    COMFYUI_OUTPUT_DIR,
    COMFYUI_WORKFLOW_DIR,
)

LOG_FILE   = Path(__file__).parent.parent.parent / "logs" / "comfyui_bridge.log"
OUTPUT_DIR = Path(COMFYUI_OUTPUT_DIR)
WORKFLOW_DIR = Path(COMFYUI_WORKFLOW_DIR)


def run(description: str, params: dict) -> str:
    """Entry point called by main.py task loop via registry. Always returns a string."""
    try:
        return _run_pipeline(params)
    except Exception as e:
        return f"[ERROR] ComfyUI tool: {e}"


def _run_pipeline(params: dict) -> str:
    prompt        = params.get("prompt", "").strip()
    workflow_name = params.get("workflow", "txt2img_default")
    output_prefix = params.get("output_prefix", "hayeong")

    if not prompt:
        return "[ERROR] No prompt provided. Set prompt in task_params."

    # ── 1. Health check ───────────────────────────────────────────────
    if not _is_running():
        _log(f"Generation skipped — ComfyUI is not running | Prompt: {prompt}")
        return "[ERROR] ComfyUI is not running. Start ComfyUI on the 7900 XTX before requesting image generation."

    # ── 2. Load workflow ──────────────────────────────────────────────
    workflow_path = WORKFLOW_DIR / f"{workflow_name}.json"
    if not workflow_path.exists():
        return f"[ERROR] Workflow not found: {workflow_path}. Available: {_list_workflows()}"

    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[ERROR] Failed to load workflow '{workflow_name}': {e}"

    # ── 3. Inject params ──────────────────────────────────────────────
    workflow = _inject_params(workflow, params)

    # ── 4. Submit to ComfyUI ──────────────────────────────────────────
    try:
        resp = requests.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow},
            timeout=30,
        )
        resp.raise_for_status()
        prompt_id = resp.json().get("prompt_id")
    except Exception as e:
        return f"[ERROR] Failed to submit workflow to ComfyUI: {e}"

    if not prompt_id:
        return "[ERROR] ComfyUI did not return a prompt_id — submission may have failed."

    # ── 5. Poll for completion ────────────────────────────────────────
    start    = time.time()
    history  = None

    while time.time() - start < COMFYUI_TIMEOUT:
        time.sleep(COMFYUI_POLL_INTERVAL)
        try:
            r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            data = r.json()
        except Exception:
            continue

        entry = data.get(prompt_id)
        if not entry:
            continue

        status = entry.get("status", {})
        if status.get("completed"):
            history = entry
            break

        if status.get("status_str") == "error":
            return f"[ERROR] ComfyUI reported generation error for prompt_id {prompt_id}."
    else:
        return f"[ERROR] ComfyUI generation timed out after {COMFYUI_TIMEOUT}s."

    # ── 6. Extract output images ──────────────────────────────────────
    images = []
    for node_output in history.get("outputs", {}).values():
        for img in node_output.get("images", []):
            images.append(img)

    if not images:
        return f"[PARTIAL] ComfyUI completed prompt_id={prompt_id} but no output images found in history."

    # ── 7. Copy outputs ───────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_paths = []

    for i, img_info in enumerate(images):
        suffix = f"_{i}" if i > 0 else ""
        dest = OUTPUT_DIR / f"{output_prefix}_{ts}{suffix}.png"
        try:
            img_data = requests.get(
                f"{COMFYUI_URL}/view",
                params={
                    "filename": img_info["filename"],
                    "subfolder": img_info.get("subfolder", ""),
                    "type": img_info.get("type", "output"),
                },
                timeout=30,
            )
            img_data.raise_for_status()
            dest.write_bytes(img_data.content)
            saved_paths.append(str(dest))
        except Exception as e:
            saved_paths.append(f"[failed to copy {img_info['filename']}: {e}]")

    # ── 8. Log ────────────────────────────────────────────────────────
    steps    = params.get("steps", "?")
    seed_val = params.get("seed", "?")
    for path in saved_paths:
        _log(f"Generated: {path} | Prompt: {prompt} | Steps: {steps} | Seed: {seed_val}")

    # ── 9. Return result ──────────────────────────────────────────────
    output_line = saved_paths[0] if len(saved_paths) == 1 else str(saved_paths)
    cfg_val      = params.get("cfg", "?")
    return (
        f"[SUCCESS] Image generated: {output_line}\n"
        f"Prompt: {prompt}\n"
        f"Workflow: {workflow_name} | Steps: {steps} | CFG: {cfg_val} | Seed: {seed_val}"
    )


def _is_running() -> bool:
    try:
        r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _inject_params(workflow: dict, params: dict) -> dict:
    """Inject params into nodes using _hayeong_role markers. Strips marker before submit."""
    wf = copy.deepcopy(workflow)
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        role = node.pop("_hayeong_role", None)
        if not role:
            continue
        inputs = node.get("inputs", {})

        if role == "positive_prompt" and params.get("prompt"):
            inputs["text"] = params["prompt"]

        elif role == "negative_prompt" and params.get("negative"):
            inputs["text"] = params["negative"]

        elif role == "settings":
            if params.get("steps") is not None:
                inputs["steps"] = int(params["steps"])
            if params.get("cfg") is not None:
                inputs["cfg"] = float(params["cfg"])
            if params.get("seed") is not None and int(params["seed"]) != -1:
                inputs["seed"] = int(params["seed"])
            if params.get("width") is not None:
                inputs["width"] = int(params["width"])
            if params.get("height") is not None:
                inputs["height"] = int(params["height"])

        elif role == "output" and params.get("output_prefix"):
            inputs["filename_prefix"] = params["output_prefix"]

    return wf


def _list_workflows() -> str:
    try:
        return ", ".join(p.stem for p in WORKFLOW_DIR.glob("*.json"))
    except Exception:
        return "(none found)"


def _log(message: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
