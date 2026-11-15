"""Shape and combing profiles for the hairstyle and facial hair galleries."""

from pathlib import Path
from math import cos, hypot, sin


STYLES = {
    "H01": "Classic Side Part mit Mid Fade",
    "H02": "Classic Slick Back",
    "H03": "Textured Quiff",
    "H04": "Short Curly Top",
    "H05": "Short Textured Crop",
    "H06": "Wavy Fringe",
    "H07": "Buzz Cut",
    "H08": "Receding Buzz Cut",
    "H09": "Short Mohawk",
    "H10": "Textured Mohawk mit Burst Fade",
    "B01": "Designer Stubble",
    "B02": "Short Rounded Beard",
    "B03": "Short Boxed Beard",
    "B04": "Buschiger runder Vollbart",
    "B05": "Vollbart mit Handlebar",
    "B06": "Kurzer klassischer Schnurrbart",
    "B07": "Beardstache mit schmaler Kieferlinie",
    "B08": "Kurzer Goatee",
    "B09": "Langer Boxed Beard mit Fade",
    "A01": "Dicht und gerade",
    "A02": "Voll mit sanftem Bogen",
    "A03": "Markant mit Winkel",
    "A04": "Schmal mit feinem Auslauf",
}
ICONS = Path(__file__).with_name("defaults") / "grooms"


def smooth(low, high, x):
    t = max(0.0, min(1.0, (x - low) / (high - low)))
    return t * t * (3 - 2 * t)


def scalp_profile(style, root, normal, depth):
    x, y, z = root
    width = abs(x)
    forehead = 1 - smooth(.028, .060, y)
    fade = smooth(-.156, -.064, z)
    hairline = -.091 + .018 * smooth(.031, .075, width)
    density = 1 - forehead * (1 - smooth(hairline - .002, hairline + .002, z))
    crown = smooth(-.096, -.044, z) * smooth(-.16, .56, normal.z)
    front = 1 - smooth(.026, .112, y)
    front_comb = forehead * smooth(hairline - .009, hairline + .011, z)

    if style == "H01":
        line = .049 - .060 * y
        part = smooth(-.107, -.071, z) * (1 - smooth(depth - .080, depth - .034, y))
        if abs(x - line) < .00095 * part:
            density = 0
        top = max(crown, front_comb * .76)
        bulk = top * (1 if x < line else .26)
        direction = (-.85 if x < line else .76, .79, front_comb * .67)
        return density * (.09 + .91 * fade), .0011 + .015 * fade**2 + .062 * bulk, .0004 + .003 * fade + bulk * (.010 + .009 * front), top, direction, 0

    return detailed_scalp_profile(style, root, normal, depth)


