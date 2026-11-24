# AP-Planer auf dem Mac einrichten

Für Macs mit Apple-Chip (M1, M2, M3, M4 …). Dauer: etwa 10 Minuten.
Welchen Chip du hast, steht unter  → **Über diesen Mac** („Chip: Apple M…“).
Für ältere Macs mit **Intel**-Chip gibt es noch keine App-Version.

## 1. App herunterladen und installieren
1. Öffne die [Download-Seite](https://github.com/Datata1/ds-tool/releases/latest).
2. Unter **Assets** die Datei **`AP-Planer_…_aarch64.dmg`** herunterladen.
3. Die Datei öffnen und **AP-Planer** in den Ordner **Programme** ziehen.
4. AP-Planer im Programme-Ordner öffnen. Weil die App (noch) nicht bei Apple registriert
   ist, blockiert macOS den ersten Start:
   - Meldung *„… kann nicht geöffnet werden“*: **Systemeinstellungen → Datenschutz &
     Sicherheit**, ganz nach unten scrollen → bei AP-Planer **Dennoch öffnen** → mit
     Passwort bestätigen. (Ältere macOS-Versionen: Rechtsklick auf die App → **Öffnen** →
     **Öffnen**.)
   - Meldung *„… ist beschädigt und kann nicht geöffnet werden“*: Das heißt hier nur „aus
     dem Internet, nicht registriert“. **Terminal** öffnen (Spotlight: `Terminal`), diese
     Zeile einfügen und Enter drücken:
     ```bash
     xattr -dr com.apple.quarantine /Applications/AP-Planer.app
     ```
     Danach startet die App normal.

Das ist nur beim ersten Start nötig.

## 2. Erster Start
Geh einmal durch **Einrichtung**:
1. **Welt & Stamm:** Welt (z.B. `de260`), euer Stamm-Tag und die Wing-Tags → *Welt einrichten*.
2. **Vorgaben:** prüfen, speichern.
3. **Discord** (optional): Bot-Token eintragen, Kanäle wählen, Spieler zuordnen.
4. **DS Ultimate** (optional): API-Key eintragen, dann siehst du live, wer abgehakt hat.

Deine Daten liegen im Ordner `ap-planner` in deinem Benutzerordner.

## 3. Truppen-Skript in die Schnellleiste
1. In der App: **Truppen → Truppen einlesen → „Zeile für die Schnellleiste kopieren“**.
   (Ohne App: auf der Download-Seite `truppen-schnellleiste.txt` öffnen, alles kopieren.)
2. Im Spiel: **Einstellungen → Schnellleiste → Neuen Link hinzufügen**. Name z.B.
   `AP Truppen`, als URL die kopierte Zeile einfügen → Speichern.
3. **Stamm → Mitglieder → Truppen** öffnen, **AP Truppen** klicken, warten, **Kopieren**.
4. In der App: **Aus der Zwischenablage einlesen**.

Mehr dazu: [Truppen-Skript](../truppen-skript.md).

## 4. Optional: Claude Desktop als Strategie-Berater
1. [Claude Desktop](https://claude.com/download) installieren und anmelden.
2. Auf der Download-Seite **`ap-planner.mcpb`** herunterladen und doppelt anklicken →
   **Installieren**.
3. Datenordner so lassen. Dann arbeiten App und Claude mit denselben Operationen.

Ausführlich: [Claude Desktop](../claude-desktop.md).

## Update auf eine neue Version
Neue `.dmg` herunterladen und die App im Programme-Ordner ersetzen. Deine Daten bleiben
erhalten. Eventuell ist der Schritt „Dennoch öffnen“ noch einmal nötig.
