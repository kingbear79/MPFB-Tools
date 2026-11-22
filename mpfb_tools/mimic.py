"""Per-character facial controls, backed by MPFB's ARKit targets."""
import json
import math
from pathlib import Path
import re
import tempfile
import uuid

import bpy
import numpy as np

from . import library_backup, saved_assets
from .hair import object_type


# Bare ARKit names are kept in saved expressions; MPFB's expression keys use !ex-.
REGIONS = {
    "brow": ("Augenbrauen", (
        ("browInnerUp", "Innen anheben"), ("browDownLeft", "Senken links"),
        ("browDownRight", "Senken rechts"), ("browOuterUpLeft", "Außen anheben links"),
        ("browOuterUpRight", "Außen anheben rechts"))),
    "eye": ("Augen", tuple((name + side, label + suffix) for name, label in (
        ("eyeBlink", "Schließen"), ("eyeSquint", "Zusammenkneifen"), ("eyeWide", "Weiten"),
        ("eyeLookUp", "Blick aufwärts"), ("eyeLookDown", "Blick abwärts"),
        ("eyeLookIn", "Blick nach innen"), ("eyeLookOut", "Blick nach außen"))
        for side, suffix in (("Left", " links"), ("Right", " rechts")))),
    "cheek": ("Wangen", (("cheekPuff", "Aufblasen"),
        ("cheekSquintLeft", "Anheben links"), ("cheekSquintRight", "Anheben rechts"))),
    "jaw": ("Kiefer", (("jawOpen", "Öffnen"), ("jawForward", "Vorschieben"),
        ("jawLeft", "Nach links"), ("jawRight", "Nach rechts"))),
    "mouth": ("Mund", (
        ("mouthClose", "Lippen schließen"), ("mouthFunnel", "Trichtermund"),
        ("mouthPucker", "Kussmund"), ("mouthLeft", "Nach links"), ("mouthRight", "Nach rechts"),
        *((name + side, label + suffix) for name, label in (
            ("mouthSmile", "Lächeln"), ("mouthFrown", "Mundwinkel senken"),
            ("mouthDimple", "Grübchen"), ("mouthStretch", "Breitziehen"),
            ("mouthPress", "Lippen pressen"), ("mouthLowerDown", "Unterlippe senken"),
            ("mouthUpperUp", "Oberlippe heben"))
          for side, suffix in (("Left", " links"), ("Right", " rechts"))),
        ("mouthRollLower", "Unterlippe einrollen"), ("mouthRollUpper", "Oberlippe einrollen"),
        ("mouthShrugLower", "Unterlippe vorschieben"), ("mouthShrugUpper", "Oberlippe vorschieben"))),
    "nose": ("Nase und Zunge", (("noseSneerLeft", "Nase rümpfen links"),
        ("noseSneerRight", "Nase rümpfen rechts"), ("tongueOut", "Zunge herausstrecken"))),
}
UNITS = tuple(name for _label, rows in REGIONS.values() for name, _text in rows)
QUICK = (
    ("smile", "Lächeln", ("mouthSmileLeft", "mouthSmileRight")),
    ("frown", "Mundwinkel senken", ("mouthFrownLeft", "mouthFrownRight")),
    ("jaw", "Mund öffnen", ("jawOpen",)),
    ("pucker", "Kussmund", ("mouthPucker",)),
    ("blink", "Augen schließen", ("eyeBlinkLeft", "eyeBlinkRight")),
    ("squint", "Augen zusammenkneifen", ("eyeSquintLeft", "eyeSquintRight")),
    ("wide", "Augen weiten", ("eyeWideLeft", "eyeWideRight")),
    ("brow_inner", "Brauen innen heben", ("browInnerUp",)),
    ("brow_outer", "Brauen außen heben", ("browOuterUpLeft", "browOuterUpRight")),
    ("brow_down", "Brauen senken", ("browDownLeft", "browDownRight")),
)
PRESETS = {
    "HAPPY": ("Fröhlich", {"mouthSmileLeft": .7, "mouthSmileRight": .7,
        "cheekSquintLeft": .25, "cheekSquintRight": .25}),
    "SAD": ("Traurig", {"browInnerUp": .6, "mouthFrownLeft": .5, "mouthFrownRight": .5}),
    "ANGRY": ("Wütend", {"browDownLeft": .65, "browDownRight": .65,
        "eyeSquintLeft": .25, "eyeSquintRight": .25, "mouthPressLeft": .35, "mouthPressRight": .35}),
    "SURPRISED": ("Überrascht", {"browInnerUp": .55, "browOuterUpLeft": .5,
        "browOuterUpRight": .5, "eyeWideLeft": .5, "eyeWideRight": .5, "jawOpen": .4}),
    "SKEPTICAL": ("Skeptisch", {"browOuterUpLeft": .6, "browDownRight": .25,
        "mouthDimpleRight": .25}),
}
ERRORS = (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError)
_enum_cache = {}


