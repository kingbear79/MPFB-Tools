"""Build scalp strands from measurements in the reference image recipe."""
import math
from typing import NamedTuple

from mathutils import Vector

from .groom_profiles import smooth


class Ear(NamedTuple):
    front: float
    rear: float
    top: float
    lobe: float

    @property
    def height(self):
        return self.top - self.lobe


def ear_landmarks(tree, depth):
    """Locate the pinna on each side of the actual MPFB head."""
    ears = {}
    for side in (-1, 1):
        def lateral(y, z):
            point, _, _, _ = tree.ray_cast((side * .20, y, z), (-side, 0, 0), .16)
            return abs(point.x) if point is not None else None

        rim = []
        for level in range(34):
            z = -.079 - .0027 * level
            before, after = lateral(.38 * depth, z), lateral(.74 * depth, z)
            if before is None or after is None:
                continue
            for index in range(16):
                part = .44 + .016 * index
                y = part * depth
                extent = lateral(y, z)
                baseline = before + (after - before) * ((part - .38) / .36)
                if extent is not None and extent - baseline > .009:
                    rim.append((y, z))
        if len(rim) >= 20 and max(z for _, z in rim) - min(z for _, z in rim) >= .031:
            ears[side] = Ear(min(y for y, _ in rim) - .0015, max(y for y, _ in rim) + .0015,
                             max(z for _, z in rim) + .0025, min(z for _, z in rim) - .004)
        else:
            ears[side] = Ear(.48 * depth, .62 * depth, -.097, -.158)
    return ears


def fade_at(root, ear, recipe):
    width, y, z = abs(root.x), root.y, root.z
    mid_y = (ear.front + ear.rear) * .5
    mid_z = (ear.top + ear.lobe) * .5
    y_radius = ((ear.rear - mid_y) + ear.height * recipe["fade_behind"]
                if y >= mid_y else mid_y - ear.front + .85 * ear.height)
    z_radius = ear.height * (.5 + recipe["fade_height"] if z >= mid_z else .74)
    distance = math.hypot((y - mid_y) / y_radius, (z - mid_z) / z_radius)
    # Convert the same visible transition width along the local ellipse direction.
    normal_scale = math.hypot((y - mid_y) / y_radius**2, (z - mid_z) / z_radius**2)
    transition = max(.015, .5 * recipe["fade_blend"] * ear.height * normal_scale / max(.1, distance))
    return (1 - smooth(1 - transition, 1 + transition, distance)) * smooth(.042, .066, width) * recipe["fade"]


def scalp_section(root, normal, depth, ear, recipe):
    x, y, z = root
    width = abs(x)
    progress = y / depth
    front = 1 - smooth(.18, .40, progress)
    fringe = 1 - smooth(.12, .42, progress)
    rear = smooth(.57, .88, progress)
    edge_noise = math.sin(x * 385 + y * 147) * .0011
    hairline = -.087 + .023 * recipe["hairline"] + .021 * smooth(.025, .068, width) + edge_noise
    cover = 1 - front * (1 - smooth(hairline - .002, hairline + .003, z))

    # The upper edge moves with the fade, and behind the ear a separate
    # panel continues from the crown down to the rear hairline.
    top_z = -.098
    crown = smooth(top_z - .010, top_z + .024, z)
    crown *= .79 + .21 * smooth(-.25, .43, normal.z)
    crown = max(crown, fringe * smooth(hairline, hairline + .032, z) * (1 - smooth(.033, .061, width)))
    nape_width = .073 * recipe["nape_width"]
    back_panel = rear * (1 - smooth(nape_width - .008, nape_width + .009, width))
    back_panel = max(back_panel, rear * crown * .85)
    lower_back = smooth(-.065, -.154, z)
    nape = back_panel * lower_back
    upper_back = back_panel * (1 - lower_back)
    top = crown * (1 - back_panel)

    side = max(0, 1 - top - upper_back - nape)
    fade = fade_at(root, ear, recipe)
    density = cover * (recipe["density"] * (top + side) + recipe["nape_density"] * back_panel) * (1 - .91 * fade)
    nape_edge = ear.lobe - ear.height * recipe["nape_drop"]
    density *= 1 - back_panel * (1 - smooth(nape_edge - .002, nape_edge + .005, z))
    if recipe["part"] > 0:
        part_x = .060 * recipe["part_offset"] * (1 - .26 * smooth(.10, .66, progress))
        part_width = .005 * recipe["part"]
        visible_part = (1 - smooth(.55, .77, progress)) * crown
        density *= 1 - visible_part * (1 - smooth(part_width * .55, part_width * 1.35, abs(x - part_x)))

    top_length = (.01 * (recipe["length"] + (recipe["fringe"] - recipe["length"]) * fringe))
    length = top_length * top + .01 * recipe["sides"] * side + .01 * (recipe["back"] * upper_back + recipe["nape"] * nape)
    length = length * (1 - fade) ** 1.75 + .00038 * fade
    front_fall = recipe["fringe_fall"] * fringe * top
    lateral = recipe["sweep"]
    fore_aft = .40 * (1 - abs(recipe["comb"])) + 1.14 * recipe["comb"] - 2.05 * front_fall
    if recipe["part"] > 0 and abs(lateral) < .9:
        lateral += (.78 - abs(lateral) * .5) * (1 if x > part_x else -1)
    elif recipe["part"] == 0:
        # Turn across the scalp as the fringe flow reverses. An opposing
        # straight comb on either side would expose an unintended parting.
        preferred_side = -1 if lateral < 0 else 1
        turn = (1 - smooth(.07, .63, abs(fore_aft))) * recipe["fringe_fall"]
        lateral += preferred_side * .83 * turn
    upper_flow = Vector((lateral, fore_aft, -.40 * front_fall))
    direction = upper_flow * top + Vector((x * 3.4, .24, -.94)) * side
    direction += Vector((x * (1.3 + 11.5 * recipe["nape_flare"]), .35, -.96)) * back_panel
    curl = recipe["curl"] * (top + .34 * side) + recipe["nape_curl"] * back_panel
    lift = min(length * .60, .0012 + .008 * recipe["volume"] * top + length * (.12 * upper_back + .10 * nape))
    return density, length, lift, direction, curl, back_panel, nape, front_fall


