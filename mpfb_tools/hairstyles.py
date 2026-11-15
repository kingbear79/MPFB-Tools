"""Procedural Hair Curves styles bound directly to the final MPFB surface."""

import math
import random
from statistics import median

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .groom_profiles import BROWS, STYLES, beard_profile, brow_z, scalp_profile, smooth
from .hair import add_hair_modifier, region_weights
from .hair_binding import remember_binding


MARKER = "mpfb_tools_hairstyle"


def detailed_scalp_path(style, root, normal, length, height, top, direction, wave, phase, tree, normal_at):
    """Comb short styles over the scalp and let longer ends lift off the form."""
    x, y, _ = root
    side_x = max(-1, min(1, x / .042))
    short = style in {"H07", "H08"}
    steps = 5 if short else (18 if style in {"H04", "H06"} else 13)
    path = [root - normal * .00012]
    contact = root.copy()
    n = normal
    comb = Vector(direction)
    if style == "H04":
        # Adjacent strands curl together. The cell phase varies between locks
        # while individual strands retain enough variation to look natural.
        cell_x = math.floor((x + .08) / .012)
        cell_y = math.floor(y / .013)
        phase = math.tau * ((cell_x * .618034 + cell_y * .37721) % 1) + .30 * math.sin(phase)

    if style == "H06":
        phase = x * 175 + y * 34 + .40 * math.sin(phase)

    for step in range(1, steps + 1):
        t = step / steps
        side = Vector((.16 * side_x, .22, -.93))
        flow = side.lerp(comb, top)
        if style == "H02":
            flow.z *= 1 - .57 * t
        elif style == "H03":
            flow.y += top * (.49 * t)
            flow.z -= top * (.55 * t)
        elif style == "H06":
            flow.z -= top * .52 * t
        tangent = (flow - n * flow.dot(n)).normalized()

        if short:
            # Near the skin there is no reason to search another triangle.
            path.append(root + normal * length * (.76 * t + .09 * t**2)
                        + tangent * length * .44 * t**1.45)
            continue

        step_size = length / steps
        hit, _, index, _ = tree.find_nearest(contact + tangent * step_size)
        if hit is None or (hit - contact).length > step_size * 2.35:
            break
        next_normal = normal_at(hit, index)
        if n.dot(next_normal) < .28:
            break
        contact = hit
        n = next_normal
        lateral = n.cross(tangent).normalized()
        if style == "H04":
            angle = phase + (1.18 + .22 * top) * math.tau * t
            curl_envelope = min(1.0, t * 4) * wave
            lift = height * (math.sin(math.pi * t * .79)**.78) + curl_envelope * .62 * (1 + math.cos(angle))
            point = contact + n * lift + lateral * curl_envelope * math.sin(angle)
        else:
            arc = math.sin(math.pi * t * (.91 if style in {"H02", "H05"} else .76))
            lift = height * arc**.83
            cycles = 1.12 if style == "H06" else .80
            curl = lateral * (math.sin(phase + t * math.tau * cycles) - math.sin(phase)) * wave * t
            point = contact + n * lift + curl
        path.append(point)
    return path


def burst_mohawk_path(root, normal, length, height, top, direction, wave, phase, tree, normal_at):
    path = [root - normal * .00012]
    x, y, _ = root
    side_flow = Vector((x * 2.1, .26, -.91))
    if length < .009:
        tangent = (side_flow - normal * side_flow.dot(normal)).normalized()
        for step in range(1, 6):
            t = step / 5
            path.append(root + normal * length * .62 * t + tangent * length * .76 * t)
        return path

    # Guide neighbouring tips into loose locks without moving their roots.
    u, v = x + .27 * y, y - .37 * x
    column, row = math.floor(u / .016), math.floor(v / .020)
    lock_phase = math.tau * ((column * .618034 + row * .414214) % 1)
    center_u = (column + .5 + .17 * math.sin(lock_phase)) * .016
    center_v = (row + .5 + .19 * math.cos(lock_phase)) * .020
    du, dv = center_u - u, center_v - v
    lock_offset = Vector((du - .27 * dv, dv + .37 * du, 0))
    phase = .74 * lock_phase + x * 61 + y * 39 + .21 * math.sin(phase)
    height *= 1 + .17 * top * math.sin(lock_phase)
    comb = side_flow.lerp(Vector(direction), top)
    contact = root.copy()
    rest_normal = normal
    for step in range(1, 19):
        t = step / 18
        angle = phase + math.tau * (.75 * t)
        bend = math.sin(angle) - math.sin(phase)
        flow = comb + Vector((.29 * bend * top, .24 * math.sin(angle) * top, -.20 * t * top))
        tangent = (flow - normal * flow.dot(normal)).normalized()
        hit, _, index, _ = tree.find_nearest(contact + tangent * (length / 18))
        if hit is None:
            break
        next_normal = normal_at(hit, index)
        if normal.dot(next_normal) < .45:
            break
        contact, normal = hit, next_normal
        lift = height * math.sin(math.pi * t * .73)**.76
        lift += wave * .82 * (math.cos(angle) - math.cos(phase)) * t
        lateral = normal.cross(tangent).normalized()
        toward_lock = lock_offset - normal * lock_offset.dot(normal)
        point = contact + normal.lerp(rest_normal, .24 * top) * lift
        point += lateral * wave * bend * t + toward_lock * top * smooth(.12, .88, t) * .74
        path.append(point)
    return path


