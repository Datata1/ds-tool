---
name: train-planung
description: Praxiswissen für echte Adel-Trains, Fake-Trains, Fake-Auswahl-Pläne und spontane Umplanungen mit ap-planner - wie man Offs vor die AGs bekommt, wann Sekunden gebrochen werden, Flexdeff im Nachtbonus, AGs fest eintragen, laufende Operationen anpassen und typische Stolperfallen. Laden, bevor du einen Train planst, eine Operation änderst oder ein Ergebnis bewertest.
---

# Trains planen in der Praxis

Ergänzt **ds-grundlagen** (Spielregeln) und **neue-operation** (Ablauf). Hier steht, was sich in
echten Operationen bewährt hat, und wo der Planer überlistet werden muss.

## 1. Vor dem Rechnen: Annahmen klären
- **AG-Zahlen bestätigen lassen.** `stamm.txt` enthält oft **Gesamt**-Truppen (inkl. unterwegs).
  Ein Spieler mit „2 AG“ in den Daten hat evtl. nur 1 (oder eins steckt noch in Produktion).
  Bei jedem echten AG kurz nachfragen, wenn unklar.
- **Wer fällt aus / wer soll nicht?** („X stellt kein AG“, „Y ist unzuverlässig“) gilt nur für
  diese Operation, außer der Spieler sagt „immer“ → dann ins Profil (`preferences`).
- **Ist das Ziel noch aktuell?** Wurde es gerade geadelt (eigenes Dorf jetzt)? Dann nicht faken.
- **Uhrzeit prüfen** (`date`): Befehle, die in < 15 min raus müssen, sind unrealistisch.
- Truppen älter als ein paar Stunden und vorher lief eine Aktion? → neu importieren lassen.

## 2. Reihenfolge im Train (ohne ms)
Gleiche Sekunde = Abschick-Reihenfolge. Daraus folgt eine einfache Regel:

> Eine Off landet nur dann in **derselben Sekunde vor** einem AG, wenn sie **länger läuft** als
> das AG (früher losgeschickt wird, mit `off_send_gap_s` Abstand).

AG läuft 35 min/Feld, Ramme 30 min/Feld. Eine Off aus einem **nahen** Dorf geht also **nach** den
AGs aus weiter entfernten Dörfern los → kann nicht in derselben Sekunde davor landen.

**Wunsch der Stammesführung (Standard, wenn nichts anderes gesagt):**
1. Offs in **derselben Sekunde vor** den AGs.
2. Die **größte Off landet zuerst**, danach absteigend.
3. Sekunde brechen (Off 1 s früher) **nur als Ausweg**, z.B. für eine große Off aus einem Dorf,
   das selbst ein AG stellt oder sehr nah steht.

**So vorgehen:**
- Fernste AGs bestimmen den Takt: Je weiter das weiteste AG, desto weniger Offs passen davor.
  5 AGs mit einem weit entfernten AG ⇒ Offs müssen *noch* weiter weg stehen.
- Varianten durchrechnen und vergleichen, z.B. „5 AGs, nur 2 Offs in der Sekunde“ vs. „4 AGs,
  4 Offs in der Sekunde“. Nachtabschick (ca. 00-07 Uhr) als Nachteil benennen.
- Große nahe Offs (Dorf stellt auch ein AG): als `manual_attacks` mit `arrival` = 1 s vor den AGs.
  Landen dort mehrere Offs, gilt wieder: früher geschickt = früher da. Die größte nur dann
  zuerst, wenn sie am weitesten weg ist, sonst allein in eine eigene Sekunde.
- **Off-Zusammensetzung prüfen:** Der Solver zählt nur Off-Plätze. Jede eingeplante Off muss
  Axt, LKav **und** Rammen haben (z.B. „2502 LKav, 15 Ramme“ ist keine Off → nicht als Off
  einplanen oder nur als Zusatz benennen). Ohne Rammen nur für Tab-Offs kurz vor den AGs,
  wenn der Wall durch die ersten Offs schon fällt. Bei Zweifel Off per `off_from`/
  `exclude_villages` steuern oder manuell eintragen.
- **Fake-AGs** tragen echte Adelsgeschlechter: dieselbe Regel (Off davor). Solver und Check
  setzen das durch.

## 3. AGs und Offs fest eintragen (statt dem Solver zu überlassen)
Wenn die Aufstellung wichtig ist (wer adelt, welche Off zuerst), alles manuell eintragen und
den Solver nur für Flexdeff/Fakes nutzen:

```yaml
targets:
  - coord: "477|526"
    offs: 0
    nobles: 0            # WICHTIG: manuelle AGs kommen ZUSÄTZLICH zu nobles
    support: {min_pop: 60000, arrival: "2026-11-08 23:00:00"}
    manual_attacks:
      - {coord: "484|530", kind: attack, slowest_unit: ram, arrival: "2026-11-08 22:59:58",
         units: {axe: 4614, light: 1570, ram: 275, catapult: 60}, note: "größte Off zuerst"}
      - {coord: "495|533", kind: attack, slowest_unit: ram,
         units: {axe: 3659, light: 1495, ram: 182, catapult: 19}}
      - {coord: "478|535", kind: noble, slowest_unit: snob, units: {snob: 1, axe: 100}}
```
- `units` aus `uv run ap troops show` bzw. der Truppen-DB holen. Stellt das Dorf auch ein AG,
  den Begleitschutz (z.B. 100 Axt) von der Off abziehen.
