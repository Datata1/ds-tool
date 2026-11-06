# Entwicklung & Architektur

```bash
uv sync
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```
CI (`.github/workflows/ci.yml`) führt dieselben Prüfungen aus.

## Aufbau (`src/ap_planner/`)
| Modul | Aufgabe |
|---|---|
| `config.py` | Einstellungen aus `.env` (`AP_WORLD`, `AP_SERVER`, `AP_DATA_DIR`, `AP_TIMEZONE`) |
| `models/` | Pydantic-Modelle: Welt, Karte, Truppen, Operation, Profil, Plan |
| `ingest/` | Weltdaten laden (`world_client`), parsen (`parse`), SQLite (`store`), Truppen-Parser (`troops/`) |
| `domain/` | Laufzeit, Abschickzeit, Nachtbonus |
| `solver/planner.py` | CP-SAT-Modell (OR-Tools): Kandidaten → Truppenbudgets → Reihenfolge-Regel → Bedarf/Ziel → Befehle → Flexdeff |
| `dsu.py` | DS-Ultimate lesen (Plan-Infos, Angriffe), nur lesend |
| `checks.py` | Automatischer Review |
| `export/` | Workbench-Format, Review-Markdown, Discord-Nachrichten |
| `services.py` | Anwendungsfälle für CLI und MCP |
| `cli.py`, `mcp_server.py` | Oberflächen |

## Planer in Kürze
Für jedes (Dorf, Ziel, Art) mit passender Laufzeit und Abschickzeit im Fenster gibt es eine
Entscheidungsvariable. Pro Dorf gelten Budgets je Einheit (Begleitschutz + Fakes ≤ Bestand, die
Off ist der Rest und muss groß genug bleiben). Die Reihenfolge-Regel ist eine harte Bedingung:
Ein AG wird nur geplant, wenn eine Off (eigene oder vom Wing) vorher landet. Fehlmengen kosten viel,
Laufzeiten wenig. Danach kommt Flexdeff als zweiter Schritt nach dem letzten AG.

## Neue Truppen-Formate
Parser liegen in `ingest/troops/`. Neue Formate (andere Sprachen oder Skript-Ausgaben) dort mit
einem Fixture in `tests/fixtures/troops/` und einem Test ergänzen.

## Skills
`.claude/skills/<name>/SKILL.md`. Allgemeines Spielwissen gehört nach `ds-grundlagen`, persönliche
Vorlieben ins Profil (`preferences`), nicht in die Skills.
