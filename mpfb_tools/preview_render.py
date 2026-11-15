"""Render one library thumbnail in an isolated Blender process."""

import sys

import bpy
from mathutils import Vector


def render_preview(filepath, object_name, output, mode="object"):
    scene = bpy.context.scene
    bpy.data.batch_remove(list(bpy.data.objects))
    with bpy.data.libraries.load(filepath, link=False) as (source, destination):
        if mode == "collection":
            destination.collections = [object_name]
        else:
            destination.objects = [object_name]
    if mode == "collection":
        collection = destination.collections[0]
        scene.collection.children.link(collection)
        subjects = [obj for obj in collection.all_objects
                    if obj.type in {"MESH", "CURVES"} and not obj.hide_render]
    else:
        obj = destination.objects[0]
        scene.collection.objects.link(obj)
        subjects = [obj]
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" or (mode == "groom" and modifier.type == "NODES"
                    and modifier.node_group and any(node.bl_idname == "GeometryNodeDeformCurvesOnSurface"
                                                    for node in modifier.node_group.nodes)):
                modifier.show_viewport = False
                modifier.show_render = False
        if mode == "groom":
            reference = obj.get("mpfb_tools_hair_bound_mesh")
            if reference:
                skin = bpy.data.objects.new("Vorschaufigur", reference)
                scene.collection.objects.link(skin)
                material = bpy.data.materials.new("Haut")
                material.diffuse_color = (.43, .28, .21, 1)
                reference.materials.append(material)

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera = bpy.data.objects.new("Vorschaukamera", bpy.data.cameras.new("Vorschaukamera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    direction = Vector((1.5, -2.6, .73 if mode != "object" else 1.3)).normalized()
    orientation = (-direction).to_track_quat("-Z", "Y")
    camera.rotation_euler = orientation.to_euler()
    camera_frame = orientation.inverted().to_matrix().to_4x4()
    points = []
    for obj in subjects:
        evaluated = obj.evaluated_get(depsgraph)
        local = camera_frame @ evaluated.matrix_world
        if evaluated.type == "MESH":
            points.extend(local @ vertex.co for vertex in evaluated.data.vertices)
        else:
            points.extend(local @ Vector(corner) for corner in evaluated.bound_box)
    if not points:
        raise ValueError("Die Vorlage enthält keine sichtbare Geometrie.")
    low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    center = orientation @ ((low + high) * .5)
    span = high - low
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(max(span.x, span.y) * 1.06, .001)
    distance = max(span.length * 2, .01)
    camera.location = center + direction * distance
    camera.data.clip_start = distance * .001
    camera.data.clip_end = distance * 4

    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = "BOTH"
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.filepath = output
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    render_preview(*sys.argv[sys.argv.index("--") + 1:])
