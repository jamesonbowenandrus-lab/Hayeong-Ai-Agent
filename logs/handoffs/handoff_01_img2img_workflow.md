# Handoff 01 — img2img Workflow JSON
**Scope:** Add `txt2img_img2img.json` to `Toolbox/comfyui/workflows/`
**Who does this:** Hayeong (no Claude Code needed — pure JSON file, no Python)
**Main.py touched:** No
**image_gen_cap.py touched:** No
**comfyui_tool.py touched:** No

---

## What This Is

A new ComfyUI workflow file that takes an existing image as a starting point instead of
generating from scratch. This enables iterative refinement — James approves a generated
image and asks for targeted changes without losing the composition entirely.

The tool already supports workflow selection via the `workflow` param. Adding this file
is the entire change. No code modification required.

---

## File to Create

**Path:** `Toolbox/comfyui/workflows/txt2img_img2img.json`

```json
{
  "1": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {
      "ckpt_name": "v1-5-pruned-emaonly.safetensors"
    }
  },
  "2": {
    "_hayeong_role": "positive_prompt",
    "class_type": "CLIPTextEncode",
    "inputs": {
      "clip": ["1", 1],
      "text": "score_9, anime girl, orange hoodie, blue hair, detailed, best quality"
    }
  },
  "3": {
    "_hayeong_role": "negative_prompt",
    "class_type": "CLIPTextEncode",
    "inputs": {
      "clip": ["1", 1],
      "text": "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, blurry"
    }
  },
  "4": {
    "class_type": "LoadImage",
    "inputs": {
      "image": "hayeong_latest.png"
    }
  },
  "5": {
    "class_type": "VAEEncode",
    "inputs": {
      "pixels": ["4", 0],
      "vae": ["1", 2]
    }
  },
  "6": {
    "_hayeong_role": "settings",
    "class_type": "KSampler",
    "inputs": {
      "model": ["1", 0],
      "positive": ["2", 0],
      "negative": ["3", 0],
      "latent_image": ["5", 0],
      "seed": 0,
      "steps": 25,
      "cfg": 7.0,
      "sampler_name": "dpmpp_2m",
      "scheduler": "karras",
      "denoise": 0.55
    }
  },
  "7": {
    "class_type": "VAEDecode",
    "inputs": {
      "samples": ["6", 0],
      "vae": ["1", 2]
    }
  },
  "8": {
    "_hayeong_role": "output",
    "class_type": "SaveImage",
    "inputs": {
      "images": ["7", 0],
      "filename_prefix": "hayeong_refined"
    }
  }
}
```

---

## Key Design Notes

**`denoise: 0.55`** — This is the most important value. It controls how much of the
original image is preserved vs redrawn.
- `0.3` = very subtle changes, mostly preserves original
- `0.55` = balanced — changes content meaningfully while keeping composition
- `0.8+` = nearly a full regeneration, just with the same general layout

James will likely want to experiment with this. The recommended approach is to expose
it as a tunable param in the future (see Handoff 03). For now 0.55 is a safe default
that will feel like genuine refinement rather than a complete redo.

**`LoadImage` node (node "4")** — ComfyUI's LoadImage node reads from its `input/`
directory. The session context system (Handoff 03) will handle copying the last
generated output there automatically so Hayeong can reference it by a stable name
(`hayeong_latest.png`) without hardcoding a timestamped path.

**`output_prefix: "hayeong_refined"`** — Refined images get a distinct prefix so they
don't overwrite originals and James can tell them apart in the output folder.

---

## How Hayeong Calls This

Once the file exists, Hayeong can use it immediately with no other changes:

```
action: image_gen
workflow: txt2img_img2img
prompt: same character but change the background to a rainy city street at night
```

The brain layer should prefer `txt2img_img2img` when James says phrases like:
- "change the...", "keep the ... but ...", "refine it", "tweak it", "adjust the..."
- And prefer `txt2img_default` or `txt2img_hires` for fresh generation requests.

**Update `capability_registry.json` decision_hint for `image_gen`:**

Change the existing hint from:
```
"James wants you to generate or draw an image. Include: prompt (description of what to generate)."
```

To:
```
"James wants you to generate or draw an image. Include: prompt (description of what to generate), workflow (txt2img_default for new images, txt2img_hires for high resolution, txt2img_img2img for refining an existing image — use img2img when James says change/tweak/refine/adjust rather than generate fresh)."
```

This teaches the brain to choose the right workflow without needing new code.

---

## Checkpoint Note

The workflow defaults to `v1-5-pruned-emaonly.safetensors` — same as the other two workflows.
If the checkpoint name in ComfyUI differs, update the `ckpt_name` field in node "1" to match.
Check the other workflow files for the currently active checkpoint name and keep all three consistent.

---

## Verification

After adding the file, test by asking Hayeong:
1. Generate a fresh image (should use `txt2img_default`)
2. "Change the background to a forest" (should use `txt2img_img2img`)
3. Confirm `Logs/outputs/comfyui/` contains a file prefixed `hayeong_refined_`
