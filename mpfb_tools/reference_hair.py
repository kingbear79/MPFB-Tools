"""Build scalp strands from measurements in the reference image recipe."""
import math

from mathutils import Vector

from .groom_profiles import smooth


def scalp_section(root, normal, depth, recipe):
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
    fade = recipe["fade"]
    fade_height = recipe["fade_height"]
    top_z = -.098 + .036 * fade * fade_height
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

    ear_distance = math.hypot((progress - .49) / .38, (z + .145) / .077)
    fade_transition = smooth(.38 + .31 * fade_height, .95 + .30 * fade_height, ear_distance)
    side_length = .00035 + (recipe["sides"] * .01 - .00035) * (1 - fade * (1 - fade_transition**1.7))
    side_density = 1 - fade * (1 - (.045 + .955 * fade_transition**1.65))
    side = max(0, 1 - top - upper_back - nape)
    density = cover * (recipe["density"] * (top + side * side_density) + recipe["nape_density"] * back_panel)
    if recipe["part"] > 0:
        part_x = .060 * recipe["part_offset"] * (1 - .26 * smooth(.10, .66, progress))
        part_width = .005 * recipe["part"]
        visible_part = (1 - smooth(.55, .77, progress)) * crown
        density *= 1 - visible_part * (1 - smooth(part_width * .55, part_width * 1.35, abs(x - part_x)))

    top_length = (.01 * (recipe["length"] + (recipe["fringe"] - recipe["length"]) * fringe))
    length = top_length * top + side_length * side + .01 * (recipe["back"] * upper_back + recipe["nape"] * nape)
    front_fall = recipe["fringe_fall"] * fringe * top
    lateral = recipe["sweep"]
    if recipe["part"] > 0 and abs(lateral) < .9:
        lateral += (.78 - abs(lateral) * .5) * (1 if x > part_x else -1)
    upper_flow = Vector((lateral, .40 * (1 - abs(recipe["comb"])) + 1.14 * recipe["comb"]
                         - 2.05 * front_fall, -.40 * front_fall))
    direction = upper_flow * top + Vector((x * 3.4, .24, -.94)) * side
    direction += Vector((x * (1.3 + 11.5 * recipe["nape_flare"]), .35, -.96)) * back_panel
    curl = recipe["curl"] * (top + .34 * side) + recipe["nape_curl"] * back_panel
    lift = min(length * .76, .002 + .01 * recipe["volume"] * top + length * (.22 * upper_back + .12 * nape))
    return density, length, lift, direction, curl, back_panel, nape, front_fall


def scalp_strand(root, normal, section, recipe, rng, tree):
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
    cell_size = .010 + .015 * clump
    crown_plane = smooth(.18, .78, normal.z)
    u = root.x + .20 * root.y + .25 * root.z
    v = (.50 + .50 * crown_plane) * root.y - .77 * (1 - crown_plane) * root.z - .15 * root.x
    cell_u = math.floor(u / cell_size + .15 * math.sin(v * 87))
    cell_v = math.floor(v / cell_size + .15 * math.cos(u * 75))
    lock = (cell_u * .61803399 + cell_v * .41421356) % 1
    phase = math.tau * lock + rng.uniform(-1, 1) * (1.25 - .96 * clump)
    underlayer = (1 - smooth(.013, .34, rng.random())) * clump * .43
    length *= (1 + (lock - .5) * .34 * clump) * (1 - underlayer) * rng.uniform(.91, 1.09)
    lift *= (1 + (lock - .5) * .44) * (1 - underlayer * .81)
    transverse = normal.cross(tangent).normalized()
    turn = (lock - .5) * 1.65 * clump
    flow = (tangent + transverse * turn).normalized()
    second = flow.cross(transverse).normalized()
    if second.dot(normal) < 0:
        second.negate()

    # Straight projection is shorter than the straightened fibre length.
    # A circular component around the guide makes real three-dimensional
    # bends, and the shared phase gives neighbouring hairs the same shape.
    radius = min(.014 * recipe["curl_size"], length * .25) * smooth(0., .77, curl)
    ellipticity = .28 + .70 * smooth(.24, .74, curl)
    turns = min(8., max(.62, length / max(.012, math.tau * radius * .90))) * (.57 + .60 * curl)
    travel = length * (1 - .57 * curl)
    steps = min(54, max(12, math.ceil(11 * turns) if radius > .00065 else math.ceil(length / .004)))
    fall = min(.99, back_panel * .70 + nape * .18 + fringe * .63 + smooth(.08, .31, length) * .73)
    guide_end = direction.normalized()
    side = 1 if root.x >= 0 else -1
    flare = recipe["nape_flare"] * back_panel
    tip_lift = min(.040, length * .41) * flare
    du = (cell_u + .5) * cell_size - u
    dv = (cell_v + .5) * cell_size - v
    toward_lock = Vector((du - .22 * dv, dv * (.32 + .68 * crown_plane), -.92 * dv * (1 - crown_plane)))
    toward_lock -= normal * toward_lock.dot(normal)
    # A long fringe follows the forehead instead of extending horizontally
    # into the air. Only the tips come back towards the head.
    forehead_clearance = min(.025, length * .40)
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
        # The first millimetres hug the root. If the guide turns inward,
        # the nearest outward-facing local skin limits penetration.
        near, face_normal, _, _ = tree.find_nearest(point, .014)
        if near is not None:
            clearance = (point - near).dot(face_normal)
            if clearance < .00024:
                point += face_normal * (.00024 - clearance)
        path.append(point)
    return path


def scalp_underlayer(root, normal, length, direction, rng, tree):
    """Follow the underlying skin so dense curls have continuous root coverage."""
    path = [root - normal * .00012]
    contact = root.copy()
    # A slight variation in the flow avoids collecting all roots into the
    # same parting as the longer locks.
    flow = direction + Vector((rng.uniform(-.4, .4), rng.uniform(-.4, .4), .28))
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