def beard_path(style, root, normal, length, wave, upper_lip, phase, tree):
    x = root.x
    side = 1 if x >= 0 else -1
    steps = 5 if length < .004 else (18 if wave > .001 else 12)
    path = [root - normal * .0001]
    contact = root.copy()
    curly = style == "B04" and not upper_lip
    relaxation = .71 if style == "B09" and not upper_lip else .36
    if curly:
        column = math.floor(x / .007)
        row = math.floor((root.z + .42 * root.y) / .007)
        phase = math.tau * ((column * .618034 + row * .37721) % 1) + .49 * math.sin(phase)
    for step in range(1, steps + 1):
        t = step / steps
        if upper_lip:
            if style == "B05":
                # Comb directly out of the lip, then roll up and back at
                # each tip. Keep the two curls visible against the cheek.
                turn = smooth(.22, .92, t) * smooth(.007, .025, abs(x))
                flow = Vector((side * (1 - 1.44 * turn), -.33, -.55 + 1.80 * turn))
            else:
                flow = Vector((side * (.27 + .68 * smooth(.003, .033, abs(x))), -.12, -.91))
            normal_weight = .37 + .21 * (1 - t)
        else:
            down = .86 if length > .004 else .59
            across = -.21 if style in {"B04", "B05"} else (.02 if style == "B03" else -.08)
            flow = Vector((side * across * smooth(.013, .064, abs(x)), -.24, -down))
            normal_weight = .28 + .22 * (1 - t) if length > .004 else .73
            if style == "B09" and length > .004:
                flow.y = -.07
                normal_weight = .18 + .15 * (1 - t)
        tangent = (flow - normal * flow.dot(normal)).normalized()
        # Long hairs relax from the root normal towards gravity rather than
        # following every contour around the underside of the chin.
        growth = tangent.lerp(flow.normalized(), relaxation * t if length > .008 else .12)
        growth = (growth + normal * normal_weight).normalized()
        contact += growth * (length / steps)
        angle = phase + math.tau * 1.38 * t
        ripple = math.sin(angle) - math.sin(phase)
        lateral = normal.cross(tangent).normalized()
        point = contact + lateral * wave * .66 * ripple * t
        if curly:
            point += normal * wave * .61 * (math.cos(angle) - math.cos(phase)) * t
        if length > .004:
            near, face_normal, _, distance = tree.find_nearest(point, .004)
            if near is not None and face_normal.dot(normal) > .15:
                clearance = (point - near).dot(face_normal)
                if clearance < .00016:
                    point += face_normal * (.00016 - clearance)
        path.append(point)
    return path


def brow_ridge_offset(tree):
    """Find the forward ridge above the eye sockets on this head shape."""
    ridges = []
    for x in (-.042, -.034, -.027, .027, .034, .042):
        samples = (tree.ray_cast((x, -.20, -.001 * i), (0, 1, 0), .34)
                   for i in range(72, 113))
        ridge = min((point for point, normal, _, _ in samples
                     if point is not None and normal.y < -.72),
                    key=lambda point: point.y, default=None)
        if ridge is not None:
            ridges.append(ridge.z)
    return median(ridges) + .100 if ridges else 0


