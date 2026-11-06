---
name: neue-operation
description: Geführter Fragebogen für eine neue Angriffs-Operation in Die Stämme. Fragt Ziele, Offs, AGs, Fakes, Flexdeff und Zeiten ab, schreibt operation.yaml, rechnet den Plan, prüft ihn automatisch und begleitet SF-Review, DS-Ultimate-Pläne und Freigabe.
---

# /neue-operation - geführte Planung

Führe den Spieler Schritt für Schritt durch eine Operation. Sprich einfach und ohne Fachjargon
(meist Deutsch). Lade vorher die Skills **ds-grundlagen** (Spielregeln, Reihenfolge-Regel) und bei
DS-Ultimate-Schritten **ds-ultimate**. **Kein Botting:** nie Spielseiten abrufen.

## 0. Vorbereitung (selbst prüfen, nicht fragen)
1. `cat .env`. Fehlt `AP_WORLD`: zuerst `uv run ap init` (bzw. `/profil-einrichten`).
2. `uv run ap profil`: Das Profil enthält Stamm, Wing, volle Off, Fakeschutz, Zeitfenster und
   **preferences**. Diese Vorgaben gelten, ohne erneut zu fragen. Nur nachfragen, wenn die
   Operation bewusst abweichen soll.
3. `uv run ap info`: Nachtbonus, ms-Einstellung, AG-Reichweite.
4. `uv run ap troops show`: Sind Truppen da und aktuell (Spalte `captured`)? Sind sie älter als
   `max_troop_age_hours` oder fehlen sie: Truppen-Übersichten in `stamm.txt` kopieren lassen →
   `uv run ap troops import stamm.txt`. Bei Bedarf `uv run ap sync`.

## 1. Fragen
**AskUserQuestion** für Auswahlfragen (max. 4 pro Aufruf, Empfehlung zuerst), Freitext für
Koordinaten/Namen. Nur fragen, was fehlt. Ableiten, wo möglich.

**Allgemein:** Name der Operation, Ankunftszeit (Datum + Uhrzeit, Serverzeit; im Nachtbonus? →
warnen).

**Pro echtem Ziel**
- Koordinate (`uv run ap villages --center x|y --radius 0` zeigt Besitzer → bestätigen lassen)
- Offs: Anzahl, Fusion erlaubt? Muss ein bestimmtes Dorf seine Off schicken (`off_from`)?
- AGs (`nobles`) - dürfen aus verschiedenen Dörfern/Spielern kommen
- Flexdeff nach dem letzten AG (`support: {min_pop: …}`)? Bei Readel-Gefahr empfehlen.
- Eigene Ankunftszeit für dieses Ziel?
- Gibt es schon einen DS-Ultimate-Plan (Wing/Handplanung)? → `dsu_plan` + `dsu_mode`
  (siehe Skill ds-ultimate). Sollen Wing-Angriffe von einem anderen Ziel umgeleitet werden
  (`wing_from`)?

**Fakes:** Welche Dörfer, wie viele Fakes pro Ziel, Fake-AGs (`fake_nobles` - verbrauchen echte
AGs, darauf hinweisen)?

## 2. operation.yaml schreiben
`uv run ap op neu "<Name>" --ankunft "YYYY-MM-DD HH:MM:SS"` legt
`data/<welt>/ops/<name>/operation.yaml` an. Dann die Ziele eintragen. Alles, was im Profil steht,
**nicht** wiederholen - es wird automatisch übernommen. Schema: `docs/operation.md` und
`src/ap_planner/models/operation.py` (unbekannte Felder sind verboten; Schlüssel nie `off`,
`on`, `yes`, `no` nennen - YAML-Booleans).

```yaml
name: Beispiel
arrival: "2026-11-10 08:15:00"
targets:
  - {coord: "480|529", offs: 2, fusion: true, nobles: 4, support: {min_pop: 3000}, note: "Hauptziel"}
  - {coord: "485|527", arrival: "2026-11-10 08:16:00", offs: 1, nobles: 1, off_from: ["483|536"]}
  - {coord: "479|525", fakes: 5, fake_nobles: 1}
  - {coord: "487|525", dsu_plan: "https://ds-ultimate.de/tools/attackPlanner/<id>/edit/<key>", dsu_mode: copy}
```
Zusammenfassung zeigen und bestätigen lassen, bevor gerechnet wird.

## 3. Rechnen, prüfen, SF-Review
1. `uv run ap op solve <pfad>/operation.yaml`, dann **immer** `uv run ap op check <pfad>/operation.yaml`.
   **Fehler** (doppelte Zuweisung, AG ohne Off davor, Abschick vorbei) zuerst beheben.
   **Hinweise** erklären. **Freie Truppen** als Option anbieten.
2. `review.md` kurz zusammenfassen: Ziele, Fehlmengen mit Grund (z.B. „Losschickzeit außerhalb
   des Fensters“, „AG außerhalb der Reichweite“) und Lösungsvorschläge.
3. `uv run ap op status <pfad> in_review`. Ziel-Pläne in DS Ultimate anlegen lassen:
   `uv run ap op dsu <pfad>/operation.yaml --fuer ziele` (läuft interaktiv im Terminal des
   Spielers). Danach `uv run ap op check <pfad> --dsu` und `/discord-nachricht` (review).
4. Feedback → YAML anpassen → neu rechnen → betroffene Pläne löschen und mit `--alle` neu anlegen.
   Alternativen als **eigene** Operation anlegen (neuer Ordner), die bestehende nie überschreiben.
5. Freigabe: `uv run ap op status <pfad> approved --note "…"`.

## 4. Spieler-Pläne und Ankündigung
`uv run ap op dsu <pfad>/operation.yaml --fuer spieler` (ein Plan pro Spieler, nur seine
Befehle), dann `/discord-nachricht` (spieler). Nur Ansehen-Links teilen.
