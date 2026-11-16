"""Convert visible image landmarks to measurements relative to the ear."""


LANDMARKS = {
    "ear_top": "y of top rim of the fully visible profile ear",
    "ear_lobe": "y of bottom of the same ear lobe",
    "ear_back": "x of back edge of that ear at mid-height",
    "fringe_tip": "y of lowest dense fringe against forehead",
    "nape_tip": "y of lowest dense nape tips",
    "fade_mid_top": "y of midpoint of fade directly above ear",
    "fade_mid_back": "x of midpoint of fade behind ear at mid-height",
    "fade_band_top": "y where fade becomes dense directly above ear",
    "fade_band_bottom": "y where the fade becomes almost bare there",
    "crown_curl_span": "vertical span across the diameter of one typical crown curl",
    "nape_curl_span": "vertical span across the diameter of one typical nape curl",
    "lock_span": "vertical span across the WIDTH of one representative bundle, perpendicular to the bundle, where it lies near horizontal",
}


def apply_landmarks(recipe, profile, parameters):
    """Use comparable distances in one view and reject implausible ratios."""
    if not isinstance(profile, dict):
        return recipe
    marks = {}
    for key in LANDMARKS:
        value = profile.get(key)
        if type(value) in (float, int) and 0 <= value <= 1000:
            marks[key] = value
    if not {"ear_top", "ear_lobe"} <= marks.keys():
        return recipe
    ear_height = marks["ear_lobe"] - marks["ear_top"]
    aspect = profile.get("aspect")
    if type(aspect) not in (float, int) or not 30 <= ear_height <= 450 or not 0.4 <= aspect <= 2.5:
        return recipe

    def difference(positive, negative, factor=1):
        if positive in marks and negative in marks:
            return factor * (marks[positive] - marks[negative]) / ear_height
        return None

    # The calibrated ratio remains separate from the fibre-length estimates.
    candidates = {
        "fringe_clearance": difference("ear_top", "fringe_tip"),
        "nape_drop": difference("nape_tip", "ear_lobe"),
        "fade_height": difference("ear_top", "fade_mid_top"),
        "fade_blend": difference("fade_band_bottom", "fade_band_top"),
    }
    behind = difference("fade_mid_back", "ear_back", aspect)
    if behind is not None:
        candidates["fade_behind"] = abs(behind)
    for parameter, landmark, ear_units in (
        ("curl_size", "crown_curl_span", 3.0),
        ("nape_curl_size", "nape_curl_span", 3.0),
        ("lock_width", "lock_span", 60.0),
    ):
        if landmark in marks:
            candidates[parameter] = ear_units * marks[landmark] / ear_height
    for parameter, value in candidates.items():
        if value is None:
            continue
        _, _, minimum, maximum, _ = parameters[parameter]
        if minimum <= value <= maximum:
            recipe[parameter] = round(value, 3)
    return recipe
