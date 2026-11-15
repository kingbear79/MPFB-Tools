# Grooming anhand von Referenzbildern

Unter **Haare → Aus Referenzbildern erstellen** wählt der Nutzer ein Hauptbild und optional weitere Ansichten aus. Die Auswahl für **Frisur**, **Bart** und **Augenbrauen** erlaubt jede Kombination. Vor dem Senden sieht der Nutzer die Bilder und Komponenten. Das Hauptbild bestimmt Stil, Schnitt und Silhouette. Ergänzende Bilder liefern Ansichten und Details für verdeckte Partien.

## Analysieren und aufbauen

1. Die Responses API analysiert ausschließlich die ausgewählten Bilder. Structured Outputs liefert ein versionsgebundenes JSON-Schema mit einem Ergebnis pro gewünschter Komponente. Das Ergebnis enthält Bezeichnung, sichtbare Merkmale, verdeckte Bereiche, Unsicherheit, Referenzansichten und normalisierte Parameter. [Offizielle OpenAI-Dokumentation zu Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
2. Für jede Komponente gelten eigene Parameter. Haare benötigen unter anderem Haarlinie, Scheitel, Nackenform, Längenverlauf, Wuchsrichtung und Bündelung. Ein Bart benötigt Wangen-, Hals- und Kinnkontur sowie Übergänge zwischen Koteletten, Schnurrbart und Kinn. Augenbrauen benötigen Ansatz, Bogen, Dichte, Auslauf und Strichrichtung. Verdeckte Merkmale werden als Annahmen markiert.
3. Blender validiert Werte und generiert die Hair Curves lokal. Dazu kommen editierbare Führungssträhnen und Regionen, deren Wurzeln über das MPFB-Basismesh an das aktive Topology-Asset übertragen werden. Ein API-Ergebnis wird als Daten eingelesen. Der Renderer führt die vorhandenen, lokal geprüften Grooming-Operationen aus.
4. Vorder-, Profil- und Dreiviertelvorschau werden auf der gewählten Figur erzeugt. Der Nutzer korrigiert die Parameter und speichert die gewünschten Komponenten getrennt in der Bibliothek. Die lokale Speicherung verwendet die vorhandene Namens- und Überschreibprüfung.

## Abnahmekriterien

Die erste Umsetzung sollte mit dem dokumentierten **Textured Mohawk mit Burst Fade** und dem dazugehörigen **Langen Boxed Beard mit Fade** beginnen. Hauptbild und Zusatzbilder werden einmal zusammen und einmal mit voneinander abweichendem Schnitt getestet. Der generierte Stil muss am Hauptbild orientiert bleiben und an Basismesh, Topology-Asset und Kopfpose halten. Oberflächenbindung und Vorschau werden auch nach dem erneuten Laden aus der Bibliothek geprüft.

API-Modell und Auswahlparameter gehören zu den exportierbaren Einstellungen. Der API-Schlüssel kommt aus `OPENAI_API_KEY` oder der lokalen Blender-Konfigurationsdatei, die über den Einstellungsdialog geschrieben wird. Die Ausführung startet erst mit einer Nutzeraktion. Ein abgebrochener oder unvollständiger API-Job erzeugt keinen Bibliothekseintrag.