def detailed_scalp_profile(style, root, normal, depth):
    x, y, z = root
    width = abs(x)
    front = 1 - smooth(.031, .076, y)
    back = smooth(depth * .62, depth * .92, y)
    temple = smooth(.025, .069, width)
    texture = .55 * sin(x * 505 + y * 104) + .45 * cos(y * 492 - x * 93)
    hairline = -.093 + .021 * temple + texture * .00135
    if style == "H08":
        hairline += .020 + .029 * smooth(.012, .057, width) - .004 * sin(x * 51)
    elif style == "H06":
        hairline += .004
    edge = 1 - front * (1 - smooth(hairline - .0016, hairline + .0024, z))

    # The nape and the area over the ear are graduated separately. A single
    # horizontal fade would put the same abrupt outline across the entire head.
    over_ear = smooth(.043, .073, width) * smooth(.045, .086, y) * (1 - smooth(.117, .163, y))
    nape = smooth(-.179 + .018 * back, -.091 + .015 * back, z)
    taper = nape * (1 - .42 * over_ear * (1 - smooth(-.118, -.069, z)))
    top = smooth(-.109, -.032, z) * smooth(-.13, .71, normal.z)
    front_top = front * smooth(hairline - .003, hairline + .023, z)
    coverage = edge * (.20 + .80 * taper)

    if style == "H02":
        # Dense, low, parallel comb marks turn inward at the temples.
        front_comb = front * (1 - .79 * smooth(.045, .074, width))
        lift = max(top, front_comb * .92)
        return (edge * (.48 + .52 * taper),
                .002 + .013 * taper + .065 * lift,
                .0005 + .002 * taper + lift * (.005 + .002 * front),
                lift, (-x * 1.45, 1, .98 * front_comb), .00045)
    if style == "H03":
        ridge = (1 - .39 * smooth(.027, .065, width)) * (1 - smooth(.024, .125, y))
        raised = max(top * .9, front_top * .86)
        return (coverage, .0012 + .012 * taper + raised * (.012 + .025 * ridge),
                .0005 + .0018 * taper + raised * (.004 + .017 * ridge),
                raised, (.51 + .18 * texture, .67, .39 + .56 * ridge), .0018)
    if style == "H04":
        curls = max(top, front_top * .70) * (.84 + .16 * texture)
        return (coverage, .0016 + .013 * taper + .033 * curls,
                .0008 + .002 * taper + .011 * curls,
                curls, (.15, .64, .36 * front_top), .009 * curls)
    if style == "H05":
        # A low silhouette with broken ends, forward crown flow and a short fringe.
        crop = max(top * .88, front_top * .58)
        return (coverage, .0014 + .010 * taper + crop * (.014 + .006 * texture),
                .0005 + .0013 * taper + .0037 * crop,
                crop, (.24 + .22 * texture, -.97, -.13), .0013 * crop)
    if style == "H06":
        fringe = max(top, front_top * .86) * (1 - .17 * back)
        sweep = .47 + .32 * sin(x * 53 + y * 17)
        return (edge * (.35 + .65 * taper), .0022 + .012 * taper + fringe * (.029 + .023 * front),
                .0007 + .002 * taper + fringe * (.007 + .003 * front),
                fringe, (sweep, -.88, -.10 - .34 * front), .006 * fringe)
    if style in ("H07", "H08"):
        # Follow the local growth direction even at clipper length. H08 adds a
        # density gradient around the receded temples and the vertex of the scalp.
        if style == "H07":
            length = .0018 + .0041 * taper
            coverage = edge * (.48 + .52 * taper)
        else:
            thinning = smooth(.014, .067, width) * front
            vertex = top * (1 - smooth(.014, .061, width)) * smooth(.083, .128, y) * (1 - back)
            length = .00085 + .0025 * taper
            coverage = edge * (.35 + .65 * taper) * (1 - .56 * thinning - .31 * vertex)
        return coverage, length, 0, top, (-x * 4.0, -.55 + 1.25 * back, -.36), 0

    if style == "H10":
        return burst_mohawk_profile(root, depth, edge)

    strip_width = .019 - .007 * smooth(.085, depth * .96, y)
    strip = 1 - smooth(strip_width - .0013, strip_width + .0013, width)
    stubble = .025 + .045 * smooth(-.117, -.066, z)
    crest = strip * (.48 + .52 * max(top, front_top))
    return (edge * (strip + (1 - strip) * stubble),
            .0007 + crest * (.016 + .012 * front),
            .0003 + crest * (.006 + .012 * front),
            strip, (-x * 7, .88, .35 * front), .00135 * crest)


def burst_mohawk_profile(root, depth, hairline):
    x, y, z = root
    progress = y / depth
    rear = smooth(.54, .91, progress)
    fringe = 1 - smooth(.11, .47, progress)
    crest_width = .052 - .024 * rear + .0028 * sin(y * 87)
    crest = 1 - smooth(crest_width - .008, crest_width + .006, abs(x))
    nape = rear * smooth(-.198, -.161, z)
    long_hair = crest * max(smooth(-.091, -.052, z), nape)

    # The shortest stubble sits at the ear. The transition arcs over the ear
    # and leaves the centre of the nape long.
    ear_distance = hypot((y - depth * .55) / (depth * .42), (z + .148) / .085)
    fade = smooth(.38, 1.32, ear_distance)
    density = hairline * max(long_hair, .027 + .79 * fade**1.55)
    lock = cos(x * 189 - y * 149 + .90 * sin(y * 81))
    lock_length = .84 + .22 * lock
    length = .00050 + .008 * fade**2 + long_hair * lock_length * (.056 + .022 * fringe - .023 * rear)
    lift = .00030 + long_hair * (.026 + .008 * fringe - .010 * rear) * (.78 + .22 * lock)
    sweep = -.51 + .36 * sin(x * 83 + y * 94)
    fringe_fall = 1 - smooth(.010, .037, abs(x + .018))
    direction = (sweep * (1 - .60 * rear),
                 -.65 + 1.43 * rear + (1.25 - .82 * fringe_fall) * fringe,
                 .47 * fringe - .85 * rear)
    return density, length, lift, long_hair, direction, (.005 + .003 * lock) * long_hair


