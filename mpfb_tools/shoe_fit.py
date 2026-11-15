"""Fit each shoe to the unposed shape of the corresponding MPFB foot."""

import gzip
from pathlib import Path

from mathutils.bvhtree import BVHTree

import bpy
import numpy as np

from .hair import object_type


REFERENCE = "mpfb_tools_foot_reference"
SURFACE = "mpfb_tools_foot_surface"
FIT_KEY = "MPFB-Tools · Fußgröße"


def body_for_rig(context, rig):
    bodies = [
        obj for obj in context.scene.objects
        if obj.type == "MESH" and object_type(obj) == "basemesh"
        and (obj.parent == rig or any(m.type == "ARMATURE" and m.object == rig for m in obj.modifiers))
    ]
    if len(bodies) != 1:
        raise ValueError("Für die Schuhpassform wird genau ein MPFB-Körper am Zielrig benötigt.")
    return bodies[0]


def rig_coordinates(obj, rig):
    if obj.parent == rig and obj.parent_type == "OBJECT":
        return obj.matrix_parent_inverse @ obj.matrix_basis
    return rig.matrix_world.inverted() @ obj.matrix_world


def transform(points, matrix):
    values = np.array(matrix)
    return points @ values[:3, :3].T + values[:3, 3]


def foot_geometry(body, rig):
    from bl_ext.blender_org.mpfb.services import LocationService

    target_dir = Path(LocationService.get_mpfb_data("targets")) / "feet"
    if len(body.data.vertices) != 19158:
        raise ValueError("Für die Fußmaße wird das vollständige MPFB-Basemesh benötigt.")
    temporary = body.shape_key_add(name="MPFB-Tools · Maße", from_mix=True) if body.data.shape_keys else None
    try:
        points = np.empty(len(body.data.vertices) * 3, dtype=np.float32)
        (temporary.data if temporary else body.data.vertices).foreach_get("co", points)
        points = transform(points.reshape(-1, 3), rig_coordinates(body, rig))
    finally:
        if temporary:
            body.shape_key_remove(temporary)

    foot_ids = []
    frames = []
    for side in ("l", "r"):
        ids = set()
        for direction in ("decr", "incr"):
            path = target_dir / f"{side}-foot-scale-{direction}.target.gz"
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                ids.update(int(line.split()[0]) for line in stream if line.strip() and not line.startswith("#"))
        foot_ids.append(ids)
        foot = points[sorted(ids)]
        low = foot.min(axis=0)
        high = foot.max(axis=0)
        frames.extend(((low + high) * .5, high - low))
    return points, np.array(frames), foot_ids


def store_reference(shoes, body, rig):
    points, frames, foot_ids = foot_geometry(body, rig)
    group = body.vertex_groups.get("body")
    if group is None:
        raise ValueError("Die MPFB-Referenz braucht die Vertex-Gruppe „body“.")
    skin = {v.index for v in body.data.vertices
            if any(w.group == group.index and w.weight > 0 for w in v.groups)}
    body.data.calc_loop_triangles()
    parts = []
    for ids in foot_ids:
        triangles = [tuple(tri.vertices) for tri in body.data.loop_triangles
                     if all(index in skin for index in tri.vertices)
                     and any(index in ids for index in tri.vertices)]
        indices = sorted({index for tri in triangles for index in tri})
        if not indices:
            raise ValueError("Die Referenz enthält keine Fußoberfläche.")
        lookup = {index: i for i, index in enumerate(indices)}
        parts.append(dict(indices=indices, points=points[indices].ravel().tolist(),
                          triangles=[lookup[index] for tri in triangles for index in tri]))
    shoes[REFERENCE] = frames.ravel().tolist()
    shoes[SURFACE] = {str(side): part for side, part in enumerate(parts)}


