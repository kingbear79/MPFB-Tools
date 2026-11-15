"""Gallery management, reusable figure snapshots, and portable backups."""
import os
from pathlib import Path
import tempfile
import textwrap

import bpy
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import catalog, library_backup, previews, saved_assets


ITEMS = [(key, label, "") for key, label in catalog.GROOMS.items()]
ITEMS.append((catalog.CHARACTERS, "Figuren", ""))
SELECTIONS = {"H": "mpfb_tools_hairstyle", "B": "mpfb_tools_beard", "A": "mpfb_tools_eyebrow",
              catalog.CHARACTERS: "mpfb_tools_figure_id"}
ERRORS = (OSError, ValueError, RuntimeError, KeyError, ImportError)


def directory(context):
    from . import directory as configured_directory

    return configured_directory(context)


def choose(scene, category, key):
    setattr(scene, SELECTIONS[category], key)


def current(context, category):
    return catalog.lookup(directory(context), category,
                          key=getattr(context.scene, SELECTIONS[category]))


def entry_icon(entry, category):
    key, path, _ = entry
    if path is None:
        from . import groom_icon

        return groom_icon(key)
    return previews.icon_for(path, category)


def draw_gallery(layout, context, category, columns=3):
    items = catalog.gallery(directory(context), category)
    selected = current(context, category)
    grid = layout.grid_flow(columns=columns, even_columns=True, even_rows=True, align=True)
    for entry in items:
        key, _, info = entry
        tile = grid.box()
        row = tile.row()
        row.alignment = "CENTER"
        icon = entry_icon(entry, category)
        if icon:
            row.template_icon(icon_value=icon, scale=7)
        else:
            row.scale_y = 6
            row.label(text="", icon="IMAGE_DATA")
        label = tile.column(align=True)
        label.alignment = "CENTER"
        lines = textwrap.wrap(info["name"], width=20, break_long_words=False)
        for line in lines + [""] * max(0, 3 - len(lines)):
            label.label(text=line)
        op = tile.operator("mpfb_tools.choose_library_entry", text="Auswählen",
                           depress=selected is not None and selected[0] == key)
        op.group, op.key = category, key


def draw_management(layout, category, selected):
    if selected is None:
        return
    row = layout.row(align=True)
    row.operator_context = "INVOKE_DEFAULT"
    for command, icon in (("rename_library_entry", "GREASEPENCIL"), ("delete_library_entry", "TRASH")):
        op = row.operator(f"mpfb_tools.{command}", icon=icon)
        op.group, op.key = category, selected[0]


class MPFBTOOLS_OT_choose_library_entry(bpy.types.Operator):
    bl_idname = "mpfb_tools.choose_library_entry"
    bl_label = "Auswählen"
    bl_options = {"INTERNAL"}
    group: bpy.props.EnumProperty(items=ITEMS)
    key: bpy.props.StringProperty()

    def execute(self, context):
        if not catalog.lookup(directory(context), self.group, key=self.key):
            return {"CANCELLED"}
        choose(context.scene, self.group, self.key)
        return {"FINISHED"}


