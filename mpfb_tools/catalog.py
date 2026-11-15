"""Stable gallery IDs and atomic edits to independent library entries."""
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from . import library_backup
from .groom_profiles import STYLES
from .library import entries


GROOMS = {"H": "Frisuren", "B": "Bärte", "A": "Augenbrauen"}
CHARACTERS = "characters"
SETTINGS = "Einstellungen.json"


def settings(root):
    path = root / "Bibliothek" / SETTINGS
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Die Bibliothekseinstellungen sind beschädigt.")
    return data


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".write-", delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def write_settings(root, data):
    write_json(root / "Bibliothek" / SETTINGS, data)
    library_backup.mark_dirty(root)


def gallery(root, category):
    if category not in GROOMS and category != CHARACTERS:
        raise ValueError("Unbekannte Galeriekategorie.")
    local = {path.name: (path, meta) for path, meta in entries(root, category)}
    if category in GROOMS:
        overrides = settings(root).get("styles", {})
        for style, name in STYLES.items():
            if not style.startswith(category) or style in local:
                continue
            custom = overrides.get(style, {})
            if not custom.get("hidden"):
                local[style] = (None, {"name": custom.get("name", name)})
    return sorted(((key, path, meta) for key, (path, meta) in local.items()),
                  key=lambda item: (item[2]["name"].casefold(), item[0]))


def lookup(root, category, *, key=None, name=None):
    return next((row for row in gallery(root, category)
                 if row[0] == key or (name is not None and row[2]["name"].casefold() == name.strip().casefold())), None)


def rename(root, category, key, name):
    entry = lookup(root, category, key=key)
    if not entry or not name.strip():
        raise ValueError("Wähle einen Bibliothekseintrag und einen Namen.")
    name = name.strip()
    duplicate = lookup(root, category, name=name)
    if duplicate and duplicate[0] != key:
        raise ValueError("Dieser Name ist in der Kategorie bereits vergeben.")
    _, path, meta = entry
    if path:
        write_json(path / "asset.json", dict(meta, name=name))
        library_backup.mark_dirty(root)
    else:
        data = settings(root)
        data.setdefault("styles", {})[key] = {"name": name}
        write_settings(root, data)


def delete(root, category, key):
    entry = lookup(root, category, key=key)
    if entry is None:
        raise ValueError("Der Bibliothekseintrag fehlt.")
    _, path, _ = entry
    if key in STYLES:
        data = settings(root)
        data.setdefault("styles", {})[key] = {"hidden": True}
        write_settings(root, data)
    if path is not None:
        removed = path.with_name(f".deleted-{uuid.uuid4().hex}")
        path.rename(removed)
        library_backup.mark_dirty(root)
        shutil.rmtree(removed, ignore_errors=True)


def save(root, category, name, confirmed_id, write_template):
    name = name.strip()
    if not name:
        raise ValueError("Gib einen Namen ein.")
    previous = lookup(root, category, name=name)
    if previous and previous[0] != confirmed_id:
        raise ValueError("Bestätige das Überschreiben des vorhandenen Eintrags.")
    key = previous[0] if previous else uuid.uuid4().hex
    folder = root / "Bibliothek" / category
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / key
    with tempfile.TemporaryDirectory(dir=folder, prefix=".create-") as stage:
        staging = Path(stage)
        meta = write_template(staging / "Vorlage.blend")
        write_json(staging / "asset.json", dict(meta, name=name))
        backup = None
        if final.exists():
            backup = final.with_name(f".backup-{uuid.uuid4().hex}")
            final.rename(backup)
        try:
            staging.rename(final)
        except OSError:
            if backup is not None:
                backup.rename(final)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    library_backup.mark_dirty(root)
    return key
