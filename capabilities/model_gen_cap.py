# capabilities/model_gen_cap.py
# 3D model generation capability.
#
# Handles: model_gen action from context_router
# Generates SketchUp Ruby scripts and OBJ files from natural language descriptions.
# Output saved to: hayeong_outputs/3d_models/
#
# Supported output formats:
#   sketchup_ruby  — Ruby script for SketchUp Ruby console (primary path)
#   obj            — Plain-text OBJ file, no software required (simple geometry)
#   blender_python — Blender Python script (future path, not yet implemented)
#
# Generation uses deepseek-coder-v2:16b first, qwen2.5:14b as fallback.
# The generation, save, and confirm steps are intentionally discrete functions
# so a vision QC pass can be inserted between save and confirm later.

import os
import json
import datetime
import requests
from pathlib import Path
from capability_loader import result

ACTIONS = ["model_gen"]

OLLAMA_URL    = "http://localhost:11434/api/chat"
GEN_MODELS    = ["deepseek-coder-v2:16b", "deepseek-coder:33b", "qwen2.5:14b"]
OUTPUT_DIR    = Path(__file__).parent.parent / "hayeong_outputs" / "3d_models"
GEN_TIMEOUT   = 120


# ─────────────────────────────────────────────
# KITCHEN STANDARDS REFERENCE
# Baked into every generation prompt so output
# is architecturally correct by default.
# ─────────────────────────────────────────────

KITCHEN_STANDARDS = """
STANDARD KITCHEN DIMENSIONS (inches — override only if James specifies):
  Base Cabinet          : W varies | H 34.5 | D 24    (countertop brings total to 36")
  Wall Cabinet          : W varies | H 30-42 | D 12   (mount 18" above countertop)
  Sink Base Cabinet     : W 30-36  | H 34.5  | D 24   (NO interior shelf — plumbing clearance)
  Tall / Pantry Cabinet : W 18-24  | H 84-96 | D 24   (full height, multiple shelves)
  Countertop overhang   : 1-1.5" front, flush back
  Toe kick              : H 3.5 | D 3-3.5 (recessed at base of every floor cabinet)
  Door gap              : 0.125" (1/8") all sides
  Drawer height         : typically 5-6" for top drawer, 8-10" for lower drawers
  Shelf thickness       : 0.75" (3/4" plywood standard)
  Cabinet side/back     : 0.75" thick sides, 0.5" back panel
"""


# ─────────────────────────────────────────────
# SKETCHUP RUBY API REFERENCE
# Minimal cheatsheet — enough for clean geometry.
# ─────────────────────────────────────────────

SKETCHUP_RUBY_REFERENCE = """
SKETCHUP RUBY API — KEY PATTERNS:

  # Always wrap in a named operation (enables single undo)
  model = Sketchup.active_model
  ents  = model.active_entities
  model.start_operation("Create Object", true)
  # ... geometry code ...
  model.commit_operation

  # Points (all units in INCHES)
  pt = Geom::Point3d.new(x, y, z)

  # Draw a rectangle face then extrude it (most reliable box method)
  face = ents.add_face(
    Geom::Point3d.new(0,0,0), Geom::Point3d.new(w,0,0),
    Geom::Point3d.new(w,d,0), Geom::Point3d.new(0,d,0)
  )
  face.pushpull(h)   # extrudes upward

  # Groups — use for each logical sub-component
  grp = ents.add_group
  ge  = grp.entities

  # Materials
  mats = model.materials
  mat  = mats.add("WoodOak")
  mat.color = Sketchup::Color.new(180, 140, 90)
  face.material = mat

  # Layers (called "Tags" in newer SketchUp but API still uses Layer)
  layer = model.layers.add("CabinetBody")
  grp.layer = layer

IMPORTANT RULES:
  - Use parametric variables (w, h, d) — never hardcode magic numbers
  - Group every distinct component (body, doors, drawers, toe kick)
  - Apply a basic wood material to visible faces
  - The script must run top-to-bottom in the Ruby console with no user interaction
  - Output ONLY the Ruby script — no markdown fences, no explanation
"""


