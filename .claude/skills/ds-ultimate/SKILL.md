---
name: ds-ultimate
description: Arbeiten mit DS-Ultimate-Angriffsplänen - Workbench-Import, Titel, Ansehen- vs. Bearbeiten-Links, bestehende Wing-Pläne einbinden (merge/split/keep/copy), Prüfen und Aufräumen. Laden, wenn Pläne in DS Ultimate angelegt, gelesen oder geteilt werden.
---

# DS Ultimate (ds-ultimate.de)

## Grundlagen
- Ein Plan hat zwei Links: **Bearbeiten** (`…/edit/<key>`) und **Ansehen** (`…/show/<key>`).
  Geteilt wird **nur** der Ansehen-Link. Bearbeiten-Links bleiben lokal in `operation.yaml`.
- `uv run ap op dsu <op> --fuer ziele|spieler` legt die Pläne **automatisch** an (ohne API-Key,
  über dieselben Aufrufe wie die DS-Ultimate-Seite): neuer Plan, Titel, Workbench-Import, danach
  Prüfung von Titel, Plan-Nummer und Anzahl der Angriffe. Vorher Vorschau + Rückfrage (`--ja`
  überspringt sie, also nur nach Freigabe durch den Spieler).
- Nach Neuberechnung: `ap op dsu <op> --fuer … --aktualisieren` leert die gespeicherten Pläne und
  befüllt sie neu - **die Links bleiben gleich** (Discord/Doc müssen nicht geändert werden).
  Wing-Pläne werden nie geleert und nur einmal ergänzt.
- `--manuell` = alter Ablauf von Hand (Browser + Zwischenablage), falls DS Ultimate etwas ändert.
- **Titel immer setzen.** Eingeloggt öffnet „neuer Plan“ sonst wieder denselben Plan ohne Titel.
- Titel-Konvention: `ADELN|OFF|FAKE <Datum> | Ziel <x|y> <Besitzer>`.
- Discord kürzt nichts, aber ein angeklickter Link, der im Terminal umgebrochen wurde, ist
  kaputt („You are not allowed to view this page“). `ap op links` gibt ganze Links aus.

## Bestehende Pläne (z.B. vom Wing) einbinden
Im Ziel `dsu_plan: <Bearbeiten-Link>` und `dsu_mode`:
| Modus | Wirkung |
|---|---|
| `merge` | Neue Main-Angriffe in den bestehenden Plan importieren; vorhandene Main-Angriffe zählen mit |
| `split` | Neuer Plan für dieses Ziel: Wing-Angriffe übernehmen, alte Main-Angriffe ersetzen |
| `keep` | Plan bleibt exakt so, nichts Neues, Truppen gelten als verbraucht |
| `copy` | Neuer Plan für dieses Ziel mit allen Angriffen daraus (Plan mit mehreren Zielen aufteilen) |

`wing_from: [{dsu_plan: <link>, coord: "x|y"}]` leitet Wing-Angriffe von einem anderen Ziel um
(gleiche Dörfer, neue Abschickzeiten - der Wing muss die neuen Zeiten bekommen!).

Fremde Pläne (Wing) liest das Tool nur bzw. ergänzt sie einmal (merge). Wing-Pläne haben oft keine
Truppenzahlen - dann wird geschätzt (Review-Hinweis „geschätzt“).

## Nach Änderungen
Neu gerechnete Pläne passen nicht mehr zu bereits angelegten Plänen. `ap op check <op> --dsu`
vergleicht jeden Plan in DS Ultimate mit der Planung. Abweichende eigene Pläne mit
`ap op dsu … --aktualisieren` neu befüllen (gleicher Link).

## API-Key (optional)
Ohne Key nutzt `src/ap_planner/dsu_web.py` die normalen Web-Aufrufe. Mit Key (`AP_DSU_API_KEY`,
in Claude Desktop in den Einstellungen der Erweiterung) nutzt `ap op dsu` die offizielle
Schnittstelle `/toolAPI/attackPlanner/*` (`src/ap_planner/dsu_api.py`): Plan mit Titel und allen
Angriffen in einer Anfrage, Leeren, Ergänzen. Den Titel kann die API nur beim Anlegen setzen, ein
geänderter Titel geht beim Neu-Befüllen weiter über die Webseite.

Nur mit Key: **Live-Stand** `ap op fortschritt <op>` (MCP `dsu_progress`). Er zeigt pro Spieler,
was in DS Ultimate als „verschickt“ abgehakt ist, was überfällig ist und den nächsten offenen
Befehl. Das stimmt nur, wenn die Spieler abhaken. **Erinnerungen** (MCP `discord_remind`) gehen
an Spieler mit Überfälligem oder einem Befehl in den nächsten Minuten, in ihren privaten Thread
bzw. per DM. Nur nach OK des Nutzers senden.

Der Key ist persönlich (DS Ultimate protokolliert jede Anfrage pro Key): nie zeigen, nie in
Nachrichten, Dateien im Repo oder die Erweiterung schreiben.
