"""Place imported body parts on the selected character."""
import bpy
from mathutils import Matrix, Vector

from .hair import body_surface, object_type
from .library import BODY, BODY_ARMATURE, BODY_OBJECT, TARGET_GROUP, discard_new, load_objects, marked_vertices, topology


def figure_surface(context, selected):
    if selected.type == "MESH":
        return body_surface(context, selected)
    candidates = [obj for obj in context.scene.objects
                  if obj.type == "MESH" and object_type(obj) == "basemesh"
                  and (obj.parent == selected or any(
                      mod.type == "ARMATURE" and mod.object == selected for mod in obj.modifiers))]
    if len(candidates) != 1:
        raise ValueError("Wähle das Körpermesh direkt aus.")
    return body_surface(context, candidates[0])


def transferred_vertex(mesh, metadata):
    index = metadata["vertex"]
    if index is None:
        return None
    if topology(mesh.data) == metadata["topology"]:
        return index
    if not metadata["basemesh"] or object_type(mesh) not in {"proxymesh", "proxymeshes"}:
        return None
    try:
        from bl_ext.blender_org.mpfb.services import ClothesService
        from bl_ext.blender_org.mpfb.entities.clothes.mhclo import Mhclo
        path = ClothesService.find_clothes_absolute_path(mesh)
        if not path:
            return None
        mapping = Mhclo()
        mapping.load(path)
    except (ImportError, OSError, ValueError):
        return None
    if set(mapping.verts) != set(range(len(mesh.data.vertices))):
        return None
    scores = [(sum(weight for vertex, weight in zip(item["verts"], item["weights"])
                   if vertex == index), key) for key, item in mapping.verts.items()]
    best = max(scores, default=(0, None))
    if best[0] > 0 and sum(abs(score - best[0]) < 1e-6 for score, _ in scores) == 1:
        return best[1]
    return None


def evaluated_target(context, mesh, index):
    # Vertex parenting asks Blender to resolve the original vertex through the modifier stack.
    anchor = bpy.data.objects.new("MPFB-Tools · Zielvertex", None)
    context.collection.objects.link(anchor)
    anchor.parent = mesh
    anchor.parent_type = "VERTEX"
    anchor.parent_vertices = (index, index, index)
    anchor.matrix_parent_inverse = Matrix.Identity(4)
    anchor.hide_render = True
    anchor.empty_display_size = .012
    context.view_layer.update()
    evaluated = mesh.evaluated_get(context.evaluated_depsgraph_get())
    group = mesh.vertex_groups[TARGET_GROUP]
    matches = [(weight.weight, vertex.index) for vertex in evaluated.data.vertices
               for weight in vertex.groups if weight.group == group.index and weight.weight > 0]
    best = max(matches, default=(0, None))
    if best[1] is None or sum(abs(weight - best[0]) < 1e-6 for weight, _ in matches) != 1:
        bpy.data.objects.remove(anchor, do_unlink=True)
        return None, None, None
    vertex = evaluated.data.vertices[best[1]]
    position = evaluated.matrix_world @ vertex.co
    normal = evaluated.matrix_world.to_3x3().inverted_safe().transposed() @ vertex.normal
    return anchor, position, normal.normalized() if normal.length_squared > 1e-12 else None


def append_body(context, path, metadata, surface, rig):
    existing = set(bpy.data.user_map())
    created_group = None
    try:
        objects = load_objects(path, BODY)
        mesh = objects[BODY_OBJECT]
        armature = objects.get(BODY_ARMATURE)
        root = armature or mesh
        if armature and mesh.parent != armature:
            # The template may rely on its Armature modifier without object parenting.
            world = mesh.matrix_world.copy()
            mesh.parent = armature
            mesh.matrix_world = world

        world = root.matrix_world.copy()
        root.parent = None
        root.matrix_parent_inverse = Matrix.Identity(4)
        root.matrix_world = world
        for obj in (mesh, armature):
            if obj is not None:
                context.collection.objects.link(obj)

        position, normal, anchor = Vector((0, 0, 0)), None, None
        if TARGET_GROUP in surface.vertex_groups:
            marked = marked_vertices(surface)
            index = marked[0] if len(marked) == 1 else None
        else:
            index = transferred_vertex(surface, metadata)
            if index is not None:
                created_group = surface.vertex_groups.new(name=TARGET_GROUP)
                created_group.add([index], 1, "REPLACE")
        if index is not None:
            anchor, point, normal = evaluated_target(context, surface, index)
            if point is not None:
                position = point

        if normal is not None:
            forward = world.to_3x3() @ Vector((0, -1, 0))
            if forward.length_squared > 1e-12:
                world = forward.normalized().rotation_difference(normal).to_matrix().to_4x4() @ world
        world.translation = position
        root.matrix_world = world
        if armature:
            if anchor:
                bpy.data.objects.remove(anchor, do_unlink=True)
            context.view_layer.update()
            constraint = root.constraints.new("CHILD_OF")
            constraint.name = "MPFB-Tools · Figuren-Rig"
            constraint.target = rig
            constraint.subtarget = metadata["bone"]
            constraint.set_inverse_pending = True
        elif anchor:
            constraint = mesh.constraints.new("COPY_LOCATION")
            constraint.name = "MPFB-Tools · Zielvertex"
            constraint.target = anchor
        context.view_layer.update()
        actual = root.evaluated_get(context.evaluated_depsgraph_get()).matrix_world.translation
        if (actual - position).length > 1e-5:
            raise ValueError("Der Ursprung konnte nicht auf den ausgewerteten Zielpunkt gesetzt werden.")
        discard_new(existing, [mesh, root])
        return mesh
    except Exception:
        if created_group is not None:
            surface.vertex_groups.remove(created_group)
        discard_new(existing)
        raise
