import bpy
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()
bpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,0))
bpy.context.active_object.name = "MyCube"
bpy.context.active_object.color = (1, 0, 0, 1)
print("HAYEONG_OK: done")

import bpy
bpy.ops.export_scene.gltf(filepath=r"H:/hayeong/Logs/outputs/blender/red_cube.glb", export_format='GLB', use_selection=False)
print("HAYEONG_EXPORT_OK: H:/hayeong/Logs/outputs/blender/red_cube.glb")