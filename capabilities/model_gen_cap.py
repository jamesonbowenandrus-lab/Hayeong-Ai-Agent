# capabilities/model_gen_cap.py
# 3D model generation capability — OBJ direct output.
#
# Handles: model_gen action from context_router
# Output: .obj + .mtl files saved to hayeong_outputs/3d_models/
#
# Hybrid approach (more reliable than asking LLM to enumerate vertices):
#   Step 1 — LLM generates a JSON geometry spec (parts as boxes with inch dimensions)
#   Step 2 — Python geometry builder converts to meters, writes correct OBJ
#             with outward-facing normals and proper CCW face winding
#   Step 3 — Save and return file path to James
#
# Steps are discrete so a Blender render + vision QC pass can be inserted
# between step 2 and step 3 in a future session.
#
# Unit convention: all LLM spec values are in INCHES. OBJ output is in METERS.
# Live Home 3D reads OBJ units as meters — 34.5 meters is a skyscraper, not a cabinet.
#
# Coordinate system (origin at front-bottom-left of the whole object):
#   x = left → right
#   y = bottom → top
#   z = front → back

import json
import datetime
import requests
import re
from pathlib import Path
from capability_loader import result

ACTIONS = ["model_gen"]

OLLAMA_URL      = "http://localhost:11434/api/chat"
SPEC_MODELS     = ["deepseek-coder-v2:16b", "deepseek-coder:33b", "deepseek-r1:latest"]
OUTPUT_DIR      = Path(__file__).parent.parent / "hayeong_outputs" / "3d_models"
GEN_TIMEOUT     = 120
INCHES_TO_METERS = 0.0254


# ─────────────────────────────────────────────
# KITCHEN STANDARDS
# Baked into spec generation prompt.
# ─────────────────────────────────────────────

KITCHEN_STANDARDS = """
STANDARD KITCHEN DIMENSIONS (inches | meters):
  Base Cabinet        : W varies | H 34.5 (0.876m) | D 24 (0.610m)
  Wall Cabinet        : W varies | H 30-42 (0.762-1.067m) | D 12 (0.305m)
  Sink Base Cabinet   : W 30-36 | H 34.5 (0.876m) | D 24 (0.610m) — NO interior shelf
  Tall/Pantry Cabinet : W 18-24 | H 84-96 (2.134-2.438m) | D 24 (0.610m)
  Toe kick            : H 3.5 (0.089m) | D setback 3.25 from front — always at base
  Panel thickness     : 0.75 (0.019m)
  Door gap reveal     : 0.0625 (0.002m) on all sides
  Drawer height       : 5-6 top drawer, 8-10 lower drawers
"""


# ─────────────────────────────────────────────
# MATERIAL LIBRARY
# Written as a .mtl file alongside the .obj.
# ─────────────────────────────────────────────

MTL_CONTENT = """\
# Hayeong cabinet materials

newmtl cabinet_wood
Ka 0.500 0.350 0.200
Kd 0.600 0.420 0.240
Ks 0.100 0.100 0.100
Ns 15.0

newmtl cabinet_white
Ka 0.940 0.940 0.930
Kd 0.940 0.940 0.930
Ks 0.200 0.200 0.200
Ns 20.0

newmtl cabinet_door
Ka 0.870 0.820 0.750
Kd 0.870 0.820 0.750
Ks 0.150 0.150 0.150
Ns 18.0

newmtl cabinet_dark
Ka 0.180 0.140 0.100
Kd 0.220 0.170 0.120
Ks 0.050 0.050 0.050
Ns 8.0

newmtl hardware_metal
Ka 0.700 0.700 0.720
Kd 0.700 0.700 0.720
Ks 0.500 0.500 0.500
Ns 80.0
"""


# ─────────────────────────────────────────────
# SPEC GENERATION PROMPT
# LLM outputs JSON only — no prose.
# ─────────────────────────────────────────────

