# operation.yaml

Eine Operation liegt in `data/<welt>/ops/<name>/operation.yaml`. Alles, was nicht drinsteht,
kommt aus dem [Profil](profil.md). Unbekannte Felder sind ein Fehler, damit Tippfehler auffallen.
Vollständiges Schema: `src/ap_planner/models/operation.py` (bzw. MCP-Ressource
`ap://operation-schema`).

> YAML-Falle: Schlüssel heißen nie `off`, `on`, `yes` oder `no`, denn YAML liest sie als
> true/false. Deshalb heißen die Felder `off_settings` usw.

## Minimal
```yaml
name: OP Beispiel
arrival: "2026-11-10 08:15:00"      # Serverzeit (Standard Europe/Berlin)
targets:
  - coord: "500|500"
    offs: 2
    nobles: 4
```

## Allgemeine Felder
| Feld | Bedeutung | Standard (Profil) |
|---|---|---|
| `name`, `world`, `arrival` | Name, Welt, Standard-Ankunft | world aus Profil |
| `send_window: {start, end}` | Wann losgeschickt werden darf (darf über Mitternacht gehen) | Profil |
| `participants: {allies, players, exclude_players, exclude_villages}` | Wer angreift | `allies` = eigener Stamm |
| `off_settings: {min_pop, units}` | Volle Off ab … Off-Plätzen (eine Off = ein Dorf) | Profil |
| `noble_settings: {escort}` | Begleitschutz pro AG | Profil |
| `fake_settings: {unit, filler, max_per_village}` | Fake-Einheit, Auffüller bis zum Fake-Limit | Ramme |
| `home_guard` | Fakeschutz: bleibt immer daheim | Profil |
| `off_send_gap_s` | Offs mind. so viele Sekunden vor jedem AG derselben Sekunde abschicken | 2 |
| `allow_second_break` | Wenn nötig, landen Offs 1 s vor den AGs | true |
| `max_troop_age_hours` | Ab wann Truppendaten als veraltet gelten | 24 |

## Ziele (`targets`)
| Feld | Bedeutung |
|---|---|
| `coord` | Zieldorf `"x\|y"` |
| `arrival` | Eigene Ankunftszeit für dieses Ziel |
| `offs` | Anzahl voller Offs (ein Dorf je Off) |
| `off_from: ["x\|y"]` | Diese Dörfer **müssen** ihre Off hierhin schicken |
| `nobles` | Anzahl AGs (aus beliebigen Dörfern und Spielern) |
| `nobles_from: ["Spieler", "x\|y"]` | Nur diese Spieler/Dörfer schicken die AGs. Leer = wer am schnellsten ist |
| `tab_offs`, `tab_min_pop` | Tab-Offs: zusätzliche Offs, die in der AG-Sekunde **zwischen** den AGs landen (nach dem ersten, vor dem letzten AG abgeschickt). Räumen Deff ab, die der Gegner zwischen die AGs tabbt. Mindestgröße `tab_min_pop` (Standard 1000) |
| `fakes`, `fake_nobles` | Fakes bzw. Fake-AGs (verbrauchen echte AGs) |
| `support: {min_pop, units, keep_home_share, enemy_radius, arrival}` | Flexdeff nach dem letzten AG + Readel-Analyse. `arrival`: feste Ankunft (z.B. 23:00:00 für den Nachtbonus), nie vor dem letzten AG |
| `manual_attacks: [{coord, kind, slowest_unit, units, arrival, running, note}]` | Fest eingetragene Befehle. `kind`: attack, noble, fake, support. Kommen **zusätzlich** zu `offs`/`nobles`. `running: true` = schon unterwegs |
| `note` | Notiz für Review und Discord |

Der Planer entscheidet selbst, welches Dorf was schickt. Ein Dorf kann gleichzeitig seine Off
schicken, AGs mit Begleitschutz stellen und Fakes laufen lassen, solange seine Truppen reichen.
Die Off ist dann der Rest. Die **Reihenfolge-Regel** gilt immer: Kein AG landet ohne Off davor.

## Bestehende DS-Ultimate-Pläne
| Feld | Bedeutung |
|---|---|
| `dsu_plan` | Bearbeiten-Link eines bestehenden Plans (z.B. Wing) |
| `dsu_mode: merge` | Neue Angriffe in diesen Plan importieren. Vorhandene eigene Angriffe zählen mit. |
| `dsu_mode: split` | Neuer Plan: Wing-Angriffe übernehmen, alte eigene Angriffe ersetzen |
| `dsu_mode: keep` | Plan bleibt exakt so, nichts Neues, Truppen gelten als verbraucht |
| `dsu_mode: copy` | Neuer Plan mit allen Angriffen daraus für dieses Ziel |
| `wing_from: [{dsu_plan, coord}]` | Wing-Angriffe von Ziel `coord` auf dieses Ziel umleiten (neue Abschickzeiten!) |

## Vom Tool gepflegt
`status` (draft / in_review / approved), `review_notes`, `dsu_links` (gespeicherte Plan-Links,
Bearbeiten-Links nur lokal), `discord_messages` (gesendete Nachrichten) und `gdoc_id` (Google Doc).

Freitext: `beschreibung` = Abschnitt „Worum geht es?“ im Google Doc (Zeilen mit `- ` werden
Aufzählungen, `**fett**` geht).

Ein vollständiges Beispiel: [examples/operation.beispiel.yaml](../examples/operation.beispiel.yaml)