class MPFBTOOLS_OT_rename_library_entry(bpy.types.Operator):
    bl_idname = "mpfb_tools.rename_library_entry"
    bl_label = "Umbenennen"
    group: bpy.props.EnumProperty(items=ITEMS)
    key: bpy.props.StringProperty()
    name: bpy.props.StringProperty(name="Name")

    def invoke(self, context, event):
        entry = catalog.lookup(directory(context), self.group, key=self.key)
        if not entry:
            return {"CANCELLED"}
        self.name = entry[2]["name"]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            catalog.rename(directory(context), self.group, self.key, self.name)
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MPFBTOOLS_OT_delete_library_entry(bpy.types.Operator):
    bl_idname = "mpfb_tools.delete_library_entry"
    bl_label = "Löschen"
    group: bpy.props.EnumProperty(items=ITEMS)
    key: bpy.props.StringProperty()
    confirmation: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        root = directory(context)
        entry = catalog.lookup(root, self.group, key=self.key)
        if not entry:
            return {"CANCELLED"}
        self.confirmation = f"{root}:{self.group}:{self.key}:{entry[2]['name']}"
        return context.window_manager.invoke_confirm(
            self, event, title="Bibliothekseintrag löschen?",
            message=f"„{entry[2]['name']}“ aus der Bibliothek löschen?",
            confirm_text="Löschen", icon="WARNING",
        )

    def execute(self, context):
        root = directory(context)
        try:
            entry = catalog.lookup(root, self.group, key=self.key)
            if not entry or self.confirmation != f"{root}:{self.group}:{self.key}:{entry[2]['name']}":
                raise ValueError("Bestätige das Löschen im Dialog.")
            catalog.delete(root, self.group, self.key)
            if getattr(context.scene, SELECTIONS[self.group]) == self.key:
                choose(context.scene, self.group, "")
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


def publish(operator, context, group, name, confirmed, writer):
    root = directory(context)
    found = catalog.lookup(root, group, name=name)
    if found is not None and confirmed != found[0]:
        return bpy.ops.mpfb_tools.overwrite_library_entry(
            "INVOKE_DEFAULT", group=group, name=name.strip(), key=found[0],
            picked_object=context.active_object.name,
        )
    try:
        key = catalog.save(root, group, name, confirmed, writer)
        choose(context.scene, group, key)
        operator.report({"INFO"}, f"„{name.strip()}“ gespeichert")
        return {"FINISHED"}
    except ERRORS as error:
        operator.report({"ERROR"}, str(error))
        return {"CANCELLED"}


class MPFBTOOLS_OT_save_curves(bpy.types.Operator):
    bl_idname = "mpfb_tools.save_curves"
    bl_label = "Hair Curves als Stil speichern"
    name: bpy.props.StringProperty(name="Name")
    group: bpy.props.EnumProperty(items=ITEMS[:-1], name="Speichern als")

    @classmethod
    def poll(cls, context):
        selected = context.active_object
        return context.mode == "OBJECT" and selected is not None and selected.type == "CURVES"

    def invoke(self, context, event):
        obj = context.active_object
        self.name = obj.name
        style = obj.get("mpfb_tools_hairstyle", "")
        if style and style[0] in catalog.GROOMS:
            self.group = style[0]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        return publish(self, context, self.group, self.name, None,
                       lambda path: saved_assets.save_groom(context, obj, path))


class MPFBTOOLS_OT_save_character(bpy.types.Operator):
    bl_idname = "mpfb_tools.save_character"
    bl_label = "Figur speichern"
    name: bpy.props.StringProperty(name="Name")

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            return False
        try:
            saved_assets.figure_base(context, context.active_object)
            return True
        except ValueError:
            return False

    def invoke(self, context, event):
        body = saved_assets.figure_base(context, context.active_object)
        self.name = body.name.split(".body")[0]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        body = saved_assets.figure_base(context, context.active_object)
        return publish(self, context, catalog.CHARACTERS, self.name, None,
                       lambda path: saved_assets.save_character(context, body, path))


class MPFBTOOLS_OT_overwrite_library_entry(bpy.types.Operator):
    bl_idname = "mpfb_tools.overwrite_library_entry"
    bl_label = "Bibliothekseintrag überschreiben"
    group: bpy.props.EnumProperty(items=ITEMS)
    key: bpy.props.StringProperty()
    name: bpy.props.StringProperty()
    picked_object: bpy.props.StringProperty()
    confirmed: bpy.props.BoolProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        self.confirmed = True
        return context.window_manager.invoke_confirm(
            self, event, title="Vorhandenen Eintrag überschreiben?",
            message=f"„{self.name}“ durch die aktuelle Auswahl ersetzen?",
            confirm_text="Überschreiben", icon="WARNING",
        )

    def execute(self, context):
        obj = context.scene.objects.get(self.picked_object)
        entry = catalog.lookup(directory(context), self.group, key=self.key)
        if not self.confirmed or obj is None or not entry or entry[2]["name"].casefold() != self.name.casefold():
            self.report({"ERROR"}, "Die Auswahl hat sich geändert. Starte das Speichern neu.")
            return {"CANCELLED"}
        if self.group == catalog.CHARACTERS:
            body = saved_assets.figure_base(context, obj)
            writer = lambda path: saved_assets.save_character(context, body, path)
        else:
            writer = lambda path: saved_assets.save_groom(context, obj, path)
        return publish(self, context, self.group, self.name, self.key, writer)