# ─────────────────────────────────────────────
# OBJ FORMAT REFERENCE
# ─────────────────────────────────────────────

OBJ_REFERENCE = """
OBJ FILE FORMAT — KEY RULES:
  # comment lines start with #
  v x y z           — vertex (coordinates in inches)
  vt u v            — texture coordinate (optional)
  vn x y z          — vertex normal (optional)
  f v1 v2 v3        — triangular face (1-indexed vertex references)
  f v1 v2 v3 v4     — quad face
  g GroupName       — start a named group
  usemtl MatName    — apply material (optional for v1)
  o ObjectName      — object name header

IMPORTANT RULES:
  - Use parametric comments at the top listing all dimensions as variables
  - Group each sub-component (body, doors, drawers, etc.)
  - Faces should be outward-facing (counter-clockwise winding from outside)
  - Output ONLY the OBJ content — no markdown fences, no explanation
  - Add a .mtl file reference line if materials are defined
"""


# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────

def _build_generation_prompt(
    object_type: str,
    description: str,
    output_format: str,
    dimensions: dict,
) -> str:
    dim_str = ""
    if dimensions:
        parts = []
        for k, v in dimensions.items():
            parts.append(f"{k}={v}\"")
        dim_str = f"\nRequested dimensions: {', '.join(parts)}"
        dim_str += "\nUse these dimensions exactly — they override the standards table."

    if output_format == "sketchup_ruby":
        format_ref   = SKETCHUP_RUBY_REFERENCE
        format_instr = (
            "Generate a complete SketchUp Ruby script (.rb) that creates this object.\n"
            "The script will be pasted directly into the SketchUp Ruby console and run."
        )
        output_ext = "rb"
    elif output_format == "obj":
        format_ref   = OBJ_REFERENCE
        format_instr = (
            "Generate a complete OBJ file (.obj) defining this object as plain text.\n"
            "The file will be imported directly into Live Home 3D or Blender."
        )
        output_ext = "obj"
    else:
        format_ref   = SKETCHUP_RUBY_REFERENCE
        format_instr = (
            "Generate a complete SketchUp Ruby script (.rb) that creates this object."
        )
        output_ext = "rb"

    return f"""{format_instr}

OBJECT TYPE: {object_type}
DESCRIPTION: {description}{dim_str}

{KITCHEN_STANDARDS}
{format_ref}

Generate the {output_ext.upper()} now. Output ONLY the file content — nothing else.
"""


# ─────────────────────────────────────────────
# LLM CALL
# ─────────────────────────────────────────────

def _call_llm(prompt: str) -> str | None:
    for model in GEN_MODELS:
        try:
            print(f"[ModelGen] Trying model: {model}...")
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":    model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream":   False,
                },
                timeout=GEN_TIMEOUT,
            )
            if resp.status_code == 200:
                content = resp.json()["message"]["content"].strip()
                print(f"[ModelGen] ✅ Got response from {model} ({len(content)} chars)")
                return content
        except requests.exceptions.ConnectionError:
            print("[ModelGen] Ollama not reachable.")
            return None
        except Exception as e:
            print(f"[ModelGen] {model} failed: {e}")
            continue

    print("[ModelGen] All models failed.")
    return None


# ─────────────────────────────────────────────
# CLEAN & SAVE
# Strip markdown fences if the LLM added them,
# then write to output folder.
# ─────────────────────────────────────────────