def brow_paths(style, points, triangles, faces, tree, uv, origin, scale):
    rng = random.Random(913)
    paths, roots, radii, tones = [], [], [], []
    length, _, _, _, _, thickness = BROWS[style]
    ridge_offset = brow_ridge_offset(tree)
    for side in (-1, 1):
        for _ in range(710):
            t = rng.random()
            end = smooth(.59, 1, t)
            inner_fade = smooth(0, .14, t)
            if rng.random() > (.35 + .65 * inner_fade) * (1 - .55 * end):
                continue
            width = thickness * (.50 + .50 * inner_fade) * (1 - .84 * end)
            x = side * (.0087 + length * t + rng.uniform(-.0011, .0011))
            z = brow_z(style, t) + ridge_offset + rng.triangular(-.59, .58, 0) * width
            root, normal, face, _ = tree.ray_cast((x, -.20, z), (0, 1, 0), .34)
            if root is None or normal.y > -.18:
                continue
            a, b, c = (points[i] for i in faces[face])
            ab, ac, ar = b - a, c - a, root - a
            aa, aa2, bb = ab.dot(ab), ab.dot(ac), ac.dot(ac)
            denom = aa * bb - aa2 * aa2
            if denom <= 1e-16:
                continue
            v = (bb * ar.dot(ab) - aa2 * ar.dot(ac)) / denom
            w = (aa * ar.dot(ac) - aa2 * ar.dot(ab)) / denom
            uv_a, uv_b, uv_c = (uv[i].uv for i in triangles[face].loops)
            roots.append(tuple(uv_a * (1 - v - w) + uv_b * v + uv_c * w))
            head = 1 - smooth(0, .33, t)
            strand_length = (.0025 + .0032 * (1 - end)) * (.68 + .32 * inner_fade) * rng.uniform(.71, 1.24)
            path = [root - normal * .00011]
            current = root
            for step in range(1, 7):
                u = step / 6
                direction = Vector((side * (.73 - .46 * head), 0,
                                    (.75 * head + .12 - .45 * end) * (1 - .54 * u)))
                tangent = (direction - normal * direction.dot(normal)).normalized()
                step_size = strand_length / 6
                guess = current + tangent * step_size
                hit, next_normal, _, _ = tree.find_nearest(guess, .002)
                if hit is None or next_normal.dot(normal) < .58:
                    hit, next_normal = guess, normal
                current, normal = hit, next_normal
                path.append(current + normal * (.00017 + .00052 * math.sin(math.pi * u * .84)))
            paths.append([tuple(origin + point * scale) for point in path])
            size = rng.uniform(.000036, .000081) * scale
            radii.extend(size * (1 - .84 * (i / 6)**1.55) for i in range(7))
            tones.append(max(0, min(1, rng.gauss(.31, .17))))
    if not paths:
        raise ValueError("Auf dieser Topologie konnte kein Brauenbogen bestimmt werden.")
    return paths, roots, radii, tones


