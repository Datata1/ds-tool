---
name: neue-operation
description: Geführter Fragebogen für eine neue Angriffs-Operation in Die Stämme. Fragt Ziele, Offs, AGs, Fakes, Flexdeff und Zeiten ab, schreibt operation.yaml, rechnet den Plan, prüft ihn automatisch und begleitet SF-Review, DS-Ultimate-Pläne, Freigabe und Versand. Laden, sobald jemand eine neue Aktion, Operation, OP, AP oder einen Angriff/Train/Fake-Plan anlegen oder planen will - auch wenn nur „neue Aktion“, „neue OP“ oder „AP planen“ gesagt wird.
---

# /neue-operation - geführte Planung

Reicht der Spieler nur „neue Aktion“ o.ä. ein, nichts voraussetzen: Vorbereitung selbst
erledigen und dann alles im Dialog abfragen, Schritt für Schritt.

Führe den Spieler Schritt für Schritt durch eine Operation. Sprich einfach und ohne Fachjargon
(meist Deutsch). Lade vorher die Skills **ds-grundlagen** (Spielregeln, Reihenfolge-Regel), **train-planung**
(Praxis und Stolperfallen) und bei
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

## 1. Fragen - immer in dieser Reihenfolge
**AskUserQuestion** für Auswahlfragen (max. 4 pro Aufruf, Empfehlung zuerst), Freitext für
Koordinaten/Namen. Immer dieselben 6 Schritte, nacheinander. Was der Spieler schon gesagt hat
oder im Profil steht, nicht neu fragen, sondern im Schritt kurz bestätigen.

**Schritt 1 - Truppen.** Sind die Truppen aktuell (`ap troops show`, Spalte `captured`)? Sonst
Übersicht in `stamm.txt` kopieren lassen → `ap troops import stamm.txt` (oder `ap troops sammeln`).
Kurz zusammenfassen: wie viele volle Offs, wie viele AGs pro Spieler verfügbar.

**Schritt 2 - Adelsziele.** Koordinaten (`ap villages --center x|y --radius 0` zeigt den
Besitzer → bestätigen). Pro Ziel: Anzahl voller Offs (`offs`, je ein Dorf), Anzahl AGs
(`nobles`), Pflicht-Offs (`off_from`), bestehender Wing-Plan (`dsu_plan` + `dsu_mode`).

**Schritt 3 - Fakeziele (optional).** Welche Dörfer, wie viele Fakes/Fake-AGs pro Ziel
(`fakes`, `fake_nobles` - verbrauchen echte AGs, darauf hinweisen). Nur Dörfer in der Nähe
der echten Ziele vorschlagen.

**Schritt 4 - Einschlag.** Datum + Uhrzeit (Serverzeit) → `arrival`, pro Ziel abweichend
`targets[].arrival`. Liegt sie im Nachtbonus → warnen.

**Schritt 5 - Wer adelt (optional).** Spieler oder Dörfer pro Ziel → `nobles_from`. Ohne
Angabe nimmt der Planer die kürzeste Laufzeit (dem Spieler so sagen).

**Schritt 6 - Strategie.** Als Auswahl fragen (multiSelect), dann in YAML übersetzen:
| Strategie | YAML |
|---|---|
| Flexdeff direkt nach dem letzten AG (gleiche Sekunde, später abgeschickt) | `support: {min_pop: …}` (Standard-Ankunft = AG-Sekunde, nie vor dem letzten AG) |
| Flexdeff zu fester Zeit (z.B. 23:00 in den Nachtbonus) | `support: {arrival: "…"}` |
| Tab-Offs zwischen den AGs einplanen | `tab_offs: N` (+ `tab_min_pop`) |
| Sekunde brechen erlaubt (Offs 1 s vor den AGs) | `allow_second_break: true/false` |
| Abstand Off → erster AG beim Abschicken | `off_send_gap_s` |
| Nur kleinste Laufzeiten / Losschick-Fenster | `send_window` |
| Wenige Dörfer für die Flexdeff | `support: {few_villages: true}` |
Alles, was nicht in die Felder passt, als Satz in `beschreibung` (steht dann im Doc und in
`aktion.md`).