- `manual_attacks` aus eigenen Dörfern zählen als verbraucht und stehen in den Spieler-Plänen.
- **Nicht** `exclude_villages` benutzen, um zusätzliche AGs eines Dorfs zu verhindern: Manuelle
  Angriffe aus ausgeschlossenen Dörfern gelten dann als „Wing“ und fehlen im Spieler-Plan.
  Stattdessen alle AGs manuell und `nobles: 0`.
- Manuelle Offs aus eigenen Dörfern **zählen bei `offs` mit**. Zusammen mit `off_from` also
  `offs = Anzahl off_from + Anzahl manuelle Offs`, sonst INFEASIBLE.
- `running: true` für Befehle, die schon unterwegs sind (Reihenfolge-Regel zählt sie mit).

## 4. Flexdeff und Readel
- Flexdeff landet nie vor dem letzten AG. Standard: dieselbe Sekunde wie die AGs (nach dem
  letzten AG geschickt); nur Dörfer, die das nicht schaffen, landen +1 s (Hinweis im Check).
- **Nachtbonus bunkern:** AGs auf `22:59:59`, Flexdeff mit `support: {arrival: "… 23:00:00"}`.
  Der Check-Hinweis „liegt im Nachtbonus“ ist dann gewollt.
- `min_pop` hoch ansetzen, wenn maximal gebunkert werden soll. Mini-Unterstützungen
  (< 100 Truppen) beim Ergebnis als „kann ignoriert werden“ markieren.
- Readel-Tabelle im Review lesen: nahe Gegner-Dörfer mit kurzer AG-Laufzeit benennen.

## 5. Fake-Trains und Fake-Auswahl
- **Fake-Train:** pro Ziel `offs: 1, fake_nobles: 1, fakes: 4`. Der Fake-AG braucht eine Off
  davor. Bei unzuverlässigen Spielern als Fake-AG-Steller Ersatz nennen.
- **Fake-Auswahl** („jeder sucht sich mind. 5 aus“): Für jedes Dorf × Ziel einen
  `manual_attacks`-Eintrag `{kind: fake, slowest_unit: ram}`. Nur Kombinationen, deren
  Abschick mind. 15 min in der Zukunft liegt. Optional `units` pro Dorf vorschlagen
  (1 Ramme/Kata + Füller bis zum Fake-Limit = 1 % der Dorfpunkte). Fehler „es fehlen X Rammen“
  ist bei einer Auswahl normal (niemand schickt alles). Ziele ohne AH o.ä. in `note`.
- Ergebnis für den Spieler nach Abschickzeit sortiert zeigen und bequeme Zeitfenster nennen.

## 6. Ändern, ohne Schaden anzurichten
- **Neue Variante = neuer Ordner** (`…-B-5ags`, `…-C`, `…-2259`). Bestehende Operationen nie
  überschreiben, freigegebene erst recht nicht.
- **Läuft eine Operation schon** (erste Befehle sind raus), nicht einfach `ap op solve`: Bereits
  gesendete Befehle fallen sonst als „zu spät“ raus. Gesendete als `running: true` eintragen
  oder nur den Ersatz in einer neuen Operation planen.
- `operation.yaml` wird nach `solve`/`link` neu geschrieben (alle Felder ausgeschrieben).
  Änderungen deshalb per YAML laden → ändern → speichern, **nie** Schlüssel anhängen
  (doppelte Schlüssel: der spätere, oft leere, gewinnt still).
- Nach jeder Änderung: `ap op solve` **und** `ap op check`. Ergebnis selbst lesen - der Check
  findet nicht alles (Plausibilität: Wer schickt nachts? Stimmt die Off-Reihenfolge?).

## 7. Ergebnis präsentieren
- Tabelle nach Abschickzeit: Zeit, Spieler, Dorf, Was, Ankunft.
- Darunter kurz: wie die Sekunde(n) aufgebaut sind, Nachtabschicks, offene Annahmen,
  Alternativen in einem Satz. Dann die vier Befehle zum Anlegen (ziele → approved → spieler →
  discord). Nur Ansehen-Links teilen.

## Werkzeuge für Bewertung und Umplanung
- **Reicht der Train?** `uv run ap op sim <pfad> --ziel x|y --wall <stufe> [--wall-ags 0]`: wie
  viele Deff-Pakete den Train blocken (mit Moral, Nachtbonus, Glück). Mit `--vorhanden
  "spear=…,sword=…"` (bekannte Deff aus Berichten) Welle für Welle. Ist eine Näherung - bei
  knappen Ergebnissen im Spiel-Simulator gegenprüfen.
- **Tab-Offs** zwischen den AGs: `tab_offs: N` am Ziel (siehe `docs/operation.md`).
- **Wer adelt**: `nobles_from: [Spieler oder x|y]`.
- **Retimes / Folge-Operation:** `rueckkehr.md` im Op-Ordner (wer ist wann zurück) bzw.
  `uv run ap op rueckkehr` für alle freigegebenen Operationen. `ap op check` warnt, wenn ein
  Dorf zur Abschickzeit noch in einer anderen Operation unterwegs ist.
