---
name: ds-ultimate
description: Arbeiten mit DS-Ultimate-Angriffsplänen - Workbench-Import, Titel, Ansehen- vs. Bearbeiten-Links, bestehende Wing-Pläne einbinden (merge/split/keep/copy), Prüfen und Aufräumen. Laden, wenn Pläne in DS Ultimate angelegt, gelesen oder geteilt werden.
---

# DS Ultimate (ds-ultimate.de)

## Grundlagen
- Ein Plan hat zwei Links: **Bearbeiten** (`…/edit/<key>`) und **Ansehen** (`…/show/<key>`).
  Geteilt wird **nur** der Ansehen-Link. Bearbeiten-Links bleiben lokal in `operation.yaml`.
- Ohne API-Key legt der Spieler Pläne von Hand an. `uv run ap op dsu <op> --fuer ziele|spieler`
  führt durch: neuer Plan öffnet sich, Workbench-Text liegt in der Zwischenablage (`k` = erneut
  kopieren), Spieler setzt den Titel → *Import/Export* → *Import Workbench* → *Importieren* → fügt
  den Link aus der Adressleiste ein. Das Tool prüft Titel, Plan-Nummer und Anzahl der Angriffe.
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

Das Tool liest Pläne nur (keine Änderungen in DS Ultimate). Wing-Pläne haben oft keine
Truppenzahlen - dann wird geschätzt (Review-Hinweis „geschätzt“).

## Nach Änderungen
Neu gerechnete Pläne passen nicht mehr zu bereits angelegten Plänen. `ap op check <op> --dsu`
vergleicht jeden Plan in DS Ultimate mit der Planung. Abweichende Pläne löschen und mit
`ap op dsu … --alle` neu anlegen.

## API-Key
`/toolAPI/attackPlanner/*` braucht einen API-Key, den die DS-Ultimate-Admins auf ihrem Discord
vergeben. Damit könnte das Tool Pläne selbst anlegen (noch nicht eingebaut).