def groom_paths(surface, style):
    beard = style.startswith("B")
    eyebrow = style in BROWS
    revised = style != "H01" and not beard and not eyebrow
    mesh = surface.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise ValueError("Das ausgewählte Körpermesh braucht eine UV-Map.")
    mask = region_weights(surface)["__BART" if beard else "__HAARE"]
    if not mask:
        raise ValueError("Auf dieser Topologie konnte keine Haarregion bestimmt werden.")
    mask_points = [mesh.vertices[i].co for i in mask]
    left, right = min(v.x for v in mask_points), max(v.x for v in mask_points)
    front, rear = min(v.y for v in mask_points), max(v.y for v in mask_points)
    bottom, crown = min(v.z for v in mask_points), max(v.z for v in mask_points)
    scale = (right - left) / (.14156 if beard else .15)
    if scale <= 1e-6:
        raise ValueError("Die Haarregion hat keine gültige Breite.")
    center = (left + right) * .5
    points = [Vector(((v.co.x - center) / scale, (v.co.y - front) / scale,
                      (v.co.z - crown) / scale)) for v in mesh.vertices]
    normals = [v.normal.copy() for v in mesh.vertices]
    mesh.calc_loop_triangles()
    group = surface.vertex_groups.get("body")
    skin = ({v.index for v in mesh.vertices
             if any(g.group == group.index and g.weight > 0 for g in v.groups)}
            if group else None)
    triangles = [t for t in mesh.loop_triangles if
                 min(mesh.vertices[i].co.z for i in t.vertices) > (crown - .135 * scale if eyebrow else bottom - .045 * scale)
                 and (skin is None or all(i in skin for i in t.vertices))]
    faces = [tuple(t.vertices) for t in triangles]
    if not faces:
        raise ValueError("Auf dem Körpermesh wurden keine Kopfflächen gefunden.")
    tree = BVHTree.FromPolygons(points, faces, all_triangles=True)
    uv = uv_layer.data
    if eyebrow:
        return brow_paths(style, points, triangles, faces, tree, uv, Vector((center, front, crown)), scale)
    rng = random.Random(492)
    paths, roots, radii, tones = [], [], [], []
    depth = (rear - front) / scale

    def normal_at(point, face):
        i, j, k = faces[face]
        a, b, c = points[i], points[j], points[k]
        u, v, w = b - a, c - a, point - a
        uu, uv_dot, vv = u.dot(u), u.dot(v), v.dot(v)
        denominator = uu * vv - uv_dot * uv_dot
        if denominator < 1e-17:
            return normals[i]
        q = (vv * w.dot(u) - uv_dot * w.dot(v)) / denominator
        r = (uu * w.dot(v) - uv_dot * w.dot(u)) / denominator
        return (normals[i] * (1 - q - r) + normals[j] * q + normals[k] * r).normalized()

    for face, triangle in enumerate(triangles):
        indices = faces[face]
        weights = [mask.get(i, 0) for i in indices]
        if max(weights) == 0:
            continue
        a, b, c = [points[i] for i in indices]
        count = triangle.area / (scale * scale) * (620000 if beard else 810000)
        uv_a, uv_b, uv_c = [uv[i].uv for i in triangle.loops]
        for _ in range(int(count) + (rng.random() < count % 1)):
            u, v = rng.random(), rng.random()
            if u + v > 1:
                u, v = 1 - u, 1 - v
            w = 1 - u - v
            mask_value = sum(value * factor for value, factor in zip(weights, (w, u, v)))
            root = a * w + b * u + c * v
            n = (normals[indices[0]] * w + normals[indices[1]] * u + normals[indices[2]] * v).normalized()
            x, _, z = root
            raw_density = smooth(.18, .69, mask_value) if revised else smooth(.13, .62, mask_value)
            if beard:
                density, length, wave, upper_lip = beard_profile(style, root)
            else:
                density, length, height, top, direction, wave = scalp_profile(style, root, n, depth)
            if rng.random() > raw_density * density:
                continue
            length *= rng.uniform(.83, 1.16)
            phase = rng.uniform(0, math.tau)
            steps = 5 if length < .006 else 12
            path = [root - n * .00015]
            contact = root
            outward = 1 if x >= 0 else -1
            if beard:
                path = beard_path(style, root, n, length, wave, upper_lip, phase, tree)
            elif style == "H10":
                path = burst_mohawk_path(root, n, length, height, top, direction, wave, phase, tree, normal_at)
            elif revised:
                path = detailed_scalp_path(style, root, n, length, height, top, direction,
                                           wave, phase, tree, normal_at)
            else:
                for step in range(1, steps + 1):
                    t = step / steps
                    side = Vector((.09 * outward, .86, -.55))
                    comb = Vector(direction)
                    comb.x *= 1 - .31 * t
                    flow = side.lerp(comb, top)
                    tangent = (flow - n * flow.dot(n)).normalized()
                    hit, _, index, _ = tree.find_nearest(contact + tangent * (length / steps))
                    if hit is None:
                        break
                    contact = hit
                    n = normal_at(contact, index)
                    curl = n.cross(tangent) * math.sin(phase + t * 12) * wave * t
                    lift = height * math.sin(math.pi * t * .81)**.87
                    path.append(contact + n * lift + curl)

            if len(path) < 2:
                continue
            paths.append([(p.x * scale + center, p.y * scale + front, p.z * scale + crown) for p in path])
            roots.append(tuple(uv_a * w + uv_b * u + uv_c * v))
            thickness = (.000115 if beard else .000075 + .000082 * smooth(-.156, -.064, z)) * rng.uniform(.76, 1.22) * scale
            if beard:
                thickness *= .74 if style == "B01" else .87
                cut_taper = .48 if style in {"B01", "B03", "B06"} else .72
                if style == "B09":
                    thickness *= .57 + .43 * smooth(.003, .016, length)
            elif revised:
                # Individual strands read as fibres rather than broad bundles.
                thickness *= .72 if style in {"H07", "H08"} else .84
                cut_taper = .14 if style in {"H07", "H08"} else .63
                if style == "H10":
                    thickness *= .55 + .45 * smooth(.005, .025, length)
            else:
                cut_taper = .82
            radii.extend(thickness * (1 - cut_taper * (i / (len(path) - 1))**1.7) for i in range(len(path)))
            tones.append(max(0, min(1, rng.gauss(.41, .17))))

    if not paths:
        raise ValueError("Auf diesem Mesh konnten keine Strähnen angelegt werden.")
    return paths, roots, radii, tones


