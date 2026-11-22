"""Reusable figure tools for Blender."""

bl_info = {
    "name": "MPFB-Tools",
    "version": (2, 4, 1),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar > MPFB-Tools",
    "category": "Object",
}

import json
import os
import shutil
import tempfile
import uuid
import textwrap
from pathlib import Path
import subprocess

import bpy
from bpy.app.handlers import persistent

from . import catalog, cloud_ui, hair_binding, library_backup, library_ui, mimic, previews, saved_assets
from .attachment import append_body, figure_surface
from .footwear import append_boots
from .shoe_fit import MPFBTOOLS_OT_refit_shoes
from .hair import MPFBTOOLS_OT_create_hair, object_type
from .groom_profiles import ICONS, STYLES
from .hairstyles import MARKER, add_groom
from .library import BODY, CATEGORIES, SHOES, entries, find_entry, register_asset


DEFAULT_DIRECTORY = str(Path.home() / "Documents" / "MPFB-Tools")
CATEGORY_ITEMS = [(key, label, "") for key, label in CATEGORIES.items()]
GENERATOR_SETTINGS = {category: f"mpfb_tools_library_{category}" for category in (BODY, SHOES)}


def generator_settings(scene, category):
    return getattr(scene, GENERATOR_SETTINGS[category])


def directory(context):
    prefs = context.preferences.addons[__package__].preferences
    value = prefs.template_directory.strip()
    legacy = context.preferences.addons.get("mpfb_tools")
    if legacy and legacy.preferences != prefs and not prefs.is_property_set("template_directory"):
        value = getattr(legacy.preferences, "template_directory", value)
    return Path(bpy.path.abspath(os.path.expanduser(value or DEFAULT_DIRECTORY))).resolve()


def directory_changed(_prefs, context):
    library_backup.mark_dirty(directory(context))
    library_ui.load_cloud_settings(context)


def selected_asset(context, category, assets):
    settings = generator_settings(context.scene, category)
    return next((entry for entry in assets if entry[0].name == settings.selected_id),
                assets[0] if assets else None)


class MPFBTOOLS_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    template_directory: bpy.props.StringProperty(
        name="Vorlagenordner", default=DEFAULT_DIRECTORY, subtype="DIR_PATH", update=directory_changed,
    )

    def draw(self, context):
        self.layout.prop(self, "template_directory")
        self.layout.operator("mpfb_tools.open_templates", icon="FILE_FOLDER")


class MPFBTOOLS_GeneratorSettings(bpy.types.PropertyGroup):
    asset_name: bpy.props.StringProperty(name="Name")
    filepath: bpy.props.StringProperty(name="Blend-Datei", subtype="FILE_PATH")
    selected_id: bpy.props.StringProperty()


def figure_rig(active, bone):
    obj = active
    while obj:
        if obj.type == "ARMATURE" and bone in obj.pose.bones:
            return obj
        if obj.type == "MESH":
            for modifier in obj.modifiers:
                rig = modifier.object if modifier.type == "ARMATURE" else None
                if rig and bone in rig.pose.bones:
                    return rig
        obj = obj.parent
    raise ValueError(f"Wähle eine Figur mit einem Rig mit Bone „{bone}“.")


def figure_selected(context):
    obj = context.active_object
    if context.mode != "OBJECT" or obj is None or not obj.select_get():
        return False
    if obj.type == "MESH":
        return object_type(obj) in {"basemesh", "proxymesh", "proxymeshes"}
    if obj.type == "ARMATURE":
        try:
            figure_surface(context, obj)
        except ValueError:
            return False
        return True
    return False