**Zusammenfassung** (immer dieses Format, dann bestätigen lassen):
```
Truppen: <Stand> · <n> volle Offs · <n> AGs
Ziele:   <coord> (<Besitzer>) – <n> Offs, <n> AGs[, <n> Tab-Offs][, Adel: <wer>]
Fakes:   <coord> ×<n> … | keine
Einschlag: <Tag> <hh:mm:ss>
Strategie: <Stichpunkte>
```

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
  - {coord: "480|529", offs: 2, nobles: 4, support: {min_pop: 3000}, note: "Hauptziel"}
  - {coord: "485|527", arrival: "2026-11-10 08:16:00", offs: 1, nobles: 1, off_from: ["483|536"]}
  - {coord: "479|525", fakes: 5, fake_nobles: 1}
  - {coord: "487|525", dsu_plan: "https://ds-ultimate.de/tools/attackPlanner/<id>/edit/<key>", dsu_mode: copy}
```
Zusammenfassung zeigen und bestätigen lassen, bevor gerechnet wird.

## 3. Rechnen, prüfen, SF-Review
1. `uv run ap op solve <pfad>/operation.yaml`, dann **immer** `uv run ap op check <pfad>/operation.yaml`.
   **Fehler** (doppelte Zuweisung, AG ohne Off davor, Abschick vorbei) zuerst beheben.
   **Hinweise** erklären. **Freie Truppen** als Option anbieten.
2. Steht der Plan ohne Fehler, **sofort das Google Doc** anlegen bzw. (bei Änderungen) dasselbe
   Doc neu befüllen und für alle mit Link lesbar freigeben: `/google-doc`. Das Doc zeigt immer
   den aktuellsten Plan; ohne aktuelles Doc geht das SF-Review nicht raus.
3. `review.md` kurz zusammenfassen: Ziele, Fehlmengen mit Grund (z.B. „Losschickzeit außerhalb
   des Fensters“, „AG außerhalb der Reichweite“) und Lösungsvorschläge.
4. `uv run ap op status <pfad> in_review`. Ziel-Pläne in DS Ultimate anlegen lassen:
   `uv run ap op dsu <pfad>/operation.yaml --fuer ziele` (legt die Pläne automatisch an, fragt
   vorher einmal nach - im Terminal des Spielers starten lassen). Danach `uv run ap op check <pfad> --dsu` und `/discord-nachricht` (review, enthält den Doc-Link).
5. Feedback → YAML anpassen → neu rechnen → `ap op dsu … --aktualisieren` (gleiche Links) →
   Google Doc neu befüllen (gleicher Link, `/google-doc`).
   Danach immer `uv run ap op aktion <pfad>/operation.yaml [weitere Operationen]` → `aktion.md`
   (Discord-fertig, Bearbeiten-Links, immer gleiches Format) und `ap op rueckkehr` (Rückkehrzeiten).
   Alternativen als **eigene** Operation anlegen (neuer Ordner), die bestehende nie überschreiben.
6. Freigabe: `uv run ap op status <pfad> approved --note "…"`.

## 4. Spieler-Pläne und Ankündigung
`uv run ap op dsu <pfad>/operation.yaml --fuer spieler` (ein Plan pro Spieler, nur seine
Befehle). Nur Ansehen-Links teilen. Dann `/discord-nachricht`:
1. Befehle privat an jeden Spieler: `--art thread` (Kanal `befehle` eingerichtet), sonst `dm`.
   Vorher die Vorschau zeigen (wer bekommt was, wer hat keine Discord-Zuordnung) und auf Wunsch
   erst nur an einzelne Spieler (`--nur`).
2. Ankündigung (`--art spieler`, erst bei Status `approved`): öffentlich im Kanal mit den
   privaten Threads (sonst `ankuendigung`), erwähnt die Discord-Rollen von Stamm + Wing (werden
   automatisch über die Stammes-Tags aus dem Profil gefunden). Grunddaten ohne Details:
   Abschick-Zeitraum, Lande-Zeitraum, Gegner-Stamm und der Aufruf, zusätzliche Fakes zu
   schicken. Verrät keine Ziele, Spieler oder was echt bzw. Fake ist.
Spätere Änderungen: neu rechnen → `ap op dsu … --aktualisieren` → erneut `--art thread`. Der Bot
bearbeitet die Nachrichten und erwähnt die betroffenen Spieler mit der Bitte, neu zu laden.