def expression_folder(context):
    from . import directory
    return directory(context) / "Bibliothek" / "expressions"


def selected_body(context):
    if context.mode not in {"OBJECT", "POSE"}:
        raise ValueError("Wechsle in den Objekt- oder Pose-Modus.")
    body = saved_assets.figure_base(context, context.active_object)
    if body.library or body.data.library:
        raise ValueError("Für diese verknüpfte Figur zuerst einen Library Override erstellen.")
    if shared_mesh(body):
        raise ValueError("Das Körpermesh wird geteilt. Erstelle zuerst eine unabhängige Kopie.")
    return body


def unit_key(body, name):
    keys = body.data.shape_keys
    if keys is None:
        return None
    key = keys.key_blocks.get("!ex-" + name)
    return key if key is not None else keys.key_blocks.get(name)


def ready(body):
    return all(unit_key(body, name) is not None for name in UNITS)


def read_expression(body):
    return {name: float(key.value) for name in UNITS if (key := unit_key(body, name)) is not None}


def validate_expression(data):
    if not isinstance(data, dict) or not isinstance(data.get("face_units"), dict):
        raise ValueError("Die Datei enthält keinen gültigen Gesichtsausdruck.")
    result = {}
    for name, value in data["face_units"].items():
        if name not in UNITS:
            continue
        value = float(value)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Ausdruckswerte müssen zwischen 0 und 1 liegen.")
        result[name] = value
    return result


def apply_expression(body, values, strength=1.0):
    if not ready(body):
        raise ValueError("Bereite zuerst die Mimik der Figur vor.")
    # Change only facial keys, leaving modelling targets, body pose and visemes intact.
    for name in UNITS:
        unit_key(body, name).value = max(0.0, min(1.0, values.get(name, 0.0) * strength))
    body["mpfb_applied_expressions"] = "[]"


def coordinates(data):
    result = np.empty(len(data) * 3, dtype=np.float32)
    data.foreach_get("co", result)
    return result.reshape(-1, 3)


def shared_mesh(obj):
    # Hair binding and the library's fake users also hold Mesh IDs; only another
    # Object would make editing this mesh change a second character.
    return obj.data.users > 1 and any(other != obj and other.type == "MESH" and other.data == obj.data
                                    for other in bpy.data.objects)