class MPFBTOOLS_OT_add_figure_addon(bpy.types.Operator):
    bl_idname = "mpfb_tools.add_figure_addon"
    bl_label = "Zur Figur hinzufügen"
    bl_options = {"REGISTER", "UNDO"}
    category: bpy.props.EnumProperty(items=CATEGORY_ITEMS)

    @classmethod
    def poll(cls, context):
        return figure_selected(context)

    def execute(self, context):
        try:
            match = selected_asset(context, self.category, entries(directory(context), self.category))
            if match is None:
                raise ValueError("Wähle eine Vorlage aus der Bibliothek aus.")
            path, info = match
            selected = context.active_object
            base = saved_assets.figure_base(context, selected)
            if self.category == SHOES:
                mesh = append_boots(context, path / "Vorlage.blend", figure_rig(selected, "hips"), self.report)
            else:
                rig = figure_rig(selected, info["bone"]) if info["bone"] else None
                mesh = append_body(context, path / "Vorlage.blend", info, figure_surface(context, selected), rig)
            mesh.name = info["name"]
            mesh[saved_assets.OWNER] = base
            if self.category == BODY and mesh.parent is not None and mesh.parent != base.parent:
                mesh.parent[saved_assets.OWNER] = base
            saved_assets.select_figure(context, selected, base)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{info['name']} hinzugefügt")
        return {"FINISHED"}


