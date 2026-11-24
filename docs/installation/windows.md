# AP-Planer unter Windows einrichten

Für Windows 10 und 11. Dauer: etwa 10 Minuten. Du brauchst keine Programmierkenntnisse.

## 1. App herunterladen und installieren
1. Öffne die [Download-Seite](https://github.com/Datata1/ds-tool/releases/latest).
2. Unter **Assets** die Datei **`AP-Planer_…_x64-setup.exe`** herunterladen.
3. Die Datei doppelt anklicken.
4. Windows warnt: *„Der Computer wurde durch Windows geschützt“*. Das kommt, weil die App
   (noch) nicht bei Microsoft signiert ist. Auf **Weitere Informationen** → **Trotzdem
   ausführen** klicken.
5. Den Installer durchklicken. Danach findest du **AP-Planer** im Startmenü.

## 2. Erster Start
Die App öffnet sich mit der Seite **Übersicht**. Geh einmal durch **Einrichtung**:
1. **Welt & Stamm:** Welt (z.B. `de260`), euer Stamm-Tag und die Wing-Tags → *Welt einrichten*.
2. **Vorgaben:** prüfen, speichern.
3. **Discord** (optional): Bot-Token eintragen, Kanäle wählen, Spieler zuordnen. Anleitung
   direkt in der App.
4. **DS Ultimate** (optional): API-Key eintragen, dann siehst du live, wer abgehakt hat.

Deine Daten liegen in `C:\Users\<dein Name>\ap-planner`. Nichts davon geht ins Internet,
außer was du selbst verschickst (DS Ultimate, Discord, Google).

## 3. Truppen-Skript in die Schnellleiste
1. In der App: **Truppen → Truppen einlesen → „Zeile für die Schnellleiste kopieren“**.
   (Ohne App: auf der Download-Seite `truppen-schnellleiste.txt` öffnen, alles kopieren.)
2. Im Spiel: **Einstellungen → Schnellleiste → Neuen Link hinzufügen**. Name z.B.
   `AP Truppen`, als URL die kopierte Zeile einfügen → Speichern.
3. **Stamm → Mitglieder → Truppen** öffnen, in der Schnellleiste **AP Truppen** klicken,
   warten, **Kopieren** klicken.
4. In der App: **Aus der Zwischenablage einlesen**.

Mehr dazu: [Truppen-Skript](../truppen-skript.md).

## 4. Optional: Claude Desktop als Strategie-Berater
Mit einem Claude-Abo kannst du zusätzlich im Chat planen und dich beraten lassen.
1. [Claude Desktop](https://claude.com/download) installieren und anmelden.
2. Auf der Download-Seite **`ap-planner.mcpb`** herunterladen und doppelt anklicken →
   **Installieren**.
3. Datenordner so lassen. Dann arbeiten App und Claude mit denselben Operationen.

Ausführlich: [Claude Desktop](../claude-desktop.md).

## Update auf eine neue Version
Neue `…_x64-setup.exe` herunterladen und installieren. Deine Daten bleiben erhalten.
Für Claude Desktop die neue `ap-planner.mcpb` genauso installieren.

## Probleme?
- **App startet, meldet aber „Der Planer-Dienst ist nicht erreichbar“:** einmal schließen und neu
  öffnen. Hilft das nicht, blockiert vielleicht ein Virenscanner die Datei
  `ap-planner-server.exe` im Installationsordner. Dann dort eine Ausnahme eintragen.
- **Links öffnen sich nicht:** Ist ein Standard-Browser eingestellt? (Windows-Einstellungen →
  Apps → Standard-Apps.)