def transfer_keys(body, child, mapping, created):
    """Transfer neutral-space offsets once; Blender drivers handle live changes and playback."""
    if shared_mesh(child):
        raise ValueError(f"„{child.name}“ teilt sein Mesh. Erstelle zuerst eine unabhängige Kopie.")
    count = len(child.data.vertices)
    indices = np.zeros((count, 3), dtype=np.int32)
    weights = np.zeros((count, 3), dtype=np.float32)
    for index, item in mapping.items():
        if index >= count:
            continue
        if min(item["verts"]) < 0 or max(item["verts"]) >= len(body.data.vertices):
            raise ValueError(f"Die MPFB-Zuordnung von „{child.name}“ passt nicht zum Körpermesh.")
        indices[index] = item["verts"]
        weights[index] = item["weights"]
    if np.any(np.abs(weights.sum(axis=1) - 1) > 1e-4):
        raise ValueError(f"Die MPFB-Zuordnung von „{child.name}“ ist unvollständig.")
    if child.data.shape_keys is None:
        created.append((child, child.shape_key_add(name="Basis", from_mix=False)))
    neutral = coordinates(child.data.shape_keys.reference_key.data)
    transform = np.asarray(child.matrix_world.inverted_safe().to_3x3() @ body.matrix_world.to_3x3())
    transferred = 0
    for name in UNITS:
        source = unit_key(body, name)
        delta = coordinates(source.data) - coordinates(source.relative_key.data)
        offsets = np.sum(delta[indices] * weights[:, :, None], axis=1) @ transform.T
        if float(np.max(np.abs(offsets))) < 1e-7:
            continue
        target_name = "MPFB-Tools · " + name
        target = child.data.shape_keys.key_blocks.get(target_name)
        if target is not None:
            # Existing keys are ours only if their driver points at this character.
            animation = child.data.shape_keys.animation_data
            path = target.path_from_id("value")
            driver = next((f for f in animation.drivers if f.data_path == path), None) if animation else None
            if not driver or not any(t.id == body for v in driver.driver.variables for t in v.targets):
                raise ValueError(f"„{child.name}“ enthält bereits einen anderen Mimiktreiber.")
            continue
        target = child.shape_key_add(name=target_name, from_mix=False)
        created.append((child, target))
        target.data.foreach_set("co", (neutral + offsets).ravel())
        curve = target.driver_add("value")
        curve.driver.type = "AVERAGE"
        variable = curve.driver.variables.new()
        variable.name = "mimik"
        variable.type = "SINGLE_PROP"
        # Target the owning Object so Blender's partial library writer can walk
        # dependencies without encountering an ownerless Key loopback.
        variable.targets[0].id_type = "OBJECT"
        variable.targets[0].id = body
        variable.targets[0].data_path = "data.shape_keys." + source.path_from_id("value")
        transferred += 1
    return transferred


def prepare(context, body):
    from bl_ext.blender_org.mpfb.services import ClothesService, TargetService
    from bl_ext.blender_org.mpfb.entities.clothes.mhclo import Mhclo

    if shared_mesh(body):
        raise ValueError("Das Körpermesh wird von mehreren Figuren geteilt. Erstelle zuerst eine unabhängige Kopie.")
    missing = [(name, TargetService.target_full_path(name)) for name in UNITS if unit_key(body, name) is None]
    if any(path is None for _name, path in missing):
        raise ValueError("Installiere das MPFB-Asset-Paket „faceunits01“ vollständig und versuche es erneut.")
    assets = []
    for obj in sorted(saved_assets.owned_objects(context.scene, body), key=lambda obj: obj.name):
        if obj == body or obj.type != "MESH" or not object_type(obj) or obj.get("mpfb_tools_hair_surface"):
            continue
        path = ClothesService.find_clothes_absolute_path(obj)
        if not path:
            raise ValueError(f"Die MPFB-Quelldatei für „{obj.name}“ fehlt. Lade das zugehörige Asset-Paket.")
        mapping = Mhclo()
        mapping.load(path)
        assets.append((obj, mapping.verts))
    created = []
    active_index = body.active_shape_key_index
    try:
        had_keys = body.data.shape_keys is not None
        for name, path in missing:
            key = TargetService.load_target(body, path, weight=0.0, name="!ex-" + name)
            if not had_keys:
                created.append((body, body.data.shape_keys.reference_key))
                had_keys = True
            created.append((body, key))
        for child, mapping in assets:
            transfer_keys(body, child, mapping, created)
        body["mpfb_tools_mimic_prepared"] = True
        return len(assets)
    except Exception:
        for obj, key in reversed(created):
            key.driver_remove("value")
            obj.shape_key_remove(key)
        raise
    finally:
        body.active_shape_key_index = active_index