class MPFBTOOLS_OT_load_character(bpy.types.Operator):
    bl_idname = "mpfb_tools.load_character"
    bl_label = "Charakter hinzufügen"
    bl_options = {"REGISTER", "UNDO"}
    standard: bpy.props.BoolProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        try:
            if self.standard:
                saved_assets.create_standard(context)
            else:
                entry = current(context, catalog.CHARACTERS)
                if not entry:
                    raise ValueError("Wähle eine gespeicherte Figur aus der Galerie.")
                saved_assets.append_character(context, entry[1] / "Vorlage.blend", entry[2])
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class MPFBTOOLS_PT_character_gallery(bpy.types.Panel):
    bl_label = "Figuren"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 27

    def draw(self, context):
        draw_gallery(self.layout, context, catalog.CHARACTERS, columns=2)


class MPFBTOOLS_PT_characters(bpy.types.Panel):
    bl_label = "Charakter laden"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MPFB-Tools"
    bl_order = -100

    def draw(self, context):
        self.layout.operator("mpfb_tools.load_character", text="Standard-Figur hinzufügen", icon="ARMATURE_DATA").standard = True
        chosen = current(context, catalog.CHARACTERS)
        self.layout.popover(panel=MPFBTOOLS_PT_character_gallery.__name__,
                            text=chosen[2]["name"] if chosen else "Figuren-Galerie",
                            icon_value=entry_icon(chosen, catalog.CHARACTERS) if chosen else 0)
        row = self.layout.row()
        row.enabled = chosen is not None
        row.operator("mpfb_tools.load_character", text="Ausgewählte Figur hinzufügen", icon="APPEND_BLEND")
        draw_management(self.layout, catalog.CHARACTERS, chosen)
        self.layout.operator("mpfb_tools.save_character", icon="FILE_TICK")


class MPFBTOOLS_OT_export_library(bpy.types.Operator, ExportHelper):
    bl_idname = "mpfb_tools.export_library"
    bl_label = "Bibliothek als ZIP exportieren"
    filename_ext = ".zip"
    filter_glob: bpy.props.StringProperty(default="*.zip", options={"HIDDEN"})

    def execute(self, context):
        try:
            library_backup.export_archive(directory(context), Path(self.filepath))
        except library_backup.ARCHIVE_ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "Bibliothek exportiert")
        return {"FINISHED"}


class MPFBTOOLS_OT_import_library(bpy.types.Operator, ImportHelper):
    bl_idname = "mpfb_tools.import_library"
    bl_label = "Bibliothek aus ZIP importieren"
    filename_ext = ".zip"
    filter_glob: bpy.props.StringProperty(default="*.zip", options={"HIDDEN"})

    def draw(self, context):
        self.layout.label(text="Ersetzt die aktive Bibliothek. Der bisherige Stand wird vorher gesichert.")

    def execute(self, context):
        try:
            library_backup.import_archive(directory(context), Path(self.filepath))
            load_cloud_settings(context)
        except library_backup.ARCHIVE_ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "Bibliothek wiederhergestellt")
        return {"FINISHED"}


def cloud_key_file():
    config = Path(bpy.utils.user_resource("CONFIG"))
    return config / "mpfb-tools" / "cloud-key"


def load_cloud_settings(context):
    info = catalog.settings(directory(context)).get("cloud", {})
    context.window_manager.mpfb_tools_cloud_model = info.get("model", "")


