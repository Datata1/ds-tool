# Befehle

Alle Befehle mit `uv run ap …`. Hilfe zu jedem Befehl: `--help`. Die Welt kommt aus `.env`
(`ap init`), alternativ `--world de260`.

## Einrichtung & Daten
| Befehl | Zweck |
|---|---|
| `ap init` | Ersteinrichtung: Welt, Stamm, Wing → `.env`, Weltdaten, `data/<welt>/profil.yaml` |
| `ap profil` | Profil anzeigen |
| `ap sync [--force]` | Weltdaten laden (Einstellungen, Einheiten, Karte; max. 1x pro Stunde) |
| `ap info` | Welt-Einstellungen: Geschwindigkeit, Nachtbonus, ms, Minuten pro Feld |
| `ap travel A B --unit ram [--arrival "…"]` | Entfernung, Laufzeit und Abschickzeit (Dorf-ID oder `x\|y`) |
| `ap villages --player NAME \| --ally TAG \| --center x\|y --radius R` | Dörfer suchen |
| `ap troops import [DATEI…]` | Kopierte Truppen-Tabellen einlesen (ohne Datei: von stdin) |
| `ap troops show` | Importierte Truppen inkl. Spieler, aus- und eingehende Befehle |

## Operationen
`PFAD` = `data/<welt>/ops/<name>/operation.yaml`

| Befehl | Zweck |
|---|---|
| `ap op neu NAME --ankunft "YYYY-MM-DD HH:MM:SS"` | Neue Operation aus Vorlage (Profil-Werte werden übernommen) |
| `ap op solve PFAD` | Planen → `review.md`, `ziele/`, `spieler/`, `plan.json` + Kurz-Review |
| `ap op check PFAD [--dsu]` | Automatischer Review (`check.md`), mit `--dsu` Abgleich mit DS Ultimate |
| `ap op dsu PFAD --fuer ziele\|spieler [--alle]` | DS-Ultimate-Pläne geführt anlegen und prüfen |
| `ap op link PFAD KEY LINK` | Einen Plan-Link von Hand prüfen und speichern (`KEY` = `x\|y` oder Spieler) |
| `ap op links PFAD` | Gespeicherte Ansehen-Links ausgeben |
| `ap op discord PFAD --art review\|spieler [--kopieren]` | Discord-Nachricht(en) erzeugen |
| `ap op status PFAD draft\|in_review\|approved [--note …]` | Review-Status setzen |

## Agent / MCP
`.mcp.json` startet `uv run ap-planner-mcp`. Werkzeuge: `get_profile`, `list_operations`,
`write_operation`, `solve_operation`, `check_operation`, `discord_message`, `import_troops`,
`troops_overview`, `find_villages`, `player_info`, `travel_time`, `world_summary`, `sync_world`.
Ressource `ap://operation-schema`. Alle Skills stehen dort auch als Prompts zur Verfügung.