SPEC_SYSTEM = f"""\
You are a 3D furniture geometry specification generator.
Given a kitchen object description, output a JSON spec listing every visible part as a box.
Output ONLY valid JSON — no markdown fences, no explanation, no other text.

JSON schema:
{{
  "object_name": "snake_case_name",
  "description": "brief description",
  "parts": [
    {{
      "name": "part_name",
      "x_in": 0.0,
      "y_in": 0.0,
      "z_in": 0.0,
      "width_in": 0.0,
      "height_in": 0.0,
      "depth_in": 0.0,
      "material": "cabinet_wood|cabinet_white|cabinet_door|cabinet_dark|hardware_metal"
    }}
  ]
}}

Coordinate system — origin at front-bottom-left of the whole object:
  x  = left → right (positive = right)
  y  = bottom → top (positive = up)
  z  = front → back (positive = back, into cabinet)

{KITCHEN_STANDARDS}

Part guidelines:
  - body: the outer cabinet shell (full outer dimensions)
  - toe_kick_recess: a thin dark box at the base front to simulate the toe kick recess
    (x=3.25, y=0, z=0, width=body_width-6.5, height=3.5, depth=0.25 — flush with front face)
  - left_door / right_door: thin panels (depth=0.75) positioned on front face (z=-0.75 from front)
    Use z_in = -0.75 so doors sit slightly proud of the body front face.
  - drawer_front: thin panel (depth=0.75) at z=-0.75
  - apron_front: for farmhouse/apron-front sinks — the decorative front panel
  - shelf: interior shelf (omit for sink base — plumbing clearance)
  - Do NOT add hidden interior panels — only exterior visible geometry
  - For sink base cabinets: include body but NO interior shelf
"""


# ─────────────────────────────────────────────
# LLM CALL — SPEC GENERATION
# ─────────────────────────────────────────────

def _generate_spec(object_type: str, description: str, dimensions: dict) -> dict | None:
    dim_note = ""
    if dimensions:
        parts = [f"{k}={v} inches" for k, v in dimensions.items()]
        dim_note = f"\nRequired dimensions: {', '.join(parts)}. Use these exactly."

    user_msg = (
        f"Generate the geometry spec for: {object_type.replace('_', ' ')}\n"
        f"Description: {description}{dim_note}\n"
        f"Output ONLY the JSON spec."
    )

    for model in SPEC_MODELS:
        try:
            print(f"[ModelGen] Generating spec with {model}...")
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":    model,
                    "messages": [
                        {"role": "system", "content": SPEC_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "stream": False,
                },
                timeout=GEN_TIMEOUT,
            )
            if resp.status_code == 200:
                raw = resp.json()["message"]["content"].strip()
                spec = _extract_json(raw)
                if spec and "parts" in spec:
                    print(f"[ModelGen] ✅ Spec from {model}: {len(spec['parts'])} parts")
                    return spec
                else:
                    print(f"[ModelGen] {model} returned unparseable JSON — trying next model")
        except requests.exceptions.ConnectionError:
            print("[ModelGen] Ollama not reachable.")
            return None
        except Exception as e:
            print(f"[ModelGen] {model} failed: {e}")

    print("[ModelGen] All spec models failed.")
    return None


