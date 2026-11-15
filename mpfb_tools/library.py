"""Storage and source validation for the user's editable templates."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

import bpy

from .hair import object_type

TARGET_GROUP = "Generator.Target.Position"
BODY = "body"
SHOES = "shoes"
CATEGORIES = {BODY: "Körperteile", SHOES: "Schuhe", "clothes": "Kleidung"}
BODY_OBJECT = "Körperteil"
BODY_ARMATURE = "Körperteil-Armature"
SHOE_OBJECT = "Schuhe"


def topology(mesh):
    return hashlib.sha256(str([tuple(p.vertices) for p in mesh.polygons]).encode()).hexdigest()


def marked_vertices(obj):
    group = obj.vertex_groups.get(TARGET_GROUP)
    if group is None:
        return []
    return [v.index for v in obj.data.vertices
            if any(w.group == group.index and w.weight > 0 for w in v.groups)]


def entries(directory, category):
    root = directory / "Bibliothek" / category
    result = []
    for metadata in root.glob("*/asset.json"):
        if metadata.parent.name.startswith("."):
            continue
        try:
            asset = json.loads(metadata.read_text(encoding="utf-8"))
            if isinstance(asset["name"], str) and (metadata.parent / "Vorlage.blend").is_file():
                result.append((metadata.parent, asset))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(result, key=lambda entry: (entry[1]["name"].casefold(), entry[0].name))


def discard_new(existing, keep=()):
    users = bpy.data.user_map()
    added = set(users) - existing
    dependencies = {}
    for datablock in added:
        for user in users[datablock]:
            dependencies.setdefault(user, []).append(datablock)
    retained = set(keep)
    pending = list(retained)
    while pending:
        for dependency in dependencies.get(pending.pop(), ()):
            if dependency not in retained:
                retained.add(dependency)
                pending.append(dependency)
    if unused := added - retained:
        bpy.data.batch_remove(unused)


def load_objects(path, category, *, inspect=False):
    name = BODY_OBJECT if category == BODY else SHOE_OBJECT
    with bpy.data.libraries.load(str(path), link=False) as (source, destination):
        if name not in source.objects:
            raise ValueError(f"Die Vorlage braucht ein Mesh namens „{name}“.")
        if inspect:
            destination.objects = list(source.objects)
        else:
            destination.objects = [name]
            if category == BODY and BODY_ARMATURE in source.objects:
                destination.objects.append(BODY_ARMATURE)
        names = list(destination.objects)
    return dict(zip(names, destination.objects))


def body_metadata(objects):
    mesh = objects[BODY_OBJECT]
    if mesh is None or mesh.type != "MESH":
        raise ValueError("„Körperteil“ muss ein Mesh sein.")
    armature = objects.get(BODY_ARMATURE)
    bone = ""
    if armature is not None:
        if armature.type != "ARMATURE":
            raise ValueError("„Körperteil-Armature“ muss eine Armature sein.")
        bone = armature.get("Target Bone")
        if not isinstance(bone, str) or not bone.strip():
            raise ValueError("Trage unter „Target Bone“ einen Bone-Namen ein.")
    guides = [o for o in objects.values() if o and o.type == "MESH" and
              o != mesh and TARGET_GROUP in o.vertex_groups]
    guide = guides[0] if len(guides) == 1 else None
    marks = marked_vertices(guide) if guide else []
    return {"bone": bone.strip(), "vertex": marks[0] if len(marks) == 1 else None,
            "topology": topology(guide.data) if len(marks) == 1 else None,
            "basemesh": bool(guide and object_type(guide) == "basemesh")}


def find_entry(directory, category, name):
    return next((path for path, asset in entries(directory, category)
                 if asset["name"].casefold() == name.strip().casefold()), None)


def register_asset(directory, category, name, source):
    name = name.strip()
    if not name:
        raise ValueError("Gib dem Addon einen Namen.")
    if category not in (BODY, SHOES):
        raise ValueError("Für diese Kategorie gibt es noch keinen Import.")
    if source.suffix.lower() != ".blend" or not source.is_file():
        raise ValueError("Wähle eine vorhandene .blend-Datei aus.")
    root = directory / "Bibliothek" / category
    root.mkdir(parents=True, exist_ok=True)
    previous = find_entry(directory, category, name)
    with tempfile.TemporaryDirectory(dir=root, prefix=".import-") as temporary:
        staging = Path(temporary)
        template = staging / "Vorlage.blend"
        shutil.copyfile(source, template)
        existing = set(bpy.data.user_map())
        try:
            objects = load_objects(template, category, inspect=True)
            if category == BODY:
                metadata = body_metadata(objects)
            else:
                mesh = objects[SHOE_OBJECT]
                if not mesh or mesh.type != "MESH" or not any(m.type == "ARMATURE" for m in mesh.modifiers):
                    raise ValueError("„Schuhe“ braucht ein Mesh mit Armature-Modifier.")
                metadata = {}
        finally:
            discard_new(existing)
        metadata["name"] = name
        (staging / "asset.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        target = previous or root / uuid.uuid4().hex
        if previous is None:
            staging.rename(target)
        else:
            # Keep the library ID and restore the previous files if publishing fails.
            backup = root / f".backup-{uuid.uuid4().hex}"
            previous.rename(backup)
            try:
                staging.rename(target)
            except OSError:
                backup.rename(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
    return target.name
