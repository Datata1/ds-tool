# ap-planner - Hinweise für Agenten

KI-gestützter Angriffsplaner für Die Stämme / Tribal Wars mit Export nach DS Ultimate.
Nutzer sind meist deutschsprachige Spieler: einfach erklären, wenig Fachjargon.

## Harte Regeln
- **Kein Botting:** nie Spielseiten mit Login abrufen, nie Spielaktionen ausführen. Nur öffentliche
  Weltdaten (max. 1x/h), vom Spieler kopierte Truppen und DS-Ultimate-Pläne über seine Links.
- **Reihenfolge ohne ms:** Gleiche Sekunde = Abschick-Reihenfolge. Ein AG landet nie ohne Off davor.
  Flexdeff nie vor dem letzten AG. Details: Skill `ds-grundlagen`.
- **Profil respektieren:** `data/<welt>/profil.yaml` (`uv run ap profil`) inkl. `preferences`.
- Nur **Ansehen-Links** (`/show/`) teilen, nie Bearbeiten-Links.
- Daten (Zeiten, Truppen) nie von Hand ändern: `operation.yaml` anpassen und neu rechnen.
  Bestehende Operationen nicht überschreiben, Alternativen in einen neuen Ordner.

## Skills (`.claude/skills/`)
`ds-grundlagen`, `ds-ultimate`, `profil-einrichten`, `neue-operation`, `discord-nachricht`.

## Ablauf
`ap init` → `ap troops import stamm.txt` → `/neue-operation` → `ap op solve` → `ap op check [--dsu]`
→ `ap op dsu --fuer ziele` → `/discord-nachricht` → `ap op status … approved` → `ap op dsu --fuer
spieler`. Doku: `docs/`.

## Code
`src/ap_planner/`: `models/`, `ingest/`, `domain/`, `solver/planner.py` (CP-SAT), `dsu.py`,
`checks.py`, `export/`, `services.py` (für CLI und MCP), `cli.py`, `mcp_server.py`.
mcp 2.x: `from mcp.server.mcpserver import MCPServer`. YAML-Schlüssel nie `off`/`on`/`yes`/`no`.

## Checks
`uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest`
