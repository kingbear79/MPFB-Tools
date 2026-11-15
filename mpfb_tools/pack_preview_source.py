"""Pack the external resources in an exported library file."""
import bpy

bpy.ops.file.pack_all()
if any(image.filepath and image.source in {"FILE", "TILED"} and not image.packed_files
       for image in bpy.data.images):
    raise RuntimeError("Mindestens eine externe Bilddatei fehlt.")
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath, compress=True)
