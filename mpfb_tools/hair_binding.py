"""Transfer existing strands between the MPFB base mesh and topology assets."""

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .hair import object_type, patch_mesh, region_weights


BASE = "mpfb_tools_hair_base"
MESH = "mpfb_tools_hair_bound_mesh"
MATRIX = "mpfb_tools_hair_bound_matrix"
CURVE_MATRIX = "mpfb_tools_hair_curve_matrix"
SKIN = "mpfb_tools_hair_skin_group"
REGION = "mpfb_tools_hair_region"
PATCH = "mpfb_tools_hair_surface"
TRIANGLE = "mpfb_tools_hair_base_triangle"
WEIGHTS = "mpfb_tools_hair_base_weights"
ROOT = "mpfb_tools_hair_bound_root"
PROXIES = {"proxymesh", "proxymeshes"}
_errors = {}


def skin_group(source):
    group = source.vertex_groups.get("body")
    return group.index if group is not None else -1


def body_for(scene, surface):
    if object_type(surface) == "basemesh":
        return surface
    if object_type(surface) not in PROXIES:
        return None
    parent = surface.parent
    if parent is None:
        return None
    if object_type(parent) == "basemesh":
        return parent
    bodies = [obj for obj in scene.objects
              if obj.type == "MESH" and obj.parent == parent and object_type(obj) == "basemesh"]
    return bodies[0] if len(bodies) == 1 else None


def mesh_surface(curves):
    surface = curves.data.surface
    return surface.parent if surface is not None and surface.get(PATCH) else surface


def remember_binding(scene, curves):
    source = mesh_surface(curves)
    if source is None:
        return
    base = body_for(scene, source)
    if base is None:
        return
    _remember(curves, base, source)


def _remember(curves, base, source, *, rebound=False):
    # Keep the Mesh ID alive when MPFB deletes the proxy Object on unequip.
    curves[BASE] = base
    curves[MESH] = source.data
    _store_frames(curves, base, source, source.matrix_world if rebound else curves.matrix_world)
    curves[SKIN] = skin_group(source)


def _store_frames(curves, base, source, world):
    inverse = base.matrix_world.inverted_safe()
    for name, matrix in ((MATRIX, inverse @ source.matrix_world), (CURVE_MATRIX, inverse @ world)):
        values = [value for row in matrix for value in row]
        previous = curves.get(name)
        if previous is None or any(abs(a - b) > 1e-7 for a, b in zip(values, previous)):
            curves[name] = values


def stored_matrix(obj, property_name):
    values = obj[property_name]
    return Matrix([values[i:i+4] for i in range(0, 16, 4)])


def fitted_vertices(source, raw):
    keys = source.data.shape_keys
    if keys is None or len(keys.key_blocks) < 2:
        return raw
    # MPFB fits proxies from this same shape-key mix, before posing or masking.
    active = source.active_shape_key_index
    key = source.shape_key_add(name="MPFB-Tools · Bindung", from_mix=True)
    try:
        coords = np.empty(len(raw) * 3, dtype=np.float32)
        key.data.foreach_get("co", coords)
        return coords.reshape(-1, 3)
    finally:
        source.shape_key_remove(key)
        source.active_shape_key_index = active


def barycentric(point, a, b, c):
    u, v, w = b - a, c - a, point - a
    uu, uv, vv = u.dot(u), u.dot(v), v.dot(v)
    denominator = uu * vv - uv * uv
    if denominator <= 1e-23:
        return 1.0, 0.0, 0.0
    q = (vv * u.dot(w) - uv * v.dot(w)) / denominator
    r = (uu * v.dot(w) - uv * u.dot(w)) / denominator
    return 1.0 - q - r, q, r


def interpolate(values, weights):
    a, b, c = values
    u, v, w = weights
    return a * u + b * v + c * w


