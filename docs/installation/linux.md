# AP-Planer unter Linux einrichten

Für 64-Bit-Linux (getestet mit Ubuntu). Dauer: etwa 10 Minuten.

## 1. App herunterladen und installieren
Öffne die [Download-Seite](https://github.com/Datata1/ds-tool/releases/latest). Unter
**Assets** gibt es zwei Varianten, nimm **eine**:

**Ubuntu, Debian, Linux Mint (empfohlen): `.deb`**
1. `AP-Planer_…_amd64.deb` herunterladen.
2. Terminal im Download-Ordner öffnen und installieren:
   ```bash
   sudo apt install ./AP-Planer_*_amd64.deb
   ```
3. **AP-Planer** erscheint im App-Menü.

**Fedora, openSUSE: `.rpm`**
1. `AP-Planer-…x86_64.rpm` herunterladen.
2. Installieren, z.B. unter Fedora: `sudo dnf install ./AP-Planer-*.x86_64.rpm`

**Alle anderen (oder ohne Installation) Distributionen: `.AppImage`**
1. `AP-Planer_…_amd64.AppImage` herunterladen.
2. Ausführbar machen und starten:
   ```bash
   chmod +x AP-Planer_*_amd64.AppImage
   ./AP-Planer_*_amd64.AppImage
   ```
3. Startet sie nicht und meldet etwas mit *FUSE*: unter Ubuntu `sudo apt install libfuse2`
   (Ubuntu 24.04: `libfuse2t64`).

## 2. Erster Start
Geh einmal durch **Einrichtung**:
1. **Welt & Stamm:** Welt (z.B. `de260`), euer Stamm-Tag und die Wing-Tags → *Welt einrichten*.
2. **Vorgaben:** prüfen, speichern.
3. **Discord** (optional): Bot-Token eintragen, Kanäle wählen, Spieler zuordnen.
4. **DS Ultimate** (optional): API-Key eintragen, dann siehst du live, wer abgehakt hat.

Deine Daten liegen in `~/ap-planner`.

## 3. Truppen-Skript in die Schnellleiste
1. In der App: **Truppen → Truppen einlesen → „Zeile für die Schnellleiste kopieren“**.
   (Ohne App: auf der Download-Seite `truppen-schnellleiste.txt` öffnen, alles kopieren.)
2. Im Spiel: **Einstellungen → Schnellleiste → Neuen Link hinzufügen**. Name z.B.
   `AP Truppen`, als URL die kopierte Zeile einfügen → Speichern.
3. **Stamm → Mitglieder → Truppen** öffnen, **AP Truppen** klicken, warten, **Kopieren**.
4. In der App: **Aus der Zwischenablage einlesen**.

Mehr dazu: [Truppen-Skript](../truppen-skript.md).

## 4. Optional: Claude Desktop als Strategie-Berater
Unter Linux kommt der Planer als **Plugin** in Claude Desktop:
1. Einmalig **uv** installieren (startet den Planer für Claude):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   Danach einmal ab- und wieder anmelden.
2. Auf der Download-Seite **`ap-planner-plugin.zip`** herunterladen und in Claude Desktop
   unter **Plugin hochladen** hineinziehen.
3. Datenordner leer lassen (= `~/ap-planner`). Dann arbeiten App und Claude mit denselben
   Operationen.

Ausführlich: [Claude Desktop](../claude-desktop.md).

## Für den ganzen Stamm auf einem Server (Docker)
Die Oberfläche kann auch auf einem Server laufen, der immer an ist (z.B. für automatische
Erinnerungen rund um die Uhr):
```bash
docker run -d --restart unless-stopped -p 127.0.0.1:8000:8000 -v ap-planer-daten:/data ghcr.io/datata1/ds-tool:v0.1.0
```
Dann im Browser `http://localhost:8000` auf dem Server. **Achtung:** Die Oberfläche hat kein
eigenes Login. Für Zugriff von außen einen Reverse-Proxy mit Passwort davorsetzen, nie den
Port offen ins Internet stellen. Details: [`docker/compose.yaml`](../../docker/compose.yaml).

## Update auf eine neue Version
- `.deb`: die neue Datei genauso mit `sudo apt install ./…deb` installieren.
- `.AppImage`: alte Datei durch die neue ersetzen.

Deine Daten in `~/ap-planner` bleiben erhalten.

## Probleme?
- **Weiße Linien beim Scrollen (NVIDIA):** ist in der App schon abgeschaltet. Bleiben sie,
  die App so starten: `WEBKIT_DISABLE_COMPOSITING_MODE=1 ap-planner-desktop`.
- **Kein Icon im Dock:** einmal ab- und wieder anmelden.
