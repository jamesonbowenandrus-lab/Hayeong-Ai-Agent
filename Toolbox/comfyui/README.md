# Toolbox/comfyui

Image generation via ComfyUI. Hayeong calls this tool to generate images —
character art, concept images, Etsy assets, content creation visuals.

## What This Tool Does

Sends generation requests to a locally running ComfyUI instance via its HTTP API.
Handles prompt injection into workflow files, polls for completion, copies output
to `Logs/outputs/comfyui/`, and returns the output path to the reasoning layer.

## Hardware

Targets the AMD RX 7900 XTX. ComfyUI must be running on that GPU before this
tool can generate. The tool checks and reports ComfyUI status — it will not hang
or crash if ComfyUI is not running.

## Files

- `comfyui_tool.py` — main tool, `run()` function, registered in `registry.json`
- `plugin.py` — heartbeat plugin, checks status every 30s, injects into presence context
- `workflows/` — workflow JSON files in ComfyUI API format
  - `txt2img_default.json` — standard 512×512 generation (euler, 20 steps)
  - `txt2img_hires.json` — higher resolution 768×768 (DPM++ 2M Karras, 30 steps)

## Calling This Tool

    action: comfyui
    description: generate a character image of Hayeong in her orange hoodie
    params: workflow=txt2img_default, prompt=score_9 anime girl orange hoodie blue hair

Full params:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `workflow` | str | `txt2img_default` | Workflow filename (no .json) |
| `prompt` | str | required | Positive prompt text |
| `negative` | str | workflow default | Negative prompt |
| `width` | int | workflow default | Image width |
| `height` | int | workflow default | Image height |
| `steps` | int | workflow default | Sampling steps |
| `cfg` | float | workflow default | CFG scale |
| `seed` | int | workflow default | Seed (-1 for random) |
| `output_prefix` | str | `hayeong` | Output filename prefix |

## Output

Generated images are saved to `Logs/outputs/comfyui/` with timestamped filenames:
`{output_prefix}_{YYYYMMDD}_{HHMMSS}.png`

## Adding Workflows

Place any new workflow JSON (ComfyUI API format — not UI format) in `workflows/`
and add `_hayeong_role` keys to the relevant nodes. The tool picks up new
workflow files automatically — no code change required.

Injection roles:
- `"_hayeong_role": "positive_prompt"` — node receives the prompt text
- `"_hayeong_role": "negative_prompt"` — node receives negative text (if provided)
- `"_hayeong_role": "settings"` — node receives steps/cfg/seed/width/height (if provided)
- `"_hayeong_role": "output"` — node receives the output filename prefix

The tool strips `_hayeong_role` before submitting to ComfyUI.

## Checkpoint Note

Both workflow files default to `v1-5-pruned-emaonly.safetensors`. Update the
`ckpt_name` field in the workflow JSON to match whatever checkpoint is installed
in `H:/ComfyUI/models/checkpoints/`.

## Status

ComfyUI must be launched separately before this tool works. Start ComfyUI normally,
then Hayeong connects to it automatically. Plugin reports status in presence context
every 30 seconds.