class Surface:
    def __init__(self, mesh, matrix, group, obj=None):
        mesh.calc_loop_triangles()
        if group >= 0:
            skin = {v.index for v in mesh.vertices
                    if any(g.group == group and g.weight > 0 for g in v.groups)}
        else:
            skin = None
        triangles = [t for t in mesh.loop_triangles
                     if skin is None or all(i in skin for i in t.vertices)]
        if not triangles:
            raise ValueError("Das Figurenmesh enthält keine Hautflächen für die Haarbindung.")
        self.faces = [tuple(t.vertices) for t in triangles]
        self.loops = [tuple(t.loops) for t in triangles]
        self.matrix = matrix
        self.mesh = mesh
        coords = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", coords)
        raw = coords.reshape(-1, 3)
        fitted = fitted_vertices(obj, raw) if obj is not None else raw
        self.raw = [matrix @ Vector(p) for p in raw]
        self.fitted = self.raw if fitted is raw else [matrix @ Vector(p) for p in fitted]
        self.raw_tree = BVHTree.FromPolygons(self.raw, self.faces, all_triangles=True)
        self.fitted_tree = (self.raw_tree if self.fitted is self.raw
                            else BVHTree.FromPolygons(self.fitted, self.faces, all_triangles=True))
        self.raw_normals = self._normals(self.raw)
        self.fitted_normals = self.raw_normals if self.fitted is self.raw else self._normals(self.fitted)
        z = [p.z for p in self.raw]
        self.tolerance = (max(z) - min(z)) * .045

    def _normals(self, coords):
        points = np.array(coords, dtype=np.float32)
        indices = np.array(self.faces, dtype=np.int32)
        a, b, c = (points[indices[:, i]] for i in range(3))
        face_normals = np.cross(b - a, c - a)
        normals = np.zeros_like(points)
        for i in range(3):
            np.add.at(normals, indices[:, i], face_normals)
        return [Vector(n).normalized() for n in normals]

    def values(self, coords, triangle):
        return (coords[i] for i in self.faces[triangle])

    def normal(self, triangle, weights, *, fitted=False):
        coords = self.fitted_normals if fitted else self.raw_normals
        return interpolate(self.values(coords, triangle), weights).normalized()

    def locate(self, point, *, fitted=False, normal=None, allowed=None):
        points = self.fitted if fitted else self.raw
        tree = self.fitted_tree if fitted else self.raw_tree
        hit, facing, i, distance = tree.find_nearest(point, self.tolerance)
        if i is not None and ((normal is not None and facing.dot(normal) < .55)
                              or (allowed is not None and not allowed[i])):
            candidates = tree.find_nearest_range(point, min(self.tolerance, distance + self.tolerance * .21))
            hit, facing, i, distance = min(
                ((p, n, idx, d) for p, n, idx, d in candidates
                 if allowed is None or allowed[idx]),
                key=lambda item: item[3] + (0 if normal is None else
                                           (1 - item[1].dot(normal)) * self.tolerance * .12),
                default=(None, None, None, None),
            )
        if i is None:
            raise ValueError("Mindestens eine Haarwurzel konnte keiner Hautfläche zugeordnet werden.")
        return i, barycentric(hit, *self.values(points, i))

    def uv_values(self, uv):
        layer = self.mesh.uv_layers.get(uv)
        if layer is None:
            raise ValueError(f'Die UV-Map „{uv}“ fehlt auf dem Zielmesh.')
        return [entry.uv.copy() for entry in layer.data]


def read_attribute(data, name, field, shape, dtype):
    attr = data.attributes.get(name)
    if attr is None:
        return None
    values = np.empty(shape, dtype=dtype)
    attr.data.foreach_get(field, values.ravel())
    return values


def write_attribute(data, name, kind, field, values):
    attr = data.attributes.get(name)
    if attr is None:
        attr = data.attributes.new(name, kind, "CURVE")
    attr.data.foreach_set(field, values.ravel())


