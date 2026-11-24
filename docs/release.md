# Eine Version veröffentlichen (für den Maintainer)

Ein Release besteht aus drei Teilen, die GitHub Actions automatisch baut, sobald ein Tag
`v…` gepusht wird:

| Teil | Datei(en) im Release | gebaut von |
|---|---|---|
| Desktop-App | `…_x64-setup.exe`, `…_x64_en-US.msi` (Windows), `…_aarch64.dmg` (Mac), `…_amd64.deb`, `…x86_64.rpm`, `…_amd64.AppImage` (Linux) | `.github/workflows/desktop.yml` |
| Claude Desktop | `ap-planner.mcpb` (Erweiterung), `ap-planner-plugin.zip` (Plugin) | `.github/workflows/ci.yml` |
| Truppen-Skript | `truppen-schnellleiste.txt` (eine Zeile für die Schnellleiste) | `.github/workflows/ci.yml` |
| Server | Docker-Image `ghcr.io/datata1/ds-tool:<tag>` | `.github/workflows/desktop.yml` |

Feste Links, die immer auf die neueste Version zeigen (für Discord, Forum, Doku):
- Download-Seite: <https://github.com/Datata1/ds-tool/releases/latest>
- Schnellleisten-Zeile: <https://github.com/Datata1/ds-tool/releases/latest/download/truppen-schnellleiste.txt>
- Claude-Erweiterung: <https://github.com/Datata1/ds-tool/releases/latest/download/ap-planner.mcpb>

## Einmalig vorher
1. **Repo öffentlich** (ist es), sonst können Spieler nichts herunterladen.
2. **Google-Login in der App** (optional): OAuth-Client anlegen wie in
   [google.md](google.md) beschrieben, dann im Repo unter *Settings → Secrets and variables →
   Actions* die Secrets `AP_GOOGLE_CLIENT_ID` und `AP_GOOGLE_CLIENT_SECRET` anlegen. Ohne sie
   funktioniert alles, nur „Mit Google anmelden“ fehlt (Google Doc dann von Hand).
3. **Docker-Image öffentlich** (nur einmal, nach dem ersten Release): GitHub → Profil →
   *Packages* → `ds-tool` → *Package settings* → *Change visibility* → Public.

## Release machen
1. Version an vier Stellen gleich setzen (für 0.1.0 schon erledigt):
   `pyproject.toml`, `desktop/package.json`, `desktop/src-tauri/Cargo.toml`,
   `desktop/src-tauri/tauri.conf.json`.
2. Lokal prüfen:
   ```bash
   uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
   ```
3. Alles committen und auf `main` pushen. Warten, bis *Actions → CI* grün ist (1-2 Minuten).
   Die Installer werden bei normalen Pushes nicht gebaut. Zum Testen vor einem Release:
   *Actions → Desktop-App → Run workflow*, die Dateien liegen dann unter *Artifacts*.
4. Tag setzen und pushen:
   ```bash
   git tag v0.1.0
   ```
   ```bash
   git push origin v0.1.0
   ```
5. Nach ca. 20-30 Minuten hängen alle Dateien am Release. Die Beschreibung kommt aus
   [`.github/release-notes.md`](../.github/release-notes.md), auf GitHub kannst du sie
   nachträglich bearbeiten.
6. Kurz testen: Installer auf einem System starten, `truppen-schnellleiste.txt` öffnen
   (eine Zeile, beginnt mit `javascript:`), `ap-planner.mcpb` in Claude Desktop installieren.

## Warum das Truppen-Skript nicht von GitHub nachgeladen wird
Man könnte in die Schnellleiste nur eine kurze Zeile setzen, die den Code bei jedem Klick von
GitHub lädt (`$.getScript('https://raw.githubusercontent.com/…')`). Das machen wir bewusst
nicht:
- Wer das Repo ändern kann (oder ein gekapertes Konto), könnte dann Code in den Accounts
  aller Spieler ausführen, ohne dass die es merken.
- Nachgeladene Fremdskripte sind bei InnoGames nur aus der offiziellen Skript-Bibliothek
  erlaubt; ein Skript, das komplett in der eigenen Zeile steckt, ist nachprüfbar.
- Der Test `tests/test_troop_script.py` verhindert das (`$.getScript`, `https://` verboten).

Neue Version des Skripts = Spieler ersetzen einmal die Zeile in der Schnellleiste (die
Versionsnummer steht im Skript-Fenster, die App zeigt die aktuelle).

## Später möglich
- **Code-Signing** (Windows-Zertifikat, Apple-Developer-Konto 99 $/Jahr): dann fallen die
  Warnungen beim ersten Start weg.
- **Intel-Macs:** eigener Build auf einem Intel-Runner.
- **Auto-Update** der App (Tauri-Updater).
