# Frisuren, Bärte und Augenbrauen aus Referenzbildern

1. Wähle unter **Addons hinzufügen → Haare → Aus Referenzbildern erstellen** ein Hauptbild und bei Bedarf bis zu sechs Zusatzbilder im JPEG-, PNG- oder WebP-Format. Das Hauptbild bestimmt Schnitt und Silhouette. Zusatzbilder ergänzen Ansichten auf verdeckte Partien.
2. Wähle **Frisur**, **Bart** und **Augenbrauen** in der gewünschten Kombination und klicke auf **Bilder analysieren**. Für eine neue Analyse braucht Blender Online-Zugriff und einen API-Schlüssel unter **Einstellungen → Cloud für Referenzbilder** oder in der Umgebungsvariable `OPENAI_API_KEY`.
3. Wähle eine MPFB-Figur, passe Grundform, Farbe und Regler an und klicke auf **Lokale Vorschau erstellen**. Die Hair Curves werden an das aktuelle Körpermesh einschließlich eines vorhandenen Topology-Assets gebunden. Mit **Vorn**, **Profil** und **Dreiviertel** lässt sich das Ergebnis in der 3D-Ansicht prüfen. Der Name und die Geometrie sind in Blender bearbeitbar.
4. Speichere jede gewünschte Komponente mit **In Bibliothek speichern**. Nach Änderungen an den Reglern aktualisierst du zuerst die Vorschau. Bei einem vorhandenen Namen fragt das Tool vor dem Überschreiben nach.

## API-Verbrauch

Die Analyse verwendet standardmäßig `gpt-4.1-mini`. Das Tool reduziert und dedupliziert die Bilder lokal. OpenAI liefert in einem Aufruf für alle fehlenden Komponenten ein strukturiertes Rezept aus der ähnlichsten vorhandenen Grundform, der Haarfarbe, kurzen Beobachtungen und numerischen Parametern. Die lokale Erzeugung kann damit z. B. Deckhaarlänge und Fade, Wangenlinie und Schnurrbart oder Breite und Bogen der Brauen verändern. Die verfügbaren Grundformen und Regler bestimmen, welche Schnittdetails reproduzierbar sind. [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) · [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

Eine Analyse bleibt lokal zwischengespeichert. Bei denselben Bildinhalten und demselben Modell verwendet das Tool bereits analysierte Komponenten erneut. Ergänzt du eine Komponente, wird nur diese nachgefragt. **Erneut anfragen** ignoriert den Cache für die gerade ausgewählten Komponenten. Der Status zeigt an, ob die Analyse aus dem Cache stammt oder ein Aufruf erfolgt ist. Wenn die API Nutzungsdaten zurückliefert, zeigt Blender auch die Token-Zahlen.

**Mit lokaler Grundform starten** füllt dieselben Regler ohne Bildanalyse. Das Anpassen, Erzeugen und Speichern der Hair Curves läuft ebenfalls lokal. Der Cache enthält Rezepte und aus Bildprüfsummen gebildete Dateinamen. API-Schlüssel und Referenzbilder werden nicht in den Bibliotheks-Export aufgenommen.