def preset_items(_self, context):
    builtins = [(key, label, "Gesichtsausdruck anwenden", index)
                for index, (key, (label, _values)) in enumerate(PRESETS.items())]
    if context is None:
        return builtins
    try:
        folder = expression_folder(context)
        stamp = folder.stat().st_mtime_ns if folder.is_dir() else 0
        cache_key = (str(folder), stamp)
        if cache_key not in _enum_cache:
            result = list(builtins)
            for path in sorted(folder.glob("*.json")):
                if not re.fullmatch(r"[0-9a-f]{32}", path.stem):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    validate_expression(data)
                    label = str(data.get("name") or "Eigener Ausdruck")
                    result.append((path.stem, label, "Eigener Gesichtsausdruck", 100 + int(path.stem[:7], 16)))
                except (OSError, ValueError, TypeError):
                    continue
            _enum_cache[cache_key] = result
        return _enum_cache[cache_key]
    except (KeyError, OSError, AttributeError):
        return builtins


def quick_get(names):
    def get(self):
        body = self.id_data
        return sum(key.value if (key := unit_key(body, name)) is not None else 0 for name in names) / len(names)
    return get


def quick_set(names):
    def set_value(self, value):
        body = self.id_data
        for name in names:
            if (key := unit_key(body, name)) is not None:
                key.value = value
        body["mpfb_applied_expressions"] = "[]"
    return set_value


class MPFBTOOLS_MimicSettings(bpy.types.PropertyGroup):
    preset: bpy.props.EnumProperty(name="Ausdruck", items=preset_items)
    strength: bpy.props.FloatProperty(name="Stärke beim Anwenden", default=1, min=0, max=1,
        subtype="FACTOR", options=set(), description="Stärke der nächsten angewendeten Ausdrucksvorlage")
    region: bpy.props.EnumProperty(name="Bereich", options=set(),
        items=[(name, label, "") for name, (label, _rows) in REGIONS.items()])


for _name, _label, _units in QUICK:
    MPFBTOOLS_MimicSettings.__annotations__[_name] = bpy.props.FloatProperty(
        name=_label, min=0, max=1, subtype="FACTOR", options=set(),
        description="Beide Seiten gemeinsam einstellen; mit ‚Mimik-Keyframe‘ animieren",
        get=quick_get(_units), set=quick_set(_units))


class FigureOperator:
    @classmethod
    def poll(cls, context):
        try:
            selected_body(context)
            return True
        except ValueError:
            return False


class MPFBTOOLS_OT_prepare_mimic(FigureOperator, bpy.types.Operator):
    bl_idname = "mpfb_tools.prepare_mimic"
    bl_label = "Mimik vorbereiten"
    bl_description = "MPFB-Gesichtsausdrücke laden und auf Topologie und Körperteile übertragen"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            count = prepare(context, selected_body(context))
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Mimik vorbereitet; {count} MPFB-Meshes angebunden")
        return {"FINISHED"}


class MPFBTOOLS_OT_apply_mimic(FigureOperator, bpy.types.Operator):
    bl_idname = "mpfb_tools.apply_mimic"
    bl_label = "Ausdruck anwenden"
    bl_description = "Die aktuelle Mimik durch die gewählte Vorlage mit eingestellter Stärke ersetzen"
    bl_options = {"REGISTER", "UNDO"}
    neutral: bpy.props.BoolProperty(options={"HIDDEN"})

    def execute(self, context):
        try:
            body = selected_body(context)
            settings = body.mpfb_tools_mimic
            if self.neutral:
                values = {}
            elif settings.preset in PRESETS:
                values = PRESETS[settings.preset][1]
            else:
                if not re.fullmatch(r"[0-9a-f]{32}", settings.preset):
                    raise ValueError("Wähle einen verfügbaren Gesichtsausdruck.")
                path = expression_folder(context) / (settings.preset + ".json")
                values = validate_expression(json.loads(path.read_text(encoding="utf-8")))
            apply_expression(body, values, settings.strength)
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MPFBTOOLS_OT_save_mimic(FigureOperator, bpy.types.Operator):
    bl_idname = "mpfb_tools.save_mimic"
    bl_label = "Ausdruck speichern"
    bl_description = "Die aktuelle Mimik als wiederverwendbaren Ausdruck in der Bibliothek speichern"
    name: bpy.props.StringProperty(name="Name", default="Mein Ausdruck", maxlen=100)

    def invoke(self, context, _event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        temporary = None
        try:
            body = selected_body(context)
            if not ready(body):
                raise ValueError("Bereite zuerst die Mimik der Figur vor.")
            name = self.name.strip()
            if not name:
                raise ValueError("Gib dem Ausdruck einen Namen.")
            folder = expression_folder(context)
            folder.mkdir(parents=True, exist_ok=True)
            identifier = uuid.uuid4().hex
            data = {"format_version": 1, "name": name,
                    "face_units": {key: value for key, value in read_expression(body).items() if value}}
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
            temporary.replace(folder / (identifier + ".json"))
            library_backup.mark_dirty(folder.parent.parent)
            self.report({"INFO"}, f"„{name}“ als Ausdruck gespeichert")
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"FINISHED"}