class MPFBTOOLS_OT_cloud_settings(bpy.types.Operator):
    bl_idname = "mpfb_tools.save_cloud_settings"
    bl_label = "Cloud-Einstellungen speichern"

    def execute(self, context):
        wm = context.window_manager
        try:
            model = wm.mpfb_tools_cloud_model.strip()
            key = wm.mpfb_tools_cloud_key.strip()
            if key:
                destination = cloud_key_file()
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                                 delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        stream.write(key + "\n")
                        stream.close()
                        temporary.chmod(0o600)
                        temporary.replace(destination)
                    finally:
                        temporary.unlink(missing_ok=True)
            info = catalog.settings(directory(context))
            info["cloud"] = {"model": model}
            catalog.write_settings(directory(context), info)
        except ERRORS as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            wm.mpfb_tools_cloud_key = ""
        self.report({"INFO"}, "Cloud-Einstellungen gespeichert")
        return {"FINISHED"}


class MPFBTOOLS_PT_settings(bpy.types.Panel):
    bl_label = "Einstellungen"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MPFB-Tools"
    bl_order = 100
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        prefs = context.preferences.addons[__package__].preferences
        self.layout.prop(prefs, "template_directory")
        self.layout.operator("mpfb_tools.open_templates", icon="FILE_FOLDER")
        self.layout.operator("mpfb_tools.export_library", icon="EXPORT")
        self.layout.operator("mpfb_tools.import_library", icon="IMPORT")
        box = self.layout.box()
        box.label(text="Cloud für Referenzbilder")
        box.prop(context.window_manager, "mpfb_tools_cloud_model")
        box.prop(context.window_manager, "mpfb_tools_cloud_key")
        if os.environ.get("OPENAI_API_KEY") or cloud_key_file().is_file():
            box.label(text="API-Schlüssel lokal verfügbar", icon="CHECKMARK")
        box.operator("mpfb_tools.save_cloud_settings")


CLASSES = (
    MPFBTOOLS_OT_choose_library_entry, MPFBTOOLS_OT_rename_library_entry, MPFBTOOLS_OT_delete_library_entry,
    MPFBTOOLS_OT_save_curves, MPFBTOOLS_OT_save_character, MPFBTOOLS_OT_overwrite_library_entry,
    MPFBTOOLS_OT_load_character, MPFBTOOLS_PT_character_gallery, MPFBTOOLS_PT_characters,
    MPFBTOOLS_OT_export_library, MPFBTOOLS_OT_import_library, MPFBTOOLS_OT_cloud_settings, MPFBTOOLS_PT_settings,
)


def register():
    bpy.types.Scene.mpfb_tools_figure_id = bpy.props.StringProperty()
    bpy.types.WindowManager.mpfb_tools_cloud_model = bpy.props.StringProperty(name="Bildanalyse-Modell", options={"SKIP_SAVE"})
    bpy.types.WindowManager.mpfb_tools_cloud_key = bpy.props.StringProperty(name="API-Schlüssel", subtype="PASSWORD", options={"SKIP_SAVE"})
    if not bpy.app.background:
        bpy.app.timers.register(initialize, first_interval=.2)
    bpy.app.handlers.save_post.append(on_save)


@persistent
def on_save(filepath):
    root = directory(bpy.context)
    if filepath and Path(filepath).resolve().is_relative_to(root):
        library_backup.mark_dirty(root)


def initialize():
    try:
        load_cloud_settings(bpy.context)
        library_backup.mark_dirty(directory(bpy.context))
    except ERRORS as error:
        print(f"MPFB-Tools · Bibliothek: {error}")


def unregister():
    bpy.app.handlers.save_post.remove(on_save)
    if bpy.app.timers.is_registered(initialize):
        bpy.app.timers.unregister(initialize)
    library_backup.flush()
    del bpy.types.WindowManager.mpfb_tools_cloud_key
    del bpy.types.WindowManager.mpfb_tools_cloud_model
    del bpy.types.Scene.mpfb_tools_figure_id
