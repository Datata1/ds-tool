# Truppen-Skript (Schnellleiste)

Liest im Spiel mit **einem Klick** die Truppen aller Stammesmitglieder, die ihre Truppen mit dem
Stamm teilen. Das Ergebnis kopierst du in den AP-Planer (Desktop-App, Claude oder Konsole).

- liest nur (keine Spielaktionen), eine Seite nach der anderen mit Pause
- schickt **nichts** an fremde Server und lädt keinen Code nach – der ganze Code steckt in der
  Zeile, die du in die Schnellleiste einfügst
- Quelltext zum Nachlesen: [`src/ap_planner/ingame/truppen.js`](../src/ap_planner/ingame/truppen.js)
- keine Gewähr: Ob eigene Skripte auf deiner Welt erlaubt sind, regeln die Spielregeln von InnoGames

## So kommst du an die Zeile
- **Desktop-App:** Truppen → „Truppen einlesen“ → „Zeile für die Schnellleiste kopieren“.
- **GitHub (ohne App):** [truppen-schnellleiste.txt](https://github.com/Datata1/ds-tool/releases/latest/download/truppen-schnellleiste.txt)
  öffnen (zeigt immer die neueste Version) → alles markieren und kopieren.
- **Claude:** „Gib mir das Truppen-Skript“.
- **Konsole:** `uv run ap troops skript` (legt die Zeile in die Zwischenablage).

## Einrichten und benutzen
1. Im Spiel: Einstellungen → Schnellleiste → „Neuen Link hinzufügen“. Name z.B. „AP Truppen“,
   als Ziel-URL die ganze Zeile (`javascript:…`) einfügen → Speichern. Nimmt die Schnellleiste
   die lange Zeile nicht an: im Browser ein Lesezeichen mit der Zeile als Adresse anlegen.
2. Stamm → Mitglieder → Truppen öffnen, in der Schnellleiste „AP Truppen“ klicken. Das Skript
   liest alle Mitglieder (etwa 1 Sekunde pro Spieler) und zeigt den Fortschritt.
3. Am Ende „Kopieren“ klicken und im AP-Planer „Aus der Zwischenablage einlesen“.
