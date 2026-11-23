# Desktop-App (ohne KI, kostenlos)

Die Desktop-App kann alles, was Claude mit dem Planer kann – nur per Formular und Knopfdruck:
Truppen einlesen, Operation anlegen, rechnen, prüfen, DS-Ultimate-Pläne, Google Doc, Discord.
Claude (mit Abo) bleibt zusätzlich nutzbar, vor allem als Strategie-Berater.

## Installieren
Die Installer gibt es auf der GitHub-Seite unter **Releases** (oder bei jedem Build unter
*Actions → Desktop-App → Artifacts*):

| System | Datei |
|---|---|
| Windows | `AP-Planer_…_x64-setup.exe` (oder `.msi`) |
| macOS (Apple Silicon) | `AP-Planer_…_aarch64.dmg` |
| Linux | `.AppImage` (ausführbar machen, starten) oder `.deb` |

Die App ist (noch) nicht signiert. Beim ersten Start warnt das System:
- **Windows:** „Der Computer wurde durch Windows geschützt“ → *Weitere Informationen* →
  *Trotzdem ausführen*.
- **macOS:** Rechtsklick auf die App → *Öffnen* → *Öffnen* (nur beim ersten Mal).

Deine Daten liegen im Ordner `ap-planner` in deinem Benutzerordner (wie bei Claude Desktop),
Zugänge (Discord-Token, DS-Ultimate-Key, Google-Anmeldung) nur auf deinem Rechner.

## Ablauf in der App
1. **Einrichtung:** Welt, eigener Stamm, Wing → Vorgaben → Zugänge (Discord-Bot, optional
   DS-Ultimate-Key) → „Mit Google anmelden“ → Discord-Kanäle und Spieler zuordnen.
2. **Truppen:** Truppen-Skript in die Schnellleiste (ein Klick liest den ganzen Stamm) oder
   Sammel-Modus mit Strg+A / Strg+C.
3. **Operationen → Neue Operation:** Ziele, Offs, AGs, Fakes, Flexdeff → *Speichern & rechnen*.
   Sonderfälle (Wing-Pläne, manuelle Angriffe …) unter *Erweitert (YAML)*.
4. **Ergebnis:** Fehler, Hinweise, freie Truppen, alle Befehle.
5. **Veröffentlichen:** DS-Ultimate-Pläne pro Ziel → Google Doc → SF-Review → Freigabe →
   Spieler-Pläne → Befehle in die privaten Threads → öffentliche Ankündigung. Alles mit
   Vorschau, gesendet wird erst auf Knopfdruck.
6. **Laufend:** wer hat abgehakt, Erinnerungen, Rückkehrzeiten.

## Im Browser / auf einem Server (Docker)
```bash
docker compose -f docker/compose.yaml up -d     # → http://localhost:8000
```
Gleiche Oberfläche, Daten im Volume `ap-planer-daten`. Der Port ist nur auf dem eigenen
Rechner erreichbar; wer ihn für den Stamm öffnet, setzt einen Reverse-Proxy mit Login davor
(die App selbst hat im Browser-Modus keinen Login). Zwischenablage-Sammeln geht im Container
nicht – dort Text einfügen.

## Für Entwickler
- Aufbau: `desktop/` (Svelte + Tauri) ruft den Python-Dienst `ap-planner-server`
  (`src/ap_planner/api/`) auf, der jeden `@usecase` aus `usecases.py` anbietet – dieselben
  Funktionen, die Claude als Tools bekommt.
- Im Browser entwickeln: `uv run ap-planner-server --port 8765 --no-token` und in `desktop/`
  `npm install && npm run dev` → <http://localhost:1420>.
- Als App: `npm run tauri dev` (startet den Dienst selbst über `uv`). Linux braucht dafür
  `libwebkit2gtk-4.1-dev libdbus-1-dev pkg-config` u.a. (siehe Tauri-Doku).
- Installer: `uv run --with pyinstaller python scripts/build_sidecar.py` (Python-Dienst als
  Einzeldatei), dann in `desktop/`
  `npx tauri build --config src-tauri/tauri.release.conf.json`. In CI:
  `.github/workflows/desktop.yml` (Secrets `AP_GOOGLE_CLIENT_ID` / `AP_GOOGLE_CLIENT_SECRET`
  für den Google-Login, siehe `docs/google.md`).