def local_fit(points, source, target, triangles, scale, center_delta):
    """Transfer the local residual of the skin deformation to shoe vertices."""
    reference = source * scale
    current = target - center_delta
    residual = current - reference
    if np.max(abs(residual)) < 1e-7:
        return points + center_delta
    tree = BVHTree.FromPolygons(reference.tolist(), triangles.tolist(), all_triangles=True)
    nearest = [tree.find_nearest(point) for point in points]
    face = np.array([hit[2] for hit in nearest], dtype=np.intp)
    contact = np.array([hit[0] for hit in nearest])
    triangle = triangles[face]
    a, b, c = reference[triangle].transpose(1, 0, 2)
    ab, ac, offset = b - a, c - a, contact - a
    dot = lambda x, y: np.einsum("ij,ij->i", x, y)
    bb, bc, cc = dot(ab, ab), dot(ab, ac), dot(ac, ac)
    pb, pc = dot(offset, ab), dot(offset, ac)
    denominator = bb * cc - bc * bc
    valid = denominator > 1e-18
    u = np.divide(cc * pb - bc * pc, denominator, out=np.zeros_like(pb), where=valid)
    v = np.divide(bb * pc - bc * pb, denominator, out=np.zeros_like(pc), where=valid)
    weights = np.clip(np.stack((1 - u - v, u, v), axis=1), 0, 1)
    weights /= weights.sum(axis=1, keepdims=True)
    correction = np.einsum("ij,ijk->ik", weights, residual[triangle])
    return points + center_delta + correction


def fit_shoes(context, shoes):
    rig = shoes.parent
    if rig is None or rig.type != "ARMATURE":
        raise ValueError("Die ausgewählten Schuhe sind keinem Rig zugeordnet.")
    source = np.array(shoes[REFERENCE]).reshape(4, 3)
    target_points, target, _ = foot_geometry(body_for_rig(context, rig), rig)
    if np.any(source[1::2] <= 1e-8) or np.any(target[1::2] <= 1e-8):
        raise ValueError("Die Fußmaße sind ungültig.")

    keys = shoes.data.shape_keys
    if keys and not keys.use_relative:
        raise ValueError("Die Schuhpassform benötigt relative Shape Keys.")
    old_fit = keys.key_blocks.get(FIT_KEY) if keys else None
    basis = keys.reference_key if keys else None
    coordinates = np.empty(len(shoes.data.vertices) * 3, dtype=np.float32)
    (basis.data if basis else shoes.data.vertices).foreach_get("co", coordinates)
    local = rig_coordinates(shoes, rig)
    points = transform(coordinates.reshape(-1, 3), local)
    side = np.argmin(abs(points[:, 0, None] - source[::2, 0]), axis=1)
    adjusted = target[::2][side] + (points - source[::2][side]) * (target[1::2] / source[1::2])[side]
    if SURFACE in shoes:
        for index in range(2):
            mask = side == index
            if not mask.any():
                continue
            part = shoes[SURFACE][str(index)]
            original = np.array(part["points"]).reshape(-1, 3) - source[2 * index]
            current = target_points[np.array(part["indices"])] - source[2 * index]
            scale = target[2 * index + 1] / source[2 * index + 1]
            delta = target[2 * index] - source[2 * index]
            triangles = np.array(part["triangles"], dtype=np.intp).reshape(-1, 3)
            scaled = (points[mask] - source[2 * index]) * scale
            adjusted[mask] = source[2 * index] + local_fit(scaled, original, current, triangles, scale, delta)
    fitted = transform(adjusted, local.inverted())
    if old_fit is None and np.max(abs(fitted - coordinates.reshape(-1, 3))) < 1e-6:
        return
    if basis is None:
        basis = shoes.shape_key_add(name="Basis", from_mix=False)
    key = old_fit or shoes.shape_key_add(name=FIT_KEY, from_mix=False)
    key.relative_key = basis
    key.data.foreach_set("co", np.ascontiguousarray(fitted, dtype=np.float32).ravel())
    key.value = 1.0
    shoes.data.update()
    context.view_layer.update()


class MPFBTOOLS_OT_refit_shoes(bpy.types.Operator):
    bl_idname = "mpfb_tools.refit_shoes"
    bl_label = "Schuhe an Fußgröße anpassen"
    bl_description = "Aktualisiert das ausgewählte Schuhobjekt anhand der aktuellen MPFB-Fußform"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object is not None and REFERENCE in context.active_object

    def execute(self, context):
        try:
            fit_shoes(context, context.active_object)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "Schuhe an die aktuelle Fußgröße angepasst")
        return {"FINISHED"}
