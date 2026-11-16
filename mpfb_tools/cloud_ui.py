"""Analyze the chosen photos once and build editable grooms in Blender."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
from time import monotonic

import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

from . import cloud_api as api, hair_binding, library_ui, saved_assets
from .attachment import figure_surface
from .groom_profiles import STYLES
from .hairstyles import add_groom
from .library import discard_new


_pending = None

COLOR_ITEMS = [(key, label, "") for key, (label, _) in api.COLORS.items()]
COMPONENTS = [(kind, label, "") for kind, label in api.LABELS.items()]
FIELD_NAMES = {"H": "hair", "B": "beard", "A": "brows"}
LOCAL_STYLES = {"H": "H02", "B": "B03", "A": "A02"}


def recipe_class(kind, suffix):
    descriptions = {
        "name": bpy.props.StringProperty(name="Name"),
        "style": bpy.props.EnumProperty(name="Grundform", items=[(sid, STYLES[sid], "") for sid in api.style_ids(kind)]),
        "color": bpy.props.EnumProperty(name="Farbe", items=COLOR_ITEMS),
        "visible": bpy.props.BoolProperty(name="Komponente übernehmen"),
        "certainty": bpy.props.StringProperty(),
        "notes": bpy.props.StringProperty(),
        "preview": bpy.props.PointerProperty(type=bpy.types.Object),
        "preview_signature": bpy.props.StringProperty(),
    }
    for key, (label, initial, low, high, _) in api.PARAMETERS[kind].items():
        descriptions[key] = bpy.props.FloatProperty(name=label, default=initial, min=low, max=high)
    return type(f"MPFBTOOLS_PG_reference_{suffix}", (bpy.types.PropertyGroup,),
                {"__module__": __name__, "__annotations__": descriptions})


RECIPES = {kind: recipe_class(kind, field) for kind, field in FIELD_NAMES.items()}


class MPFBTOOLS_PG_reference_path(bpy.types.PropertyGroup):
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")


class MPFBTOOLS_PG_reference_job(bpy.types.PropertyGroup):
    main_image: bpy.props.StringProperty(name="Hauptbild", subtype="FILE_PATH")
    support: bpy.props.CollectionProperty(type=MPFBTOOLS_PG_reference_path)
    with_hair: bpy.props.BoolProperty(name="Frisur", default=True)
    with_beard: bpy.props.BoolProperty(name="Bart")
    with_brows: bpy.props.BoolProperty(name="Augenbrauen")
    refresh: bpy.props.BoolProperty(name="Erneut anfragen", description="Sende die Bilder trotz vorhandener Analyse erneut")
    analyzed_paths: bpy.props.StringProperty()
    available: bpy.props.StringProperty()
    status: bpy.props.StringProperty()
    hair: bpy.props.PointerProperty(type=RECIPES["H"])
    beard: bpy.props.PointerProperty(type=RECIPES["B"])
    brows: bpy.props.PointerProperty(type=RECIPES["A"])


def settings(context):
    return context.window_manager.mpfb_tools_reference


def parts(state):
    return tuple(kind for kind, include in zip(api.LABELS, (state.with_hair, state.with_beard, state.with_brows)) if include)


def paths(state):
    return [bpy.path.abspath(state.main_image)] + sorted(bpy.path.abspath(row.filepath) for row in state.support)


def signature(state):
    files = []
    for name in paths(state):
        try:
            stat = Path(name).stat()
            files.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            files.append((name, None, None))
    return json.dumps(files, ensure_ascii=False)


def recipe_state(state, kind):
    return getattr(state, FIELD_NAMES[kind])


def available(state):
    return tuple(kind for kind in parts(state) if kind in state.available) if state.analyzed_paths == signature(state) else ()


def read_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return library_ui.cloud_key_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def accept_result(state, result, source):
    recipes = {kind: api.clean_recipe(kind, item) for kind, item in result["recipes"].items()}
    for kind, data in recipes.items():
        recipe = recipe_state(state, kind)
        for field, value in data.items():
            setattr(recipe, field, value)
    previous = set(state.available) if state.analyzed_paths == source else set()
    state.analyzed_paths = source
    state.available = "".join(kind for kind in api.LABELS if kind in recipes or kind in previous)
    if result["requested"]:
        usage = result.get("usage") or {}
        if set(usage) == {"input_tokens", "output_tokens"}:
            state.status = (f"1 API-Aufruf · {usage['input_tokens']} Eingabe- und "
                            f"{usage['output_tokens']} Ausgabetokens")
        else:
            state.status = "Analyse fertig · 1 API-Aufruf"
    else:
        state.status = "Analyse aus lokalem Cache · 0 API-Aufrufe"


class MPFBTOOLS_OT_reference_add_images(bpy.types.Operator, ImportHelper):
    bl_idname = "mpfb_tools.reference_add_images"
    bl_label = "Zusatzbilder auswählen"
    filter_glob: bpy.props.StringProperty(default="*.jpg;*.jpeg;*.png;*.webp", options={"HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    def execute(self, context):
        state = settings(context)
        current = {row.filepath for row in state.support}
        selected = list(dict.fromkeys(str(Path(self.directory) / f.name) for f in self.files))
        if not selected and self.filepath:
            selected = [self.filepath]
        extra = [path for path in selected if path not in current and path != bpy.path.abspath(state.main_image)]
        if len(current) + len(extra) > api.MAX_SUPPORT:
            self.report({"ERROR"}, f"Es sind bis zu {api.MAX_SUPPORT} Zusatzbilder möglich.")
            return {"CANCELLED"}
        for path in extra:
            state.support.add().filepath = path
        return {"FINISHED"}


class MPFBTOOLS_OT_reference_remove_image(bpy.types.Operator):
    bl_idname = "mpfb_tools.reference_remove_image"
    bl_label = "Zusatzbild entfernen"
    index: bpy.props.IntProperty(min=0)

    def execute(self, context):
        images = settings(context).support
        if self.index >= len(images):
            return {"CANCELLED"}
        images.remove(self.index)
        return {"FINISHED"}


class MPFBTOOLS_OT_reference_analyze(bpy.types.Operator):
    bl_idname = "mpfb_tools.reference_analyze"
    bl_label = "Bilder analysieren"
    bl_description = "Verwendet gespeicherte Analysen oder sendet die Referenzbilder für die fehlenden Komponenten an OpenAI"

    @classmethod
    def poll(cls, context):
        state = settings(context)
        return _pending is None and context.window is not None and bool(state.main_image and parts(state))

    def execute(self, context):
        global _pending
        state = settings(context)
        self.workspace = tempfile.TemporaryDirectory(prefix="mpfb-reference-")
        folder = Path(self.workspace.name)
        self.result = folder / "result.json"
        self.source = signature(state)
        self.timer = None
        self.process = None
        self.started = monotonic()
        self.wm = context.window_manager
        try:
            request = {
                "paths": paths(state), "kinds": parts(state),
                "model": context.window_manager.mpfb_tools_cloud_model.strip() or api.MODEL,
                "cache": str(library_ui.cloud_key_file().parent / "reference-cache"),
                "online": bpy.app.online_access, "refresh": state.refresh,
            }
            source = folder / "request.json"
            source.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ)
            env["MPFB_REFERENCE_KEY"] = read_key()
            env.pop("OPENAI_API_KEY", None)
            self.process = subprocess.Popen(
                [bpy.app.binary_path, "-b", "-Y", "--factory-startup", "-t", "2", "--python-exit-code", "1",
                 "-P", str(Path(__file__).with_name("cloud_worker.py")), "--", str(source), str(self.result)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
            )
            self.timer = self.wm.event_timer_add(.25, window=context.window)
            self.wm.modal_handler_add(self)
            state.status = "Prüfe lokale Analyse und Referenzbilder …"
            _pending = self
            if context.area:
                context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        except (OSError, RuntimeError, ValueError) as error:
            self.release()
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

    def release(self):
        global _pending
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        if self.timer is not None:
            self.wm.event_timer_remove(self.timer)
            self.timer = None
        self.workspace.cleanup()
        if _pending is self:
            _pending = None
        for window in self.wm.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def modal(self, context, event):
        if _pending is not self:
            return {"CANCELLED"}
        state = settings(context)
        if event.type == "ESC":
            state.status = "Analyse abgebrochen."
            self.release()
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if self.process.poll() is None and monotonic() - self.started < 110:
            return {"PASS_THROUGH"}
        try:
            if self.process.poll() is None:
                raise RuntimeError("Die Analyse hat zu lange gedauert.")
            if self.process.returncode:
                raise RuntimeError("Der Prozess für die Bildanalyse wurde vorzeitig beendet.")
            result = json.loads(self.result.read_text(encoding="utf-8"))
            if "error" in result:
                raise RuntimeError(result["error"])
            accept_result(state, result, self.source)
            state.refresh = False
            return {"FINISHED"}
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            state.status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            self.release()

    def cancel(self, context):
        if _pending is self:
            self.release()


class MPFBTOOLS_OT_reference_local_preset(bpy.types.Operator):
    bl_idname = "mpfb_tools.reference_local_preset"
    bl_label = "Mit lokaler Grundform starten"
    bl_description = "Verwendet die gewählte Bibliotheksgrundform oder eine Standardform ohne API-Aufruf"

    @classmethod
    def poll(cls, context):
        return _pending is None and bool(parts(settings(context)))

    def execute(self, context):
        state = settings(context)
        recipes = {}
        for kind in parts(state):
            style = getattr(context.scene, library_ui.SELECTIONS[kind])
            if style not in api.style_ids(kind):
                style = LOCAL_STYLES[kind]
            recipes[kind] = {
                "style": style, "name": STYLES[style], "visible": True, "color": "dark_brown",
                "certainty": "medium", "notes": "",
                **{key: spec[1] for key, spec in api.PARAMETERS[kind].items()},
            }
        accept_result(state, {"recipes": recipes, "requested": False}, signature(state))
        state.status = "Lokale Grundformen · 0 API-Aufrufe"
        return {"FINISHED"}


def recipe_dict(kind, recipe):
    return api.clean_recipe(kind, {
        "visible": recipe.visible, "name": recipe.name, "style": recipe.style,
        "color": recipe.color, "certainty": recipe.certainty, "notes": recipe.notes,
        **{param: getattr(recipe, param) for param in api.PARAMETERS[kind]},
    })


def geometry_signature(kind, recipe):
    return json.dumps([recipe[key] for key in ("style", "color", *api.PARAMETERS[kind])])


def current_preview(context, kind, field):
    obj = field.preview
    if obj is not None and context.scene.objects.get(obj.name) == obj and field.visible:
        if field.preview_signature == geometry_signature(kind, recipe_dict(kind, field)):
            return obj
    return None


def target_mesh(context, selected):
    base = saved_assets.figure_base(context, selected)
    return base, figure_surface(context, base if selected.type == "CURVES" else selected)


def replace_preview(context, state):
    selected = context.active_object
    base, surface = target_mesh(context, selected)
    components = [(kind, recipe_state(state, kind)) for kind in available(state)]
    recipes = [(kind, field, recipe_dict(kind, field)) for kind, field in components if field.visible]
    if not recipes:
        raise ValueError("Wähle mindestens eine analysierte Komponente für die Vorschau.")
    kinds = {kind for kind, _, _ in recipes}
    old_objects = [obj for obj in context.scene.objects if obj.type == "CURVES"
                   and obj.get(saved_assets.GROOM_PREVIEW) in kinds and obj.get(saved_assets.OWNER) == base]
    new_objects = []
    before = set(bpy.data.user_map())
    try:
        for kind, field, recipe in recipes:
            obj = add_groom(context, surface, recipe["style"], recipe=recipe)
            obj[saved_assets.GROOM_PREVIEW] = kind
            obj[saved_assets.OWNER] = base
            new_objects.append((field, obj, geometry_signature(kind, recipe)))
    except Exception:
        discard_new(before)
        saved_assets.select_figure(context, selected, base)
        raise
    for old in old_objects:
        data = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if data.users == 0:
            bpy.data.hair_curves.remove(data)
    for field, obj, digest in new_objects:
        field.preview = obj
        field.preview_signature = digest
    saved_assets.select_figure(context, selected, base)
    return [obj for _, obj, _ in new_objects]


class MPFBTOOLS_OT_reference_preview(bpy.types.Operator):
    bl_idname = "mpfb_tools.reference_preview"
    bl_label = "Lokale Vorschau erstellen"
    bl_description = "Erzeugt oder ersetzt die Referenz-Hair-Curves auf der ausgewählten Figur"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        try:
            if context.mode == "OBJECT" and _pending is None:
                target_mesh(context, context.active_object)
                return True
        except ValueError:
            pass
        return False

    def execute(self, context):
        try:
            created = replace_preview(context, settings(context))
        except library_ui.ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{len(created)} lokale Vorschauobjekte erstellt")
        return {"FINISHED"}


class MPFBTOOLS_OT_reference_view(bpy.types.Operator):
    bl_idname = "mpfb_tools.reference_view"
    bl_label = "Haarvorschau ansehen"
    angle: bpy.props.EnumProperty(items=[("front", "Vorn", ""), ("side", "Profil", ""),
                                        ("quarter", "Dreiviertel", "")])

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        state = settings(context)
        objects = [recipe_state(state, k).preview for k in available(state)]
        objects = [obj for obj in objects if obj is not None and obj.name in context.scene.objects]
        if not objects:
            return {"CANCELLED"}
        depsgraph = context.evaluated_depsgraph_get()
        points = []
        for obj in objects:
            evaluated = obj.evaluated_get(depsgraph)
            points.extend(evaluated.matrix_world @ Vector(point) for point in evaluated.bound_box)
        low = Vector([min(p[i] for p in points) for i in range(3)])
        high = Vector([max(p[i] for p in points) for i in range(3)])
        direction = Vector({"front": (0, -1, .04), "side": (-1, -.02, .04), "quarter": (-1, -1, .15)}[self.angle])
        surface = hair_binding.mesh_surface(objects[0])
        if surface is not None:
            direction = surface.matrix_world.to_quaternion() @ direction
        view = context.space_data.region_3d
        if view is None:
            return {"CANCELLED"}
        view.view_rotation = direction.to_track_quat("Z", "Y")
        view.view_perspective = "ORTHO"
        view.view_location = (low + high) * .5
        view.view_distance = max((high - low).length * 1.25, .12)
        return {"FINISHED"}


class MPFBTOOLS_OT_reference_save(bpy.types.Operator):
    bl_idname = "mpfb_tools.reference_save"
    bl_label = "In Bibliothek speichern"
    group: bpy.props.EnumProperty(items=COMPONENTS)

    def execute(self, context):
        state = settings(context)
        recipe = recipe_state(state, self.group)
        obj = current_preview(context, self.group, recipe)
        if obj is None or self.group not in available(state):
            self.report({"ERROR"}, "Erstelle zuerst die lokale Vorschau mit den aktuellen Werten.")
            return {"CANCELLED"}
        return library_ui.publish(self, context, self.group, recipe.name, None,
                                  lambda path: saved_assets.save_groom(context, obj, path), picked_object=obj)


class MPFBTOOLS_PT_reference(bpy.types.Panel):
    bl_label = "Aus Referenzbildern erstellen"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MPFB-Tools"
    bl_parent_id = "MPFBTOOLS_PT_hair"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        area = self.layout
        state = settings(context)
        inputs = area.column()
        inputs.enabled = _pending is None
        inputs.prop(state, "main_image")
        for index, image in enumerate(state.support):
            row = inputs.row(align=True)
            row.label(text=Path(image.filepath).name, icon="IMAGE_DATA")
            row.operator("mpfb_tools.reference_remove_image", text="", icon="X").index = index
        inputs.operator("mpfb_tools.reference_add_images", icon="FILE_IMAGE")
        inputs.prop(state, "with_hair")
        inputs.prop(state, "with_beard")
        inputs.prop(state, "with_brows")
        inputs.label(text="Bildanalyse über OpenAI")
        inputs.prop(state, "refresh")
        inputs.operator("mpfb_tools.reference_analyze", icon="VIEWZOOM")
        inputs.operator("mpfb_tools.reference_local_preset", icon="CURVES_DATA")
        if state.status:
            for line in textwrap.wrap(state.status, width=35):
                area.label(text=line)
        ready = available(state)
        if not ready:
            return
        result = area.column()
        result.enabled = _pending is None
        result.operator("mpfb_tools.reference_preview", icon="CURVES_DATA")
        if any(recipe_state(state, kind).preview for kind in ready):
            row = result.row(align=True)
            for key, label in (("front", "Vorn"), ("side", "Profil"), ("quarter", "Dreiviertel")):
                row.operator("mpfb_tools.reference_view", text=label).angle = key
        certainty = {"low": "Gering", "medium": "Mittel", "high": "Hoch"}
        for kind in ready:
            recipe = recipe_state(state, kind)
            box = result.box()
            box.label(text=api.LABELS[kind])
            box.prop(recipe, "visible")
            if recipe.notes:
                for line in textwrap.wrap(recipe.notes, width=32):
                    box.label(text=line)
            if recipe.visible:
                if recipe.notes:
                    box.label(text=f"Erkennung {certainty.get(recipe.certainty, '')}")
                box.prop(recipe, "name")
                box.prop(recipe, "style")
                box.prop(recipe, "color")
                for key in api.PARAMETERS[kind]:
                    box.prop(recipe, key)
                save = box.row()
                save.enabled = current_preview(context, kind, recipe) is not None
                save.operator("mpfb_tools.reference_save", icon="FILE_TICK").group = kind


CLASSES = (
    *RECIPES.values(), MPFBTOOLS_PG_reference_path, MPFBTOOLS_PG_reference_job,
    MPFBTOOLS_OT_reference_add_images, MPFBTOOLS_OT_reference_remove_image,
    MPFBTOOLS_OT_reference_analyze, MPFBTOOLS_OT_reference_local_preset,
    MPFBTOOLS_OT_reference_preview, MPFBTOOLS_OT_reference_view,
    MPFBTOOLS_OT_reference_save, MPFBTOOLS_PT_reference,
)


def register():
    bpy.types.WindowManager.mpfb_tools_reference = bpy.props.PointerProperty(
        type=MPFBTOOLS_PG_reference_job, options={"SKIP_SAVE"})


def unregister():
    if _pending is not None:
        _pending.release()
    del bpy.types.WindowManager.mpfb_tools_reference
