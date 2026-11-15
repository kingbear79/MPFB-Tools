"""Versioned, atomic checkpoints for the editable library."""
import json
from pathlib import Path, PurePosixPath
import shutil
from stat import S_ISLNK
import tempfile
from zipfile import BadZipFile, ZIP_STORED, ZipFile

import bpy


FILENAME = "MPFB-Tools-Bibliothek.zip"
MANIFEST = "mpfb-tools-library.json"
FORMAT = 1
ROOTS = {"Bibliothek", "Entwürfe"}
_dirty = set()


def archive_paths(root):
    for path in sorted(root.iterdir()):
        if path.is_symlink():
            continue
        if path.is_file() and path.suffix.lower() == ".blend":
            yield path
        elif path.name in ROOTS and path.is_dir():
            for member in sorted(path.rglob("*")):
                relative = member.relative_to(path)
                if (not any(part.startswith(".") for part in relative.parts)
                        and not any(parent.is_symlink() for parent in [member, *member.parents] if parent != root)
                        and member.is_file() and member.suffix.lower() not in {".blend1", ".blend2"}):
                    yield member


def export_archive(root, output):
    root.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".zip", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
            archive.writestr(MANIFEST, json.dumps({"format": FORMAT, "directories": sorted(ROOTS)}))
            for path in archive_paths(root):
                archive.write(path, path.relative_to(root).as_posix())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def checkpoint(root):
    export_archive(root, root / FILENAME)
    _dirty.discard(root)


def mark_dirty(root):
    _dirty.add(root)
    if not bpy.app.background and not bpy.app.timers.is_registered(_backup):
        bpy.app.timers.register(_backup, first_interval=.8, persistent=True)


def _backup():
    for root in list(_dirty):
        try:
            checkpoint(root)
        except OSError as error:
            print(f"MPFB-Tools · Bibliothekssicherung: {error}")
    return 12.0 if _dirty else None


def flush():
    if bpy.app.timers.is_registered(_backup):
        bpy.app.timers.unregister(_backup)
    _backup()


def import_archive(root, source):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".restore-") as workspace:
        staging = Path(workspace) / "new"
        staging.mkdir()
        with ZipFile(source) as archive:
            manifest = json.loads(archive.read(MANIFEST))
            if manifest.get("format") != FORMAT:
                raise ValueError("Diese Version der Bibliothekssicherung wird nicht unterstützt.")
            directories = manifest.get("directories")
            if (not isinstance(directories, list) or not all(isinstance(d, str) for d in directories)
                    or set(directories) != ROOTS):
                raise ValueError("Die Sicherung enthält eine ungültige Bibliotheksstruktur.")
            seen = set()
            for entry in archive.infolist():
                if entry.filename == MANIFEST:
                    continue
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or not path.parts or "\\" in entry.filename
                        or any(part in (".", "..") or part.startswith(".") for part in path.parts)
                        or S_ISLNK(entry.external_attr >> 16)
                        or path.as_posix().casefold() in seen
                        or (path.parts[0] not in ROOTS and (len(path.parts) != 1 or path.suffix.lower() != ".blend"))):
                    raise ValueError(f"Unzulässiger ZIP-Pfad „{entry.filename}“.")
                seen.add(path.as_posix().casefold())
                target = staging.joinpath(*path.parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as data, target.open("wb") as stream:
                        shutil.copyfileobj(data, stream)
        for directory in ROOTS:
            (staging / directory).mkdir(exist_ok=True)
        # Keep a recoverable snapshot of the state before replacing it.
        export_archive(root, root / "MPFB-Tools-Vor-Import.zip")
        previous = Path(workspace) / "old"
        previous.mkdir()
        installed = []
        moved = []
        try:
            for item in staging.iterdir():
                destination = root / item.name
                if destination.exists() or destination.is_symlink():
                    destination.rename(previous / item.name)
                    moved.append(item.name)
                item.rename(destination)
                installed.append(item.name)
            checkpoint(root)
        except OSError:
            for name in installed:
                (root / name).rename(staging / name)
            for name in moved:
                (previous / name).rename(root / name)
            raise


ARCHIVE_ERRORS = (OSError, ValueError, KeyError, BadZipFile)
