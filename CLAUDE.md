# ap-planner - Hinweise für Agenten

KI-gestützter Angriffsplaner für Die Stämme / Tribal Wars mit Export nach DS Ultimate.
Nutzer sind meist deutschsprachige Spieler: einfach erklären, wenig Fachjargon.

## Harte Regeln
- **Kein Botting:** Das Tool (Python, MCP, App) ruft nie Spielseiten mit Login ab und führt nie
  Spielaktionen aus. Nur öffentliche Weltdaten (max. 1x/h), vom Spieler kopierte Truppen und
  DS-Ultimate-Pläne über seine Links. **Einzige Ausnahme:** das eigene Schnellleisten-Skript
  `src/ap_planner/ingame/truppen.js` - läuft im Browser des Spielers nur auf seinen Klick, liest
  nur (GET, nacheinander, mit Pause), schickt nichts an fremde Server, lädt keinen Code nach.
  Diese Eigenschaften nie aufweichen (Test `tests/test_troop_script.py`).
- **Reihenfolge ohne ms:** Gleiche Sekunde = Abschick-Reihenfolge. Ein AG landet nie ohne Off davor.
  Flexdeff nie vor dem letzten AG: möglichst dieselbe Sekunde (nach dem letzten AG geschickt),
  sonst +1 s. Details: Skill `ds-grundlagen`.
- **Profil respektieren:** `data/<welt>/profil.yaml` (`uv run ap profil`) inkl. `preferences`.
- Nur **Ansehen-Links** (`/show/`) teilen, nie Bearbeiten-Links. **Ausnahme `aktion.md`:** dort
  immer Bearbeiten-Links (Wunsch des Stammesleiters). Erzeugen mit `ap op aktion`, nie von Hand.
- Daten (Zeiten, Truppen) nie von Hand ändern: `operation.yaml` anpassen und neu rechnen.
  Bestehende Operationen nicht überschreiben, Alternativen in einen neuen Ordner.

## Skills (`.claude/skills/`)
`ds-grundlagen`, `ds-ultimate`, `profil-einrichten`, `neue-operation`, `discord-nachricht`,
`einrichtung` (geführtes Setup in Claude Desktop), `google-doc` (Spieler-Dokument als Google Doc), `train-planung` (Praxis: Offs vor AGs, AGs fest eintragen, Fake-Auswahl, Umplanen, Stolperfallen), `strategie-beratung` (nächste Ziele, Readel-Vorteil: `domain/strategy.py`).

## Ablauf
`ap init` → `ap troops sammeln` (oder `import stamm.txt`) → `/neue-operation` → `ap op solve` → `ap op check [--dsu]`
→ `ap op dsu --fuer ziele` → `ap op aktion` (aktion.md) → `/discord-nachricht` (+ `/google-doc`) → `ap op status … approved` → `ap op dsu --fuer
spieler` → `ap op discord --art dm --senden`. Doku: `docs/`.

## Code
`src/ap_planner/`: `models/`, `ingest/`, `domain/`, `solver/planner.py` (CP-SAT), `dsu.py`
(lesen), `dsu_web.py` (Pläne anlegen ohne API-Key), `dsu_api.py` (mit Key `AP_DSU_API_KEY`: anlegen, Fortschritt „abgehakt“), `discord_bot.py` + `discord_sync.py` (Befehle an Spieler: private Threads im Kanal `befehle` oder DM),
`checks.py`, `domain/returns.py` (Rückkehr), `troop_collect.py`, `export/` (u.a. `gdoc.py`), `services.py` (Kernlogik), `cli.py`,
`usecases.py` (ein `@usecase` pro Schritt, gemeinsam für MCP und Desktop-App), `mcp_server.py` (macht jeden Use-Case zum Tool), `api/` (HTTP für die Desktop-App).
**Claude Desktop** (Nicht-Coder, keine Konsole): Erweiterung `dist/ap-planner.mcpb` bzw. Plugin
`dist/ap-planner-plugin.zip` (Skills + Server in `server/`) aus `scripts/build_mcpb.py`, Datenordner über `AP_HOME` (`config.app_home`). Jeder neue CLI-Schritt
braucht einen `@usecase` (wird automatisch MCP-Tool und API-Endpunkt) + Eintrag in der Zuordnungstabelle in `mcp_server.INSTRUCTIONS`.
Anleitung: `docs/claude-desktop.md`.
**Desktop-App ohne KI:** `desktop/` (Svelte + Tauri) → `ap-planner-server` (`api/`), Installer über
`scripts/build_sidecar.py` + `.github/workflows/desktop.yml`, Docker in `docker/`. Anleitung: `docs/desktop-app.md`.
**Release:** Tag `v*` baut Installer, Claude-Plugin und Schnellleisten-Zeile (`docs/release.md`);
Spieler-Anleitungen pro System in `docs/installation/`.
mcp 2.x: `from mcp.server.mcpserver import MCPServer`. YAML-Schlüssel nie `off`/`on`/`yes`/`no`.

## Checks
`uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest`
