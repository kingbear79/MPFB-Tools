# MPFB-Tools

Blender 4.5 oder neuer, MPFB 2 und Rigify. Das Panel befindet sich in der 3D-Ansicht unter **N → MPFB-Tools**.

- **Charakter laden** lädt den mitgelieferten Basis-Bär oder eine gespeicherte Figur mit Rig, Pose und Assets. **Figur speichern** übernimmt die ausgewählte MPFB-Figur in die Galerie.
- **Addons hinzufügen → Haare** enthält die Galerien für Frisuren, Bärte und Augenbrauen. Wähle ein gebundenes Hair-Curves-Objekt und nutze **Hair Curves als Stil speichern**, um das Grooming wiederzuverwenden.
- **Einstellungen** enthält den Bibliotheksordner und den ZIP-Import und -Export. Ein ZIP-Import legt zuerst `MPFB-Tools-Vor-Import.zip` an. Die laufende Sicherung heißt `MPFB-Tools-Bibliothek.zip`.

## Installation und Updates

In Blender unter **Bearbeiten → Einstellungen → Erweiterungen → Repositories** ein Remote-Repository hinzufügen. Als URL den [Blender-Repository-Index](https://raw.githubusercontent.com/kingbear79/MPFB-Tools/blender-repository/index.json) verwenden. Danach auf **Erweiterungen abrufen** nach **MPFB-Tools** suchen. Eine lokal heruntergeladene Extension-ZIP lässt sich auch über **Von Datenträger installieren** einspielen. Vor dem einmaligen Wechsel auf die Extension die ältere Legacy-Fassung deaktivieren. Bei einem eigenen Vorlagenordner denselben Ordner in der Extension wählen.

## Paket bauen

```sh
python3 tools/build.py --blender /path/to/blender --output dist
```

Für Releases dieselbe Version im Manifest und in `mpfb_tools/__init__.py` verwenden. Ein Tag wie `v2.0.0` baut die Extension und veröffentlicht den Blender-Index. Die Build-Dateiliste umfasst nur Programmcode, die eingebauten Vorschauen, die Haar-Node-Gruppe und die Basis-Bär-Parameter. Benutzerbibliotheken, Projekte, Bibliotheksbackups und Cloud-Schlüssel liegen außerhalb des Repositories.

[Frisuren, Bärte und Augenbrauen aus Referenzbildern](docs/referenzbilder.md)
