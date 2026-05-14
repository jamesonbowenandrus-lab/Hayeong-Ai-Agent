# Toolbox/blender

3D generation and rendering via Blender Python scripting. Hayeong writes a bpy
script, the pipeline runs Blender headless, and the output file is saved to
`Logs/outputs/blender/`.

## Files

- `blender_tool.py` — main tool, `run()` function, registered in `registry.json`
- `blender_prompt.txt` — domain prompt for the reasoning LLM when planning Blender tasks
- `scripts/` — generated bpy scripts are written here before execution; logs saved alongside

## How It Works

The reasoning LLM writes the bpy scene creation script. The pipeline:
1. Appends an export call (so the LLM doesn't need to get the output path right)
2. Writes the full script to `scripts/gen_TIMESTAMP.py`
3. Runs `blender --background --python gen_TIMESTAMP.py`
4. Checks for output file; returns path on success, log tail on failure

## Calling This Tool

    action: blender
    params:
      blender_script=[full bpy Python script]
      output_filename=my_model.glb
      export_format=glb
      timeout=120

Supported export formats: `glb`, `blend`, `stl`, `fbx`

## Configuration

Blender path is set in `Brain/config.py`:

    BLENDER_PATH   = "H:/blender/blender.exe"
    BLENDER_OUTPUT = "Logs/outputs/blender"

## Rules for LLM-Written Scripts

- Always start with `import bpy`
- Clear the scene first: `bpy.ops.object.select_all(action='SELECT')` then `bpy.ops.object.delete()`
- Do NOT include an export call — the pipeline appends this automatically
- Keep scripts self-contained — no external imports beyond `bpy` and `math`