class MPFBTOOLS_OT_import_template(bpy.types.Operator):
    bl_idname = "mpfb_tools.import_template"
    bl_label = "Import"
    category: bpy.props.EnumProperty(items=CATEGORY_ITEMS)

    def invoke(self, context, event):
        if self.category in (BODY, SHOES):
            settings = generator_settings(context.scene, self.category)
            if find_entry(directory(context), self.category, settings.asset_name):
                return context.window_manager.invoke_confirm(
                    self, event, title="Vorlage überschreiben?",
                    message=f"„{settings.asset_name.strip()}“ wird durch die ausgewählte Datei ersetzt.",
                    confirm_text="Überschreiben",
                )
        return self.execute(context)

    def execute(self, context):
        if self.category not in (BODY, SHOES):
            return {"CANCELLED"}
        settings = generator_settings(context.scene, self.category)
        try:
            key = register_asset(directory(context), self.category, settings.asset_name,
                                 Path(bpy.path.abspath(settings.filepath)))
            settings.selected_id = key
            library_backup.mark_dirty(directory(context))
        except (OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{settings.asset_name.strip()} in der Bibliothek registriert")
        return {"FINISHED"}


class MPFBTOOLS_OT_new_template(bpy.types.Operator):
    bl_idname = "mpfb_tools.new_template"
    bl_label = "Neu"
    category: bpy.props.EnumProperty(items=CATEGORY_ITEMS)

    def execute(self, context):
        if self.category not in (BODY, SHOES):
            return {"CANCELLED"}
        settings = generator_settings(context.scene, self.category)
        path = directory(context) / "Entwürfe"
        name = bpy.path.clean_name(settings.asset_name.strip()) or CATEGORIES[self.category]
        output = path / f"{name}.blend"
        try:
            path.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise ValueError(f"Der Entwurf „{output.name}“ existiert bereits.")
            script = Path(__file__).with_name("generator.py")
            log = output.with_suffix(".log")
            with log.open("w", encoding="utf-8") as stream:
                process = subprocess.Popen(
                    [bpy.app.binary_path, "-b", "-Y", "--python-exit-code", "1",
                     "--python", str(script), "--", self.category, str(output)],
                    stdout=stream, stderr=subprocess.STDOUT,
                )
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.filepath = str(output)

        def open_when_ready():
            status = process.poll()
            if status is None:
                return .25
            if status == 0 and output.is_file():
                library_backup.mark_dirty(output.parent.parent)
                try:
                    subprocess.Popen([bpy.app.binary_path, "-Y", str(output)])
                    log.unlink(missing_ok=True)
                except OSError as error:
                    print(f"MPFB-Tools: {error}")
            else:
                bpy.context.window_manager.popup_menu(
                    lambda self, _: self.layout.label(text=f"Siehe {log}"),
                    title="Basisfile konnte nicht erstellt werden", icon="ERROR",
                )
            return None

        bpy.app.timers.register(open_when_ready, first_interval=.25)
        return {"FINISHED"}


class MPFBTOOLS_OT_open_templates(bpy.types.Operator):
    bl_idname = "mpfb_tools.open_templates"
    bl_label = "Vorlagenordner öffnen"

    def execute(self, context):
        try:
            folder = directory(context)
            folder.mkdir(parents=True, exist_ok=True)
            return bpy.ops.wm.path_open(filepath=str(folder))
        except (OSError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class MPFBTOOLS_OT_select_asset(bpy.types.Operator):
    bl_idname = "mpfb_tools.select_asset"
    bl_label = "Vorlage auswählen"
    bl_options = {"INTERNAL"}
    category: bpy.props.EnumProperty(items=CATEGORY_ITEMS)
    asset_id: bpy.props.StringProperty()

    def execute(self, context):
        if self.category not in (BODY, SHOES):
            return {"CANCELLED"}
        if not any(path.name == self.asset_id for path, _ in entries(directory(context), self.category)):
            self.report({"ERROR"}, "Die Vorlage ist im aktuellen Vorlagenordner nicht verfügbar.")
            return {"CANCELLED"}
        generator_settings(context.scene, self.category).selected_id = self.asset_id
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


def managed_asset(operator, context):
    for path, asset in entries(directory(context), operator.category):
        if path.name == operator.asset_id:
            return path, asset
    raise ValueError("Dieser Bibliothekseintrag ist nicht mehr verfügbar.")


class MPFBTOOLS_OT_rename_asset(bpy.types.Operator):
    bl_idname = "mpfb_tools.rename_asset"
    bl_label = "Addon umbenennen"
    category: bpy.props.EnumProperty(items=CATEGORY_ITEMS)
    asset_id: bpy.props.StringProperty()
    new_name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, event):
        try:
            _, asset = managed_asset(self, context)
            self.new_name = asset["name"]
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "new_name")

    def execute(self, context):
        try:
            path, asset = managed_asset(self, context)
            name = self.new_name.strip()
            if not name:
                raise ValueError("Gib dem Addon einen Namen.")
            duplicate = find_entry(directory(context), self.category, name)
            if duplicate is not None and duplicate != path:
                raise ValueError("Dieser Name ist in der Kategorie bereits vergeben.")
            asset["name"] = name
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path, delete=False) as file:
                temp = Path(file.name)
                try:
                    json.dump(asset, file, ensure_ascii=False)
                    file.close()
                    temp.replace(path / "asset.json")
                finally:
                    temp.unlink(missing_ok=True)
            library_backup.mark_dirty(directory(context))
        except (ValueError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MPFBTOOLS_OT_delete_asset(bpy.types.Operator):
    bl_idname = "mpfb_tools.delete_asset"
    bl_label = "Addon löschen"
    category: bpy.props.EnumProperty(items=CATEGORY_ITEMS)
    asset_id: bpy.props.StringProperty()
    confirmed_path: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        try:
            path, asset = managed_asset(self, context)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.confirmed_path = str(path)
        return context.window_manager.invoke_confirm(
            self, event, title="Addon aus Bibliothek löschen?",
            message=f"„{asset['name']}“ und seine gespeicherte Vorlage werden gelöscht.",
            confirm_text="Löschen", icon="WARNING",
        )

    def execute(self, context):
        try:
            path, asset = managed_asset(self, context)
            if self.confirmed_path != str(path):
                raise ValueError("Bitte bestätige das Löschen im Dialog.")
            removed = path.with_name(f".deleted-{uuid.uuid4().hex}")
            path.rename(removed)
            try:
                shutil.rmtree(removed)
            except OSError:
                removed.rename(path)
                raise
            library_backup.mark_dirty(directory(context))
        except (ValueError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"„{asset['name']}“ aus der Bibliothek gelöscht")
        return {"FINISHED"}


class AssetGallery:
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 24

    def draw(self, context):
        assets = entries(directory(context), self.category)
        selected = selected_asset(context, self.category, assets)
        grid = self.layout.grid_flow(columns=2, even_columns=True, even_rows=True, align=True)
        for path, asset in assets:
            tile = grid.box()
            image = tile.row()
            image.alignment = "CENTER"
            icon = previews.icon_for(path, self.category)
            if icon:
                image.template_icon(icon_value=icon, scale=9.0)
            else:
                image.scale_y = 8
                image.label(text="", icon="IMAGE_DATA")
            button = tile.operator(
                "mpfb_tools.select_asset", text=asset["name"],
                depress=selected is not None and selected[0] == path,
            )
            button.category = self.category
            button.asset_id = path.name


class MPFBTOOLS_PT_body_gallery(AssetGallery, bpy.types.Panel):
    bl_label = "Körperteile"
    category = BODY


class MPFBTOOLS_PT_shoe_gallery(AssetGallery, bpy.types.Panel):
    bl_label = "Schuhe"
    category = SHOES


class SidebarPanel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MPFB-Tools"


class MPFBTOOLS_PT_addons(SidebarPanel, bpy.types.Panel):
    bl_label = "Addons hinzufügen"
    bl_order = 10

    def draw(self, context):
        for category, label in CATEGORIES.items():
            box = self.layout.box()
            box.label(text=label)
            if category in (BODY, SHOES):
                assets = entries(directory(context), category)
                selected = selected_asset(context, category, assets)
                gallery = MPFBTOOLS_PT_body_gallery if category == BODY else MPFBTOOLS_PT_shoe_gallery
                picker = box.row()
                picker.enabled = selected is not None
                picker.popover(
                    panel=gallery.__name__, text=selected[1]["name"] if selected else "Keine Vorlagen",
                    icon_value=previews.icon_for(selected[0], category) if selected else 0,
                )
                row = box.row()
                row.enabled = selected is not None and figure_selected(context)
                row.operator("mpfb_tools.add_figure_addon", icon="APPEND_BLEND").category = category
                if selected:
                    actions = box.row(align=True)
                    actions.operator_context = "INVOKE_DEFAULT"
                    for operator, icon in (("rename_asset", "GREASEPENCIL"), ("delete_asset", "TRASH")):
                        action = actions.operator(f"mpfb_tools.{operator}", icon=icon)
                        action.category = category
                        action.asset_id = selected[0].name
            if category == SHOES:
                box.operator("mpfb_tools.refit_shoes", icon="FILE_REFRESH")
        self.layout.operator("mpfb_tools.open_templates", icon="FILE_FOLDER")


def groom_icon(style):
    path = ICONS / f"{style}.png"
    if not path.is_file():
        return 0
    key = str(path)
    if key not in previews.icons:
        previews.icons.load(key, key, "IMAGE")
    return previews.icons[key].icon_id


GROOM_SELECTIONS = library_ui.SELECTIONS


def selected_groom(scene, beard=False, eyebrow=False):
    prefix = "A" if eyebrow else "B" if beard else "H"
    style = getattr(scene, GROOM_SELECTIONS[prefix])
    if style == "classic_side_part":
        return "H01" if prefix == "H" else ""
    return style


class MPFBTOOLS_OT_select_hairstyle(bpy.types.Operator):
    bl_idname = "mpfb_tools.select_hairstyle"
    bl_label = "Stil auswählen"
    bl_options = {"INTERNAL"}
    style: bpy.props.StringProperty(default="H01")

    def execute(self, context):
        if self.style not in STYLES:
            return {"CANCELLED"}
        setattr(context.scene, GROOM_SELECTIONS[self.style[0]], self.style)
        return {"FINISHED"}


class MPFBTOOLS_OT_add_hairstyle(bpy.types.Operator):
    bl_idname = "mpfb_tools.add_hairstyle"
    bl_label = "Stil hinzufügen"
    bl_options = {"REGISTER", "UNDO"}
    beard: bpy.props.BoolProperty()
    eyebrow: bpy.props.BoolProperty()

    @classmethod
    def poll(cls, context):
        selected = context.active_object
        return figure_selected(context) or (
            context.mode == "OBJECT" and selected is not None and selected.select_get()
            and selected.type == "CURVES" and selected.data.surface is not None
        )

    def execute(self, context):
        prefix = "A" if self.eyebrow else "B" if self.beard else "H"
        style = selected_groom(context.scene, self.beard, self.eyebrow)
        try:
            match = catalog.lookup(directory(context), prefix, key=style)
            if match is None:
                raise ValueError("Wähle einen Stil aus der Galerie.")
            _, folder, info = match
            selected = context.active_object
            base = saved_assets.figure_base(context, selected)
            surface = figure_surface(context, base if selected.type == "CURVES" else selected)
            if folder is None:
                obj = add_groom(context, surface, style)
                obj.name = info["name"]
            else:
                obj = saved_assets.append_groom(context, surface, folder / "Vorlage.blend", info)
                obj[MARKER] = prefix
            saved_assets.select_figure(context, selected, base)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{info['name']} hinzugefügt")
        return {"FINISHED"}


class GroomGallery:
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 29

    def draw(self, context):
        library_ui.draw_gallery(self.layout, context, self.prefix)


class MPFBTOOLS_PT_hairstyle_gallery(GroomGallery, bpy.types.Panel):
    bl_label = "Frisuren"
    prefix = "H"


class MPFBTOOLS_PT_beard_gallery(GroomGallery, bpy.types.Panel):
    bl_label = "Bärte"
    prefix = "B"


class MPFBTOOLS_PT_eyebrow_gallery(GroomGallery, bpy.types.Panel):
    bl_label = "Augenbrauen"
    prefix = "A"


class MPFBTOOLS_PT_hair(SidebarPanel, bpy.types.Panel):
    bl_label = "Haare"
    bl_parent_id = "MPFBTOOLS_PT_addons"

    def draw(self, context):
        for prefix, label, panel, select_text, add_text in (
            ("H", "Frisuren", MPFBTOOLS_PT_hairstyle_gallery, "Frisur auswählen", "Frisur hinzufügen"),
            ("B", "Bärte", MPFBTOOLS_PT_beard_gallery, "Bart auswählen", "Bart hinzufügen"),
            ("A", "Augenbrauen", MPFBTOOLS_PT_eyebrow_gallery, "Brauen auswählen", "Brauen hinzufügen"),
        ):
            box = self.layout.box()
            box.label(text=label)
            style = selected_groom(context.scene, prefix == "B", prefix == "A")
            entry = catalog.lookup(directory(context), prefix, key=style)
            box.popover(panel=panel.__name__, text=entry[2]["name"] if entry else select_text,
                        icon_value=library_ui.entry_icon(entry, prefix) if entry else 0)
            row = box.row()
            row.enabled = entry is not None
            operator = row.operator("mpfb_tools.add_hairstyle", text=add_text, icon="CURVES_DATA")
            operator.beard = prefix == "B"
            operator.eyebrow = prefix == "A"
            library_ui.draw_management(box, prefix, entry)
        self.layout.operator("mpfb_tools.save_curves", icon="FILE_TICK")
        if errors := hair_binding.binding_errors(context.scene):
            box = self.layout.box()
            box.label(text="Haarbindung konnte nicht aktualisiert werden", icon="ERROR")
            for error in errors:
                for line in textwrap.wrap(error, width=39):
                    box.label(text=line)


class MPFBTOOLS_PT_mesh(SidebarPanel, bpy.types.Panel):
    bl_label = "Mesh-Operationen"
    bl_order = 20
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        self.layout.operator("mpfb_tools.create_hair", icon="CURVES_DATA")


class MPFBTOOLS_PT_print(SidebarPanel, bpy.types.Panel):
    bl_label = "Vorbereitung 3D-Druck"
    bl_order = 30
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        self.layout.label(text="Noch kein Druck-Workflow hinterlegt.")


class MPFBTOOLS_PT_generate(SidebarPanel, bpy.types.Panel):
    bl_label = "Generieren"
    bl_order = 40
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        for category, label in CATEGORIES.items():
            box = self.layout.box()
            box.label(text=label)
            if category not in (BODY, SHOES):
                continue
            settings = generator_settings(context.scene, category)
            box.prop(settings, "asset_name")
            box.prop(settings, "filepath")
            row = box.row(align=True)
            row.operator("mpfb_tools.new_template", icon="FILE_NEW").category = category
            import_button = row.row()
            path = Path(bpy.path.abspath(settings.filepath))
            import_button.enabled = bool(settings.asset_name.strip()) and path.suffix.lower() == ".blend" and path.is_file()
            import_button.operator("mpfb_tools.import_template", icon="IMPORT").category = category


CLASSES = (
    MPFBTOOLS_Preferences, MPFBTOOLS_GeneratorSettings, MPFBTOOLS_OT_add_figure_addon,
    MPFBTOOLS_OT_import_template, MPFBTOOLS_OT_new_template, MPFBTOOLS_OT_open_templates,
    MPFBTOOLS_OT_create_hair, MPFBTOOLS_PT_addons, MPFBTOOLS_PT_mesh, MPFBTOOLS_PT_print,
    MPFBTOOLS_PT_generate, MPFBTOOLS_OT_select_asset,
    MPFBTOOLS_OT_select_hairstyle, MPFBTOOLS_OT_add_hairstyle,
    MPFBTOOLS_PT_hairstyle_gallery, MPFBTOOLS_PT_beard_gallery, MPFBTOOLS_PT_eyebrow_gallery, MPFBTOOLS_PT_hair,
    MPFBTOOLS_OT_rename_asset, MPFBTOOLS_OT_delete_asset,
    MPFBTOOLS_PT_body_gallery, MPFBTOOLS_PT_shoe_gallery, MPFBTOOLS_OT_refit_shoes,
    *library_ui.CLASSES,
    *cloud_ui.CLASSES,
    *mimic.CLASSES,
)


@persistent
def migrate_scene_settings(_filepath=None):
    for scene in bpy.data.scenes:
        for prefix, old_key in library_ui.LEGACY_GROOM_SELECTIONS.items():
            key = library_ui.SELECTIONS[prefix]
            if key not in scene and isinstance(value := scene.get(old_key), str):
                setattr(scene, key, value)
        for category in GENERATOR_SETTINGS:
            legacy = scene.get(f"mpfb_tools_{category}")
            if legacy is None or not hasattr(legacy, "get"):
                continue
            settings = generator_settings(scene, category)
            for field in ("selected_id", "asset_name", "filepath"):
                if field not in settings and isinstance(value := legacy.get(field), str):
                    settings[field] = value


def register():
    previews.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for prefix in library_ui.LEGACY_GROOM_SELECTIONS:
        setattr(bpy.types.Scene, library_ui.SELECTIONS[prefix], bpy.props.StringProperty())
    for key in GENERATOR_SETTINGS.values():
        setattr(bpy.types.Scene, key, bpy.props.PointerProperty(type=MPFBTOOLS_GeneratorSettings))
    bpy.app.handlers.load_post.append(migrate_scene_settings)
    bpy.app.timers.register(migrate_scene_settings, persistent=True)
    hair_binding.register()
    library_ui.register()
    cloud_ui.register()
    mimic.register()


def unregister():
    mimic.unregister()
    cloud_ui.unregister()
    library_ui.unregister()
    hair_binding.unregister()
    if bpy.app.timers.is_registered(migrate_scene_settings):
        bpy.app.timers.unregister(migrate_scene_settings)
    bpy.app.handlers.load_post.remove(migrate_scene_settings)
    for prefix in library_ui.LEGACY_GROOM_SELECTIONS:
        delattr(bpy.types.Scene, library_ui.SELECTIONS[prefix])
    previews.unregister()
    for key in GENERATOR_SETTINGS.values():
        delattr(bpy.types.Scene, key)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
