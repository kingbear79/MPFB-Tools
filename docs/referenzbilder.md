# Frisuren, Bärte und Augenbrauen aus Referenzbildern

1. Wähle unter **Addons hinzufügen → Haare → Aus Referenzbildern erstellen** ein Hauptbild und bei Bedarf bis zu sechs Zusatzbilder im JPEG-, PNG- oder WebP-Format. Das Hauptbild bestimmt Schnitt und Silhouette. Zusatzbilder ergänzen Ansichten auf verdeckte Partien.
2. Wähle **Frisur**, **Bart** und **Augenbrauen** in der gewünschten Kombination und klicke auf **Referenzen analysieren**. Für eine neue Analyse braucht Blender Online-Zugriff und einen API-Schlüssel. Kopiere den vollständigen Schlüssel im OpenAI-Dashboard und klicke unter **Einstellungen → Cloud für Referenzbilder** auf **API-Schlüssel aus Zwischenablage speichern**. Alternativ kann Blender die Umgebungsvariable `OPENAI_API_KEY` verwenden.
3. Wähle eine MPFB-Figur und klicke auf **Vorschau auf Figur erzeugen**. Die Hair Curves werden an das aktuelle Körpermesh einschließlich eines vorhandenen Topology-Assets gebunden. Mit **Vorn**, **Profil**, **Hinten** und **Dreiviertel** kannst du das Ergebnis prüfen. Unter **Schnitt und Textur bearbeiten** kannst du die Parameter der Frisur ändern und die Vorschau lokal neu erzeugen.
4. Speichere jede gewünschte Komponente mit **In Bibliothek speichern**. Nach Änderungen an den Reglern aktualisierst du zuerst die Vorschau. Bei einem vorhandenen Namen fragt das Tool vor dem Überschreiben nach.

## API-Verbrauch

Die Analyse verwendet standardmäßig `gpt-4.1-mini`. Das Tool reduziert und dedupliziert die Bilder lokal. OpenAI liefert in einem Aufruf für alle fehlenden Komponenten die Haarfarbe, kurze Beobachtungen und numerische Parameter. Bei einer Frisur schätzt die Analyse Deckhaar, Pony, Seiten, Hinterkopf und Nacken getrennt. Blender baut daraus neue Kurven mit eigener Silhouette und Lockenform auf. Bart und Brauen verwenden weiterhin ihre anpassbaren Grundformen. [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) · [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

Eine Analyse bleibt lokal zwischengespeichert. Bei denselben Bildinhalten und demselben Modell verwendet das Tool bereits analysierte Komponenten erneut. Ergänzt du eine Komponente, wird nur diese nachgefragt. **Erneut anfragen** ignoriert den Cache für die gerade ausgewählten Komponenten. Der Status zeigt an, ob die Analyse aus dem Cache stammt oder ein Aufruf erfolgt ist. Wenn die API Nutzungsdaten zurückliefert, zeigt Blender auch die Token-Zahlen.

**Manuell entwerfen** füllt die Regler ohne Bildanalyse mit Startwerten. Das Anpassen, Erzeugen und Speichern der Hair Curves läuft lokal. Der Cache enthält Rezepte und aus Bildprüfsummen gebildete Dateinamen. API-Schlüssel und Referenzbilder werden nicht in den Bibliotheks-Export aufgenommen.