def _clean_output(raw: str, ext: str) -> str:
    lines = raw.splitlines()
    # Strip opening fence (```ruby, ```obj, ```, etc.)
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    # Strip closing fence
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _save_output(content: str, object_type: str, ext: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = object_type.replace(" ", "_").lower()
    filename  = f"{safe_type}_{timestamp}.{ext}"
    path      = OUTPUT_DIR / filename
    path.write_text(content, encoding="utf-8")
    print(f"[ModelGen] ✅ Saved to {path}")
    return path


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    decision    = context.get("decision", {})
    speak_fn    = context.get("speak_fn")
    logger      = context.get("logger")

    # ── Extract params from decision dict ──
    object_type   = decision.get("object_type") or "object"
    description   = decision.get("description") or user_input
    output_format = decision.get("output_format", "sketchup_ruby")
    dimensions    = decision.get("dimensions") or {}

    ext = "rb" if output_format in ("sketchup_ruby", "blender_python") else "obj"

    # ── Blender path not yet implemented ──
    if output_format == "blender_python":
        return result(
            success=False,
            speak="Blender Python generation isn't ready yet — I'll use SketchUp Ruby instead.",
            data={"reason": "blender_python_not_implemented"},
        )

    # ── Acknowledge immediately ──
    speak_text = f"Generating the {object_type.replace('_', ' ')}."
    if speak_fn:
        speak_fn(speak_text, emotion="focused")

    # ── Build prompt and call LLM ──
    prompt = _build_generation_prompt(object_type, description, output_format, dimensions)
    raw    = _call_llm(prompt)

    if not raw:
        return result(
            success=False,
            speak="I wasn't able to generate the model — Ollama might not be running.",
            data={"error": "llm_unavailable"},
        )

    # ── Clean and save ──
    clean_content = _clean_output(raw, ext)
    try:
        out_path = _save_output(clean_content, object_type, ext)
    except Exception as e:
        return result(
            success=False,
            speak="I generated the model but couldn't save the file.",
            data={"error": str(e), "content": clean_content[:500]},
        )

    # ── Log ──
    if logger:
        try:
            logger.log_capability_used(
                "model_gen", action="generate",
                outcome="success",
                details={
                    "object_type":   object_type,
                    "output_format": output_format,
                    "file":          str(out_path),
                    "dimensions":    dimensions,
                },
            )
        except Exception:
            pass

    # ── Build context to inject into Hayeong's response ──
    dim_note = ""
    if dimensions:
        parts = [f"{k}={v}\"" for k, v in dimensions.items()]
        dim_note = f"\nDimensions used: {', '.join(parts)}"

    if output_format == "sketchup_ruby":
        instructions = (
            "How James uses this:\n"
            "  1. Open SketchUp\n"
            "  2. Window → Ruby Console\n"
            "  3. Paste the script and press Enter\n"
            "  4. File → Export → 3D Model → choose .obj or .dae\n"
            "  5. Import into Live Home 3D"
        )
    else:
        instructions = (
            "How James uses this:\n"
            "  1. Open Live Home 3D\n"
            "  2. File → Import 3D Object → select the .obj file\n"
            "  (Or open in Blender for editing)"
        )

    response_ctx = (
        f"[3D MODEL GENERATED]\n"
        f"Object: {object_type.replace('_', ' ').title()}\n"
        f"Format: {output_format}\n"
        f"File: {out_path}{dim_note}\n\n"
        f"{instructions}\n\n"
        f"Tell James the model is ready, give him the file path, "
        f"and walk him through how to use it in one or two sentences. "
        f"If he's using it for the kitchen remodel, mention he can ask you to generate "
        f"more objects (wall cabinets, sink base, appliances) when he's ready."
    )

    return result(
        success=True,
        response=response_ctx,
        speak=f"Done. The {object_type.replace('_', ' ')} is ready.",
        emotion="pleased",
        data={
            "file":          str(out_path),
            "object_type":   object_type,
            "output_format": output_format,
            "dimensions":    dimensions,
        },
    )


# ─────────────────────────────────────────────
# LIFECYCLE
# ─────────────────────────────────────────────

def on_load():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[ModelGen] ✅ Loaded — output dir: {OUTPUT_DIR}")


def on_unload():
    pass