def scalp_strand(root, normal, section, recipe, ear, depth, rng, tree):
    _, length, lift, direction, curl, back_panel, nape, fringe = section
    tangent = direction - normal * direction.dot(normal)
    if tangent.length_squared < 1e-8:
        tangent = normal.orthogonal()
    tangent.normalize()
    path = [root - normal * .00012]
    if length < .008:
        growth = (normal * .69 + tangent * .72).normalized()
        return path + [root + growth * length * (i / 4) for i in range(1, 5)]

    # Use a sheet of neighbouring guides with shared pitch and phase.
    # Roots stay distinct. Their tips gather around the same lock.
    clump = recipe["clump"]
    # The image width includes overlapping fibres along the edges. Give
    # the guide cell enough room for these before it reaches its neighbours.
    cell_size = .001 * recipe["lock_width"] * (.56 + .44 * clump)
    crown_plane = smooth(.18, .78, normal.z)
    u = root.x + .20 * root.y + .25 * root.z
    v = (.50 + .50 * crown_plane) * root.y - .77 * (1 - crown_plane) * root.z - .15 * root.x
    cell_u = math.floor(u / cell_size + .15 * math.sin(v * 87))
    cell_v = math.floor(v / cell_size + .15 * math.cos(u * 75))
    lock = (cell_u * .61803399 + cell_v * .41421356) % 1
    phase = math.tau * lock + rng.uniform(-1, 1) * (1.19 - 1.08 * clump) * (1 - .56 * curl)
    underlayer = (1 - smooth(.013, .34, rng.random())) * clump * .43
    length *= (1 + (lock - .5) * .34 * clump) * (1 - underlayer) * rng.uniform(.91, 1.09)
    lift *= (1 + (lock - .5) * .44) * (1 - underlayer * .81)
    transverse = normal.cross(tangent).normalized()
    turn = (lock - .5) * clump * (1.2 + 1.65 * curl)
    flow = (tangent + transverse * turn).normalized()
    second = flow.cross(transverse).normalized()
    if second.dot(normal) < 0:
        second.negate()

    # Straight projection is shorter than the straightened fibre length.
    # A circular component around the guide makes real three-dimensional
    # bends, and the shared phase gives neighbouring hairs the same shape.
    outer_radius = .01 * (recipe["curl_size"] + (recipe["nape_curl_size"] - recipe["curl_size"]) * back_panel)
    centreline_radius = max(.56 * outer_radius, outer_radius - .31 * cell_size)
    radius = min(centreline_radius, length * .25) * smooth(0., .77, curl)
    ellipticity = .28 + .70 * smooth(.24, .74, curl)
    turns = min(8., max(.62, length / max(.012, math.tau * radius * .90))) * (.57 + .60 * curl)
    travel = length * (1 - .57 * curl)
    steps = min(54, max(12, math.ceil(11 * turns) if radius > .00065 else math.ceil(length / .004)))
    fall = min(.99, back_panel * .70 + nape * .18 + fringe * .63 + smooth(.08, .31, length) * .73)
    guide_end = direction.normalized()
    side = 1 if root.x >= 0 else -1
    flare = recipe["nape_flare"] * back_panel
    tip_lift = min(.025, length * .32) * flare
    du = (cell_u + .5) * cell_size - u
    dv = (cell_v + .5) * cell_size - v
    toward_lock = Vector((du - .22 * dv, dv * (.32 + .68 * crown_plane), -.92 * dv * (1 - crown_plane)))
    toward_lock -= normal * toward_lock.dot(normal)
    # A long fringe follows the forehead instead of extending horizontally
    # into the air. Only the tips come back towards the head.
    forehead_clearance = min(.014, length * .28)
    nape_limit = None
    if back_panel > .55:
        nape_limit = ear.lobe - ear.height * recipe["nape_drop"]
        nape_limit += abs(root.x) * .08 + (.003 + .018 * curl) * lock
    fringe_limit = ear.top + ear.height * recipe["fringe_clearance"] + .002 * math.sin(phase)
    crown_limit = .01 * recipe["volume"] * (.91 + .13 * lock) + .0015
    rear_limit = depth + .007 + .006 * recipe["volume"]
    for i in range(1, steps + 1):
        t = i / steps
        # Short roots lift up before turning. Long guides fall freely
        # below the skull, so the nape is never cut off at the last root.
        point = root + flow * (travel * t * (1 - .52 * fall * t))
        point += guide_end * (travel * fall * .48 * t**2)
        point.z -= travel * (fall * .50 * t**2 + .20 * fringe * t**3)
        point += normal * (lift * math.sin(math.pi * t * .76)**.92)
        point += Vector((side * .80, .65, .46)) * (tip_lift * smooth(.57, 1., t))
        point += toward_lock * (min(.86, 1.30 * clump) * smooth(.07, .63, t))
        if radius:
            angle = phase + math.tau * turns * (t + .08 * math.sin(math.pi * t))
            ramp = smooth(0., .22, t) * (1 - .22 * smooth(.83, 1, t))
            point += transverse * (radius * math.sin(angle) * ramp)
            point += second * (ellipticity * radius * math.cos(angle) * ramp)
        if fringe > .12 and t > .32 and point.y < 0:
            forehead, _, _, _ = tree.ray_cast((point.x, -.18, point.z), (0, 1, 0), .22)
            if forehead is not None:
                ahead = forehead.y - forehead_clearance
                point.y += max(0., ahead - point.y) * smooth(.29, .83, t) * fringe
        if point.z > crown_limit:
            excess = point.z - crown_limit
            point.z = crown_limit + excess * .002 / (.002 + excess)
        if point.y > rear_limit:
            excess = point.y - rear_limit
            point.y = rear_limit + excess * .006 / (.006 + excess)
        # The first millimetres hug the root. If the guide turns inward,
        # the nearest outward-facing local skin limits penetration.
        near, face_normal, _, _ = tree.find_nearest(point, .014)
        if near is not None:
            clearance = (point - near).dot(face_normal)
            if clearance < .00024:
                point += face_normal * (.00024 - clearance)
        fall_limit = fringe_limit if fringe > .12 and point.y < .18 * depth else nape_limit
        if fall_limit is not None and point.z < fall_limit < path[-1].z:
            cut = (path[-1].z - fall_limit) / (path[-1].z - point.z)
            path.append(path[-1].lerp(point, cut))
            break
        path.append(point)
    return path


def scalp_underlayer(root, normal, length, direction, rng, tree):
    """Follow the underlying skin so dense curls have continuous root coverage."""
    path = [root - normal * .00012]
    contact = root.copy()
    # A slight variation in the flow avoids collecting all roots into the
    # same parting as the longer locks.
    flow = direction * .46 + Vector((rng.uniform(-.55, .55), rng.uniform(-.55, .55), .16))
    step = min(.029, length * .49) / 6
    for i in range(1, 7):
        glide = flow - normal * flow.dot(normal)
        if glide.length_squared < 1e-8:
            glide = normal.orthogonal()
        hit, n, _, _ = tree.find_nearest(contact + glide.normalized() * step, step * 2.3)
        if hit is None or n.dot(normal) < .55:
            break
        contact, normal = hit, n
        path.append(hit + n * (.00034 + .0034 * math.sin(math.pi * i / 9)))
    return path