def hair_material(style):
    finish = {"H02": ("Pomade", .34, .25), "H03": ("Matt", .55, .15)}.get(style)
    color, diffuse, dark, light = {
        "H10": ("Aschbraun", (.113, .085, .059), (.021, .015, .010), (.145, .112, .076)),
        "B09": ("Sandbraun", (.104, .068, .043), (.020, .011, .006), (.151, .103, .060)),
    }.get(style, ("Dunkelbraun", (.043, .019, .010), (.005, .0025, .0014), (.037, .017, .008)))
    name = f"MPFB-Tools · {color}"
    if finish:
        name += f" · {finish[0]}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*diffuse, 1)
    mat.use_nodes = True
    tree = mat.node_tree
    shader = tree.nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = finish[1] if finish else .50
    shader.inputs["Specular IOR Level"].default_value = finish[2] if finish else .19
    tone = tree.nodes.new("ShaderNodeAttribute")
    tone.attribute_name = "mpfb_hair_tone"
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    tree.links.new(tone.outputs["Fac"], ramp.inputs["Fac"])
    tree.links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
    return mat


def add_groom(context, surface, style):
    paths, roots, radii, tones = groom_paths(surface, style)
    old_active = context.view_layer.objects.active
    old_selection = list(context.selected_objects)
    obj = None
    old_rest = surface.add_rest_position_attribute
    try:
        bpy.ops.object.select_all(action="DESELECT")
        surface.select_set(True)
        context.view_layer.objects.active = surface
        surface.add_rest_position_attribute = True
        if bpy.ops.object.curves_empty_hair_add() != {"FINISHED"}:
            raise RuntimeError("Blender konnte die Hair Curves nicht anlegen.")
        obj = context.active_object
        curves = obj.data
        if curves.surface != surface:
            raise RuntimeError("Blender hat die Hair Curves nicht an das Körpermesh gebunden.")
        obj.parent = surface
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = Matrix.Identity(4)
        curves.surface_uv_map = surface.data.uv_layers.active.name
        obj.name = curves.name = STYLES[style]
        obj[MARKER] = style
        curves.add_curves([len(path) for path in paths])
        coords = np.asarray([p for path in paths for p in path], dtype=np.float32).ravel()
        curves.attributes["position"].data.foreach_set("vector", coords)
        for name, kind, domain, field, data in (
            ("surface_uv_coordinate", "FLOAT2", "CURVE", "vector", roots),
            ("radius", "FLOAT", "POINT", "value", radii),
            ("mpfb_hair_tone", "FLOAT", "CURVE", "value", tones),
        ):
            attr = curves.attributes.get(name) or curves.attributes.new(name, kind, domain)
            attr.data.foreach_set(field, np.asarray(data, dtype=np.float32).ravel())
        curves.materials.append(hair_material(style))
        add_hair_modifier(obj, frizz_distance={"H10": .00070, "B09": .00060}.get(style))
        context.view_layer.update()
        remember_binding(context.scene, obj)
        return obj
    except Exception:
        if obj is not None:
            curves = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if curves.users == 0:
                bpy.data.hair_curves.remove(curves)
        surface.add_rest_position_attribute = old_rest
        bpy.ops.object.select_all(action="DESELECT")
        for selected in old_selection:
            selected.select_set(True)
        context.view_layer.objects.active = old_active
        raise