def _extract_json(raw: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences and surrounding prose."""
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw.strip(), flags=re.MULTILINE)
    raw = raw.strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting first {...} block
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# ─────────────────────────────────────────────
# OBJ GEOMETRY BUILDER
# Converts JSON spec (inches) → OBJ text (meters).
#
# Face winding: counter-clockwise from outside (right-hand rule).
# Outward normals computed per face — no ambiguity for importers.
#
# Vertex layout for box at (ox,oy,oz) size (w,h,d):
#   1: (ox,    oy,    oz   )  left-bottom-front
#   2: (ox+w,  oy,    oz   )  right-bottom-front
#   3: (ox+w,  oy+h,  oz   )  right-top-front
#   4: (ox,    oy+h,  oz   )  left-top-front
#   5: (ox,    oy,    oz+d )  left-bottom-back
#   6: (ox+w,  oy,    oz+d )  right-bottom-back
#   7: (ox+w,  oy+h,  oz+d )  right-top-back
#   8: (ox,    oy+h,  oz+d )  left-top-back
#
# Face order (with CCW winding and outward normals verified by cross product):
#   Front  (-Z): 1 4 3 2   normal (0,0,-1)
#   Back   (+Z): 5 6 7 8   normal (0,0,+1)
#   Left   (-X): 1 5 8 4   normal (-1,0,0)
#   Right  (+X): 2 3 7 6   normal (+1,0,0)
#   Bottom (-Y): 1 2 6 5   normal (0,-1,0)
#   Top    (+Y): 4 8 7 3   normal (0,+1,0)
# ─────────────────────────────────────────────

# Global vertex normals — defined once, indexed 1-6
OBJ_NORMALS = [
    "vn  0.0000  0.0000 -1.0000",   # n1: Front
    "vn  0.0000  0.0000  1.0000",   # n2: Back
    "vn -1.0000  0.0000  0.0000",   # n3: Left
    "vn  1.0000  0.0000  0.0000",   # n4: Right
    "vn  0.0000 -1.0000  0.0000",   # n5: Bottom
    "vn  0.0000  1.0000  0.0000",   # n6: Top
]


def _box_lines(part: dict, v_off: int) -> list[str]:
    """Return OBJ lines for one box part. v_off = vertex count before this part."""
    name = part["name"]
    ox = part.get("x_in", 0) * INCHES_TO_METERS
    oy = part.get("y_in", 0) * INCHES_TO_METERS
    oz = part.get("z_in", 0) * INCHES_TO_METERS
    w  = max(part["width_in"],  0.001) * INCHES_TO_METERS
    h  = max(part["height_in"], 0.001) * INCHES_TO_METERS
    d  = max(part["depth_in"],  0.001) * INCHES_TO_METERS
    mat = part.get("material", "cabinet_wood")

    lines = [f"\ng {name}", f"usemtl {mat}"]

    # 8 vertices
    for vx, vy, vz in [
        (ox,    oy,    oz   ),  # 1
        (ox+w,  oy,    oz   ),  # 2
        (ox+w,  oy+h,  oz   ),  # 3
        (ox,    oy+h,  oz   ),  # 4
        (ox,    oy,    oz+d ),  # 5
        (ox+w,  oy,    oz+d ),  # 6
        (ox+w,  oy+h,  oz+d ),  # 7
        (ox,    oy+h,  oz+d ),  # 8
    ]:
        lines.append(f"v {vx:.6f} {vy:.6f} {vz:.6f}")

    # 6 faces — (v1, v2, v3, v4, normal_index)
    o = v_off
    for v1, v2, v3, v4, ni in [
        (o+1, o+4, o+3, o+2, 1),   # Front
        (o+5, o+6, o+7, o+8, 2),   # Back
        (o+1, o+5, o+8, o+4, 3),   # Left
        (o+2, o+3, o+7, o+6, 4),   # Right
        (o+1, o+2, o+6, o+5, 5),   # Bottom
        (o+4, o+8, o+7, o+3, 6),   # Top
    ]:
        lines.append(f"f {v1}//{ni} {v2}//{ni} {v3}//{ni} {v4}//{ni}")

    return lines


def _build_obj(spec: dict, mtl_filename: str) -> str:
    """Build a complete OBJ file string from a geometry spec."""
    obj_name  = spec.get("object_name", "object")
    desc      = spec.get("description", "")
    parts     = spec.get("parts", [])
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# {obj_name}",
        f"# {desc}",
        f"# Generated by Hayeong — {timestamp}",
        f"# Units: meters (Live Home 3D reads OBJ as meters)",
        f"#",
        f"mtllib {mtl_filename}",
        "",
        f"o {obj_name}",
        "",
    ]

    lines += OBJ_NORMALS
    lines.append("")

    v_count = 0
    for part in parts:
        lines += _box_lines(part, v_count)
        v_count += 8

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────

def _save(obj_text: str, mtl_text: str, object_type: str) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe      = object_type.replace(" ", "_").lower()
    obj_path  = OUTPUT_DIR / f"{safe}_{timestamp}.obj"
    mtl_path  = OUTPUT_DIR / f"{safe}_{timestamp}.mtl"
    obj_path.write_text(obj_text, encoding="utf-8")
    mtl_path.write_text(mtl_text, encoding="utf-8")
    print(f"[ModelGen] ✅ Saved: {obj_path}")
    return obj_path, mtl_path


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    decision = context.get("decision", {})
    speak_fn = context.get("speak_fn")
    logger   = context.get("logger")

    object_type = decision.get("object_type") or "object"
    description = decision.get("description") or user_input
    dimensions  = decision.get("dimensions") or {}

    # output_format — only 'obj' supported here; blender_python routes to blender_gen_cap
    output_format = decision.get("output_format", "obj")
    if output_format == "sketchup_ruby":
        return result(
            success=False,
            speak=(
                "SketchUp Ruby requires a Pro license — that path is eliminated. "
                "I'll generate an OBJ file you can import directly into Live Home 3D instead. "
                "Ask me again and I'll use the OBJ path."
            ),
            data={"reason": "sketchup_ruby_eliminated"},
        )
    if output_format == "blender_python":
        return result(
            success=False,
            speak="Use the blender_gen action for Blender Python output.",
            data={"reason": "wrong_capability"},
        )

    # Acknowledge
    label = object_type.replace("_", " ")
    if speak_fn:
        speak_fn(f"Generating the {label}.", emotion="focused")

    # Step 1 — LLM generates geometry spec
    spec = _generate_spec(object_type, description, dimensions)
    if not spec:
        return result(
            success=False,
            speak="I couldn't generate the geometry spec — Ollama may not be running.",
            data={"error": "spec_generation_failed"},
        )

    # Step 2 — Python builds OBJ
    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    mtl_name    = f"{object_type.replace(' ', '_').lower()}_{timestamp}.mtl"
    obj_text    = _build_obj(spec, mtl_name)

    # Step 3 — Save
    try:
        obj_path, mtl_path = _save(obj_text, MTL_CONTENT, object_type)
    except Exception as e:
        return result(
            success=False,
            speak="I built the geometry but couldn't save the file.",
            data={"error": str(e)},
        )

    # Log
    if logger:
        try:
            logger.log_capability_used(
                "model_gen", action="generate", outcome="success",
                details={
                    "object_type": object_type,
                    "parts":       len(spec.get("parts", [])),
                    "file":        str(obj_path),
                },
            )
        except Exception:
            pass

    # Build response context
    parts_list = ", ".join(p["name"] for p in spec.get("parts", []))
    dim_note   = ""
    if dimensions:
        dim_note = "\nDimensions: " + ", ".join(f"{k}={v}\"" for k, v in dimensions.items())

    response_ctx = (
        f"[3D MODEL GENERATED]\n"
        f"Object: {spec.get('object_name', object_type)}\n"
        f"Parts: {parts_list}\n"
        f"OBJ file: {obj_path}\n"
        f"MTL file: {mtl_path}{dim_note}\n\n"
        f"How James imports it into Live Home 3D:\n"
        f"  1. File → Import → 3D Object\n"
        f"  2. Select: {obj_path.name}\n"
        f"  3. Object appears in scene ready to place\n\n"
        f"Tell James the file is ready and give him the filename. "
        f"Mention he can ask for more objects — wall cabinets, sink base, appliances. "
        f"If something looks off after import (proportions, scale), tell him to let you know "
        f"and you can adjust the spec and regenerate."
    )

    return result(
        success=True,
        response=response_ctx,
        speak=f"Done — the {label} is ready to import.",
        emotion="pleased",
        data={
            "obj_path":    str(obj_path),
            "mtl_path":    str(mtl_path),
            "object_type": object_type,
            "parts":       len(spec.get("parts", [])),
            "spec":        spec,
        },
    )


# ─────────────────────────────────────────────
# LIFECYCLE
# ─────────────────────────────────────────────

def on_load():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[ModelGen] ✅ Loaded — output: {OUTPUT_DIR}")


def on_unload():
    pass