def transfer(curves, source, base, target, frame, uv_name, allowed):
    data = curves.data
    count = len(data.curves)
    if not count:
        return None
    sizes = np.array([len(c.points) for c in data.curves], dtype=np.int32)
    starts = np.cumsum(sizes) - sizes
    points = read_attribute(data, "position", "vector", (len(data.points), 3), np.float32)
    old_roots = points[starts]
    previous = read_attribute(data, ROOT, "vector", (count, 3), np.float32)
    triangles = read_attribute(data, TRIANGLE, "value", count, np.int32)
    weights = read_attribute(data, WEIGHTS, "vector", (count, 3), np.float32)
    if previous is None or triangles is None or weights is None:
        previous = np.full_like(old_roots, np.nan)
        triangles = np.zeros(count, dtype=np.int32)
        weights = np.zeros((count, 3), dtype=np.float32)
    same_roots = np.all(np.abs(previous - old_roots) < 1e-6, axis=1)
    roots = np.empty_like(old_roots)
    lookup = target.uv_values(uv_name)
    uv = np.empty((count, 2), dtype=np.float32)
    rotations = np.empty((count, 3, 3), dtype=np.float32)
    to_local = target.matrix.inverted_safe()
    linear = frame.to_3x3()
    inverse_linear = to_local.to_3x3()

    for i in range(count):
        root = frame @ Vector(old_roots[i])
        src_id, src_w = source.locate(root)
        source_normal = source.normal(src_id, src_w)
        if not same_roots[i] or not 0 <= triangles[i] < len(base.faces):
            if source is base:
                triangles[i], weights[i] = src_id, src_w
            else:
                fitted_root = interpolate(source.values(source.fitted, src_id), src_w)
                triangles[i], weights[i] = base.locate(
                    fitted_root, fitted=True, normal=source.normal(src_id, src_w, fitted=True))
        triangle, w = int(triangles[i]), weights[i]
        neutral_normal = base.normal(triangle, w, fitted=True)
        if target is base and allowed is None:
            target_id, target_w = triangle, w
        else:
            fit = interpolate(base.values(base.fitted, triangle), w)
            target_id, target_w = target.locate(fit, fitted=True, normal=neutral_normal, allowed=allowed)
        target_normal = target.normal(target_id, target_w)
        on_surface = interpolate(target.values(target.raw, target_id), target_w)
        roots[i] = to_local @ (on_surface - target_normal * target.tolerance * .0013)
        uv[i] = interpolate((lookup[k] for k in target.loops[target_id]), target_w)
        into_neutral = source_normal.rotation_difference(neutral_normal)
        out_of_neutral = neutral_normal.rotation_difference(target_normal)
        rotations[i] = inverse_linear @ (out_of_neutral @ into_neutral).to_matrix() @ linear

    owner = np.repeat(np.arange(count), sizes)
    points = roots[owner] + np.einsum("nij,nj->ni", rotations[owner], points - old_roots[owner])
    return points, uv, roots, triangles, weights


def apply_transfer(obj, destination, uv_name, result):
    if obj.data.users > 1 or obj.data.library:
        obj.data = obj.data.copy()
    data = obj.data
    if result is not None:
        points, uv, roots, triangles, weights = result
        data.attributes["position"].data.foreach_set("vector", points.ravel())
        write_attribute(data, "surface_uv_coordinate", "FLOAT2", "vector", uv)
        write_attribute(data, ROOT, "FLOAT_VECTOR", "vector", roots)
        write_attribute(data, TRIANGLE, "INT", "value", triangles)
        write_attribute(data, WEIGHTS, "FLOAT_VECTOR", "vector", weights)
    obj.parent = destination
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.matrix_basis = Matrix.Identity(4)
    data.surface = destination
    data.surface_uv_map = uv_name
    obj.update_tag()


def topology_patch(patch):
    for modifier in patch.modifiers:
        if modifier.type != "NODES" or modifier.node_group is None:
            continue
        nodes = modifier.node_group.nodes
        source = next((n for n in nodes if n.bl_idname == "GeometryNodeObjectInfo"), None)
        mask = next((n for n in nodes if n.bl_idname == "GeometryNodeInputNamedAttribute"), None)
        if source and mask:
            attribute = mask.inputs["Name"].default_value
            region = patch.get(REGION, {"mpfb_tools_haare": "__HAARE",
                                        "mpfb_tools_bart": "__BART"}.get(attribute))
            if region:
                return source.inputs["Object"], attribute, region
    raise ValueError(f'Die Haarfläche „{patch.name}“ konnte nicht zugeordnet werden.')


def move_patch(patch, target, weights, source_input, name):
    values = [all(i in weights for i in p.vertices) for p in target.data.polygons]
    if not any(values):
        raise ValueError(f'Für „{patch.name}“ wurde keine passende Haarfläche gefunden.')
    attr = target.data.attributes.get(name)
    if attr is None:
        attr = target.data.attributes.new(name, "BOOLEAN", "FACE")
    attr.data.foreach_set("value", values)
    old = patch.data
    patch.data = patch_mesh(target, weights)
    if old.users == 0:
        bpy.data.meshes.remove(old)
    patch.parent = target
    patch.matrix_parent_inverse = Matrix.Identity(4)
    patch.matrix_basis = Matrix.Identity(4)
    source_input.default_value = target
    patch.update_tag()