def beard_profile(style, root):
    x, y, z = root
    width = abs(x)
    front = 1 - smooth(.021, .055, y)
    grain = .0007 * sin(950 * x + 300 * y) + .00045 * cos(650 * y)
    corner = smooth(.012, .036, width)
    lip_top = -.035 - .006 * corner + grain
    lip_bottom = -.047 - .004 * corner + grain
    mustache = front * (1 - smooth(.026, .036, width))
    mustache *= smooth(lip_bottom - .0008, lip_bottom + .001, z)
    mustache *= 1 - smooth(lip_top - .001, lip_top + .0014, z)
    chin = (1 - smooth(.019, .035, width)) * (1 - smooth(-.064, -.057, z))
    chin *= (1 - smooth(.030, .065, y)) * smooth(-.105, -.097, z)
    sideburn = smooth(.041, .068, width)
    cheek_line = -.057 + .040 * sideburn + .006 * smooth(.018, .075, y) + grain
    cheek = 1 - smooth(cheek_line - .0019, cheek_line + .0015, z)
    neck = -.112 + .015 * smooth(.058, .105, y)
    under = smooth(neck - .001, neck + .005, z)
    body = cheek * under
    mouth_corners = smooth(.023, .028, width) * (1 - smooth(.033, .040, width))
    connector = mouth_corners * front * smooth(-.071, -.066, z) * (1 - smooth(-.047, -.041, z))
    full = max(body, mustache, connector)
    # Each zone has its own growth direction. The upper lip is split at
    # the philtrum so neighbouring hairs sweep towards their own corner.
    lip_zone = mustache > max(body, connector) or (mustache > .20 and z >= lip_bottom)
    density_gradient = .72 + .28 * smooth(cheek_line, cheek_line - .030, z)

    if style == "B01":
        return max(body * density_gradient, mustache) * .81, .0013 + .0010 * chin, 0, lip_zone
    under_length = 1 - .72 * smooth(-.086, -.110, z)
    if style == "B02":
        length = .004 + .008 * (1 - .49 * sideburn) * smooth(-.054, -.081, z)
        return full, .0075 if lip_zone else length * under_length, .00047, lip_zone
    if style == "B03":
        boxed_top = -.058 + .039 * sideburn + grain * .4
        boxed = (1 - smooth(boxed_top - .0009, boxed_top + .0011, z)) * smooth(neck + .002, neck + .005, z)
        jaw = smooth(-.061, -.084, z)
        corner_fill = .56 + .44 * smooth(.009, .042, width)
        length = (.006 + .016 * jaw * corner_fill) * under_length
        return max(boxed, mustache, connector), .008 if lip_zone else length, .00036, lip_zone
    if style == "B04":
        mass = (1 - .58 * sideburn) * smooth(-.044, -.080, z)
        length = (.011 + .035 * mass) * (.42 + .58 * under_length)
        return full, .014 if lip_zone else length, (.00055 if lip_zone else .0036 * mass), lip_zone
    if style == "B05":
        mass = (1 - .71 * sideburn) * smooth(-.048, -.085, z)
        length = .018 + .024 * smooth(.006, .030, width) if lip_zone else (.008 + .018 * mass) * under_length
        upper_cheek = front * smooth(-.070, -.056, z)
        density = max(mustache, body * (1 - .67 * upper_cheek), .28 * connector)
        return density, length, .00025 if lip_zone else .00075, lip_zone
    if style == "B06":
        return mustache, .006 + .005 * corner, .00019, True
    if style == "B07":
        jaw_top = -.091 + .050 * smooth(.035, .067, width)
        jaw = (1 - smooth(jaw_top - .002, jaw_top + .001, z)) * under
        return max(mustache, jaw * .59), (.011 + .003 * corner) if lip_zone else .0017, .0002, lip_zone
    if style == "B09":
        # The jaw keeps its weight while the upper cheek and the sideburn
        # blend into clipper stubble. Keep the base broad across the chin.
        fade = smooth(-.013, -.078, z)
        cheek = 1 - smooth(cheek_line - .004, cheek_line + .002, z)
        neckline = smooth(neck + .001, neck + .005, z)
        density = max(cheek * neckline * (.23 + .77 * fade), mustache, connector * .89)
        jaw = smooth(-.045, -.084, z)
        front_volume = 1 - .18 * smooth(.060, .112, y)
        length = .002 + jaw * (.142 + z) * front_volume * 1.15
        return density, .014 if lip_zone else length, (.00063 if lip_zone else .0017 * jaw), lip_zone
    # Use a disconnected goatee as a concrete interpretation of the profile drawing.
    goatee = chin * (1 - smooth(-.061, -.058, z))
    sideburn_strip = sideburn * smooth(.054, .064, y) * (1 - smooth(.085, .093, y))
    sideburn_strip *= smooth(-.040 + grain, -.030 + grain, z)
    length = .007 if lip_zone else .003 + .012 * goatee
    return max(mustache, goatee, sideburn_strip), length, .00045, lip_zone


BROWS = {
    # width, head height, rise to peak, peak location, drop from peak, body thickness
    "A01": (.052, -.107, .0019, .62, .0050, .0084),
    "A02": (.053, -.109, .0069, .55, .0090, .0075),
    "A03": (.050, -.113, .0100, .68, .0097, .0073),
    "A04": (.051, -.108, .0043, .63, .0093, .0037),
}


def brow_z(style, t):
    _, start, raise_by, peak, drop, _ = BROWS[style]
    if t <= peak:
        rise = t / peak if style == "A03" else smooth(0, peak, t)
        return start + raise_by * rise
    fall = (t - peak) / (1 - peak) if style == "A03" else smooth(peak, 1, t)
    return start + raise_by - drop * fall
