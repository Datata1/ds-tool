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
| `ap troops skript` | Schnellleisten-Skript (liest die Truppen aller Mitglieder mit einem Klick, Export einfach kopieren) |
| `ap troops sammeln [--stunden N] [--stamm TAG]` | Zwischenablage beobachten: jede kopierte Truppen-Seite wird sofort importiert, zeigt wer noch fehlt (Strg+C beendet) |
| `ap troops status [--stunden N]` | Wer im Stamm hat aktuelle Truppendaten (Standard: `max_troop_age_hours`), wer fehlt |
| `ap troops show` | Importierte Truppen inkl. Spieler, aus- und eingehende Befehle und Alter der Daten |

## Operationen
`PFAD` = `data/<welt>/ops/<name>/operation.yaml`

| Befehl | Zweck |
|---|---|
| `ap op neu NAME --ankunft "YYYY-MM-DD HH:MM:SS"` | Neue Operation aus Vorlage (Profil-Werte werden übernommen) |
| `ap op solve PFAD` | Planen → `review.md`, `ziele/`, `spieler/`, `plan.json` + Kurz-Review |
| `ap op check PFAD [--dsu]` | Automatischer Review (`check.md`), mit `--dsu` Abgleich mit DS Ultimate |
| `ap op dsu PFAD --fuer ziele\|spieler [--aktualisieren] [--alle] [--manuell]` | DS-Ultimate-Pläne automatisch anlegen bzw. neu befüllen (Links bleiben) und prüfen. Mit `AP_DSU_API_KEY` über die offizielle API |
| `ap op link PFAD KEY LINK` | Einen Plan-Link von Hand prüfen und speichern (`KEY` = `x\|y` oder Spieler) |
| `ap op links PFAD` | Gespeicherte Ansehen-Links ausgeben |
| `ap op aktion PFAD [PFAD…] [--datei aktion.md]` | `aktion.md`: Discord-fertig, immer gleiches Format (Kopf, Pläne pro Dorf, Pläne pro Spieler), **Bearbeiten-Links**, < 2000 Zeichen pro Nachricht |
| `ap op rueckkehr [PFAD…]` | Rückkehrzeiten (`rueckkehr.md` + `.json`, schreibt `op solve` automatisch). Ohne Pfad: alle kommenden Rückkehrer aus freigegebenen Operationen in `data/<welt>/rueckkehr.md` |
| `ap op sim PFAD --ziel x\|y [--deff spear=1000,sword=1000] [--wall 20] [--wall-ags 0] [--vorhanden …]` | Kampf-Simulation: wie viele Deff-Pakete blocken den Train (Moral, Nachtbonus, Wall, Glück −25/0/+25 %)? Mit `--vorhanden` Welle für Welle. Näherung, im Spiel-Simulator gegenprüfen |
| `ap op doc PFAD [--gdoc ID] [--ende N]` | `--ende`: bestehendes Google Doc neu befüllen (`doc_update.json` für den Docs-Connector, Link bleibt gleich) |
| `ap op doc PFAD [--gdoc ID]` | Dokument für die Spieler als `doc.html` (wird zum Google Doc, siehe [google.md](google.md)); `--gdoc` merkt sich das hochgeladene Doc |
| `ap op discord PFAD --art review\|spieler\|thread\|dm [--senden] [--nur SPIELER] [--kopieren]` | Discord-Nachricht(en) erzeugen, mit `--senden` per Bot senden bzw. bearbeiten. `thread` = jeder Spieler in seinem privaten Thread |
| `ap op fortschritt PFAD` | Wer hat in DS Ultimate „verschickt“ abgehakt, was ist überfällig? (braucht `AP_DSU_API_KEY`) |
| `ap op status PFAD draft\|in_review\|approved [--note …]` | Review-Status setzen |

## Discord-Bot
Einrichtung: [discord.md](discord.md).

| Befehl | Zweck |
|---|---|
| `ap discord einrichten --server ID --review ID --ankuendigung ID [--befehle ID]` | Server und Kanäle speichern; `--befehle` = Kanal für die privaten Threads pro Spieler |
| `ap discord spieler [--alle]` | DS-Spieler den Discord-Mitgliedern zuordnen (für DMs) |

## Agent / MCP
`.mcp.json` (Claude Code) bzw. die Erweiterung `ap-planner.mcpb` (Claude Desktop, siehe
[claude-desktop.md](claude-desktop.md)) startet `ap-planner-mcp`. Jeder Befehl oben gibt es dort
als Werkzeug, dazu `overview`, `setup_check`, `import_troops_from_clipboard`, `dsu_progress`,
`discord_remind` und `help_docs`. Alle Skills stehen als Prompts zur Verfügung, dazu `start`
und `einrichtung`.