def sync_scene(scene):
    objects = list(scene.objects)
    targets = {}
    for obj in objects:
        if obj.type == "MESH" and object_type(obj) in PROXIES:
            base = body_for(scene, obj)
            if base is not None:
                targets.setdefault(base, []).append(obj)
    surfaces = {}
    masks = {}
    moved_patches = set()

    def surface(base, obj=None, reference=None):
        if obj is not None:
            mesh = obj.data
            frame = base.matrix_world.inverted_safe() @ obj.matrix_world
            group = skin_group(obj)
        else:
            mesh = reference.get(MESH)
            frame = stored_matrix(reference, MATRIX)
            group = reference.get(SKIN, -1)
        key = (base, mesh, obj)
        if key not in surfaces:
            surfaces[key] = Surface(mesh, frame, group, obj)
        return surfaces[key]

    tracked = []
    for curves in objects:
        if curves.type != "CURVES" or curves.library or curves.mode != "OBJECT":
            continue
        patch = curves.data.surface
        if patch is not None and not patch.get(PATCH):
            patch = None
        source = mesh_surface(curves)
        base = (body_for(scene, source) if source is not None else None) or curves.get(BASE)
        if base is None or base.name not in scene.objects:
            continue
        tracked.append((curves, patch, source, base, curves.matrix_world.copy()))

    failures = []
    for curves, patch, source, base, world in tracked:
        old_mesh = curves.get(MESH)
        candidates = targets.get(base, [])
        visible = [obj for obj in candidates if obj.visible_get(view_layer=scene.view_layers[0])]
        target = (visible or candidates or [base])[-1]
        if source == target:
            if old_mesh != target.data or curves.get(BASE) != base:
                _remember(curves, base, target)
            else:
                _store_frames(curves, base, target, world)
            continue
        if source is None and old_mesh is None:
            failures.append(f'„{curves.name}“: Die bisherige Oberfläche fehlt.')
            continue
        if target.mode != "OBJECT" or base.mode != "OBJECT":
            continue
        try:
            uv_layer = target.data.uv_layers.active
            if uv_layer is None:
                raise ValueError("Das neue Figurenmesh braucht eine aktive UV-Map.")
            if source is not None:
                source_surface = surface(base, source)
                frame = base.matrix_world.inverted_safe() @ world
            else:
                source_surface = surface(base, reference=curves)
                frame = stored_matrix(curves, CURVE_MATRIX if CURVE_MATRIX in curves else MATRIX)
            base_surface = surface(base, base)
            target_surface = surface(base, target)
            allowed = None
            if patch is not None:
                socket, attribute, region = topology_patch(patch)
                if target not in masks:
                    masks[target] = region_weights(target)
                weights = masks[target][region]
                allowed = [all(i in weights for i in face) for face in target_surface.faces]
            result = transfer(curves, source_surface, base_surface, target_surface, frame, uv_layer.name, allowed)
            if patch is not None and patch not in moved_patches:
                move_patch(patch, target, weights, socket, attribute)
                moved_patches.add(patch)
            target.add_rest_position_attribute = True
            apply_transfer(curves, patch if patch is not None else target, uv_layer.name, result)
            _remember(curves, base, target, rebound=True)
            if target == base and not candidates:
                for mod in base.modifiers:
                    if (mod.type == "MASK" and mod.name.split(".")[0] == "Hide base mesh"
                            and mod.invert_vertex_group and mod.vertex_group == "body"):
                        mod.show_viewport = mod.show_render = False
        except (OSError, RuntimeError, ValueError) as error:
            failures.append(f'„{curves.name}“: {error}')
    key = scene.as_pointer()
    if failures:
        if _errors.get(key) != failures:
            print("MPFB-Tools · Haarbindung:", " | ".join(failures))
        _errors[key] = failures
    else:
        _errors.pop(key, None)
    return failures


def binding_errors(scene):
    return _errors.get(scene.as_pointer(), ())


def _sync():
    if bpy.context.scene is not None:
        sync_scene(bpy.context.scene)


def _schedule():
    if not bpy.app.timers.is_registered(_sync):
        bpy.app.timers.register(_sync, first_interval=.15)


@persistent
def _update(scene, depsgraph):
    if any(isinstance(update.id, (bpy.types.Object, bpy.types.Scene, bpy.types.Collection))
           for update in depsgraph.updates):
        _schedule()


@persistent
def _after_file_change(_):
    _errors.clear()
    _schedule()


def register():
    bpy.app.handlers.depsgraph_update_post.append(_update)
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        handlers.append(_after_file_change)
    _schedule()


def unregister():
    if bpy.app.timers.is_registered(_sync):
        bpy.app.timers.unregister(_sync)
    bpy.app.handlers.depsgraph_update_post.remove(_update)
    for handlers in (bpy.app.handlers.load_post, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        handlers.remove(_after_file_change)
    _errors.clear()
