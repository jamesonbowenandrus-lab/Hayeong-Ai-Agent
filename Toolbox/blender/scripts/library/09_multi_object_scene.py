"""
09_multi_object_scene.py — Skill library reference
Demonstrates building a scene with multiple objects, each with their own material.
Pattern: create object → name it → create material → assign to object.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy


def make_material(name, r, g, b, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Roughness"].default_value  = roughness
    bsdf.inputs["Metallic"].default_value   = metallic
    return mat


def assign_material(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Floor ─────────────────────────────────────────────────────────────
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = "Floor"
assign_material(floor, make_material("Mat_Floor", 0.8, 0.8, 0.75, roughness=0.9))

# ── Red box ───────────────────────────────────────────────────────────
bpy.ops.mesh.primitive_cube_add(size=1.5, location=(-2, 0, 0.75))
box = bpy.context.active_object
box.name = "Box_Red"
assign_material(box, make_material("Mat_Red", 0.8, 0.15, 0.1, roughness=0.3))

# ── Blue sphere ───────────────────────────────────────────────────────
bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(2, 0, 1.0))
sph = bpy.context.active_object
sph.name = "Sphere_Blue"
bpy.ops.object.shade_smooth()
assign_material(sph, make_material("Mat_Blue", 0.1, 0.3, 0.85, roughness=0.15, metallic=0.2))

# ── Gold cylinder ─────────────────────────────────────────────────────
bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.5, depth=2.0, location=(0, 2, 1.0))
cyl = bpy.context.active_object
cyl.name = "Cylinder_Gold"
bpy.ops.object.shade_smooth()
assign_material(cyl, make_material("Mat_Gold", 1.0, 0.75, 0.1, roughness=0.2, metallic=0.9))

print("HAYEONG_OK: multi-object scene created (floor + box + sphere + cylinder)")
