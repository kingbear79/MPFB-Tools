# MPFB-Tools

Blender 4.5 oder neuer, MPFB 2 und Rigify. Das Panel befindet sich in der 3D-Ansicht unter **N → MPFB-Tools**.

- **Charakter laden** lädt den mitgelieferten Basis-Bär oder eine gespeicherte Figur mit Rig, Pose und Assets. **Figur speichern** übernimmt die ausgewählte MPFB-Figur in die Galerie.
- **Addons hinzufügen → Haare** enthält die Galerien für Frisuren, Bärte und Augenbrauen. Wähle ein gebundenes Hair-Curves-Objekt und nutze **Hair Curves als Stil speichern**, um das Grooming wiederzuverwenden.
- **Einstellungen** enthält den Bibliotheksordner und den ZIP-Import und -Export. Ein ZIP-Import legt zuerst `MPFB-Tools-Vor-Import.zip` an. Die laufende Sicherung heißt `MPFB-Tools-Bibliothek.zip`.
- **Mimik** steuert Gesichtsausdrücke der ausgewählten Figur im Objekt- und Pose-Modus. Einmal **Mimik vorbereiten** lädt die 52 MPFB-Gesichtsformen aus dem installierten Asset-Paket `faceunits01` und überträgt sie auf MPFB-Topologie, Augen, Zähne und weitere MPFB-Meshes.

## Mimik

Wähle eine Figur, ihr Rig oder eine zugehörige Haarfrisur und öffne **N → MPFB-Tools → Mimik**. Nach der Vorbereitung stehen gemeinsame Regler für beide Gesichtshälften bereit. Unter **Mimik im Detail** lassen sich die Seiten getrennt einstellen; links/rechts gilt aus Sicht der Figur. Die Haare folgen der vorhandenen Haarbindung an das sichtbare Mesh.

Wähle **Fröhlich**, **Traurig**, **Wütend**, **Überrascht** oder **Skeptisch**, stelle die **Stärke beim Anwenden** ein und klicke **Anwenden**. Das ersetzt die bisherige Mimik. **Neutral** setzt nur die Gesichtswerte zurück. Die Vorlagen sind Ausgangspunkte und können an individuelle Proportionen angepasst werden.

**Ausdruck speichern** legt die aktuellen Gesichtswerte als eigene Vorlage unter `Bibliothek/expressions` im Vorlagenordner ab. Diese Vorlagen sind auf anderen vorbereiteten Figuren verfügbar und werden mit der Bibliothek gesichert. Die aktuelle Mimik bleibt auch beim Speichern einer Figur in der Charaktergalerie erhalten.

Für Animationen die Mimik einstellen und **Mimik-Keyframe** drücken. Der Button setzt alle 52 Gesichtswerte am aktuellen Frame, auch Nullwerte. Danach zum nächsten Frame wechseln, die Mimik ändern und erneut einen Keyframe setzen. Einzelne Gesichtsformen unter **Mimik im Detail** unterstützen außerdem Blenders normale Keyframe-Funktionen. Die Schnellregler zeigen den aktuellen Mittelwert beider Seiten; eine Änderung setzt beide Seiten auf denselben Wert.

Nach dem Hinzufügen weiterer Gesichtsteile **Mimik im Detail → Anbauteile aktualisieren** verwenden. Übertragen werden nur die Körpertopologie sowie MPFB-Augen, Zähne, Zunge, Augenbrauen und Wimpern. Kleidung und andere Anbauten erhalten keine Mimik und benötigen hierfür keine MPFB-Quelldatei. Das gilt auch für Kleidung, die aus Helper-Geometrie abgetrennt wurde und noch die geerbte MPFB-Kennung „Basemesh“ trägt.

Bei einer Körpertopologie wie **Male Muscle** kann die sichtbare Topologie oder das Rig ausgewählt werden. Das vollständige ursprüngliche Basis-Mesh bleibt die Mimikquelle und darf verborgen sein. Die Körpererkennung berücksichtigt die vollständige Vertexzahl; vor der Vorbereitung wird zusätzlich die ursprüngliche MPFB-Topologie geprüft. Das Basis-Mesh darf deshalb nicht gelöscht oder durch das Entfernen seiner Helper-Vertices verändert werden. Für die Übertragung auf die Körpertopologie und Gesichtsteile müssen deren MPFB-Quelldateien verfügbar sein.

Manuell hinzugefügte Meshes ohne MPFB-Zuordnung werden nicht automatisch verformt. Geteilte Meshes müssen vor der Vorbereitung unabhängig gemacht werden. Ausgeprägte Gesichtsposen auf den Rigify-Bones können sich mit den Shape Keys überlagern.

## Installation und Updates

In Blender unter **Bearbeiten → Einstellungen → Erweiterungen → Repositories** ein Remote-Repository hinzufügen. Als URL den [Blender-Repository-Index](https://raw.githubusercontent.com/kingbear79/MPFB-Tools/blender-repository/index.json) verwenden. Danach auf **Erweiterungen abrufen** nach **MPFB-Tools** suchen. Eine lokal heruntergeladene Extension-ZIP lässt sich auch über **Von Datenträger installieren** einspielen. Vor dem einmaligen Wechsel auf die Extension die ältere Legacy-Fassung deaktivieren. Bei einem eigenen Vorlagenordner denselben Ordner in der Extension wählen.

## Paket bauen

```sh
python3 tools/build.py --blender /path/to/blender --output dist
```

Für Releases dieselbe Version im Manifest und in `mpfb_tools/__init__.py` verwenden. Ein Tag wie `v2.0.0` baut die Extension und veröffentlicht den Blender-Index. Die Build-Dateiliste umfasst nur Programmcode, die eingebauten Vorschauen, die Haar-Node-Gruppe und die Basis-Bär-Parameter. Benutzerbibliotheken, Projekte, Bibliotheksbackups und Cloud-Schlüssel liegen außerhalb des Repositories.

[Frisuren, Bärte und Augenbrauen aus Referenzbildern](docs/referenzbilder.md)