class MPFBTOOLS_OT_keyframe_mimic(FigureOperator, bpy.types.Operator):
    bl_idname = "mpfb_tools.keyframe_mimic"
    bl_label = "Mimik-Keyframe"
    bl_description = "Alle Gesichtswerte am aktuellen Frame speichern; auch neutrale Werte"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            body = selected_body(context)
            if not ready(body):
                raise ValueError("Bereite zuerst die Mimik der Figur vor.")
            for name in UNITS:
                unit_key(body, name).keyframe_insert("value", frame=context.scene.frame_current, group="Mimik")
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MimicPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MPFB-Tools"


class MPFBTOOLS_PT_mimic(MimicPanel, bpy.types.Panel):
    bl_label = "Mimik"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        try:
            body = selected_body(context)
        except ValueError as error:
            layout.label(text=str(error), icon="INFO")
            return
        layout.label(text=body.name, icon="OUTLINER_OB_ARMATURE")
        if not ready(body) or not body.get("mpfb_tools_mimic_prepared"):
            layout.label(text="Gesichtsausdrücke einmalig einrichten.")
            layout.operator("mpfb_tools.prepare_mimic", icon="MOD_MESHDEFORM")
            return
        settings = body.mpfb_tools_mimic
        box = layout.box()
        box.prop(settings, "preset", text="Vorlage")
        box.prop(settings, "strength", slider=True)
        row = box.row(align=True)
        row.operator("mpfb_tools.apply_mimic", text="Anwenden", icon="CHECKMARK")
        row.operator("mpfb_tools.apply_mimic", text="Neutral", icon="LOOP_BACK").neutral = True
        controls = layout.column(align=True)
        for name, _label, _units in QUICK:
            controls.prop(settings, name, slider=True)
        layout.label(text="Schnellregler wirken auf beide Seiten.", icon="INFO")
        layout.operator("mpfb_tools.keyframe_mimic", icon="KEY_HLT")
        layout.operator("mpfb_tools.save_mimic", icon="ADD")


class MPFBTOOLS_PT_mimic_details(MimicPanel, bpy.types.Panel):
    bl_label = "Mimik im Detail"
    bl_parent_id = "MPFBTOOLS_PT_mimic"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        try:
            body = selected_body(context)
            return ready(body) and bool(body.get("mpfb_tools_mimic_prepared"))
        except ValueError:
            return False

    def draw(self, context):
        body = selected_body(context)
        settings = body.mpfb_tools_mimic
        self.layout.prop(settings, "region", text="")
        column = self.layout.column(align=True)
        for name, label in REGIONS[settings.region][1]:
            column.prop(unit_key(body, name), "value", text=label, slider=True)
        self.layout.label(text="Links/rechts aus Sicht der Figur.")
        self.layout.operator("mpfb_tools.prepare_mimic", text="Anbauteile aktualisieren", icon="FILE_REFRESH")


CLASSES = (MPFBTOOLS_MimicSettings, MPFBTOOLS_OT_prepare_mimic, MPFBTOOLS_OT_apply_mimic,
           MPFBTOOLS_OT_save_mimic, MPFBTOOLS_OT_keyframe_mimic, MPFBTOOLS_PT_mimic, MPFBTOOLS_PT_mimic_details)


def register():
    bpy.types.Object.mpfb_tools_mimic = bpy.props.PointerProperty(type=MPFBTOOLS_MimicSettings)


def unregister():
    del bpy.types.Object.mpfb_tools_mimic
    _enum_cache.clear()
