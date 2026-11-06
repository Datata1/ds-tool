---
name: ds-grundlagen
description: Spielwissen Die Stämme / Tribal Wars für die Angriffsplanung - Laufzeiten, Reihenfolge ohne Millisekunden, AG-Regeln, Fakes und Fake-Limit, Fusionsoffs, Flexdeff, Readel, Nachtbonus, Fakeschutz. Laden, bevor du Angriffe planst, Pläne bewertest oder Spielfragen beantwortest.
---

# Die Stämme - was ein Planungs-Agent wissen muss

## Grundsatz: kein Botting
Dieses Tool automatisiert **nie** Spielaktionen und ruft **nie** Spielseiten mit dem Login eines
Spielers ab. Erlaubt: öffentliche Weltdaten (`interface.php`, `/map/*.txt.gz`, höchstens 1x pro
Stunde), Daten, die der Spieler selbst kopiert (Truppen-Übersichten), und DS-Ultimate-Pläne über
Links, die der Spieler angibt. Wer Truppen von allen Stammesmitgliedern will, nimmt ein vom Spiel
**freigegebenes** Skript und fügt dessen Ausgabe ein - nie selbst Seiten abrufen.

## Laufzeiten
- Laufzeit = Entfernung (Felder, Pythagoras) × Minuten pro Feld der **langsamsten** Einheit,
  auf ganze Sekunden gerundet. `get_unit_info` liefert die Minuten schon mit Welt- und
  Einheitengeschwindigkeit verrechnet (`uv run ap info`).
- Abschickzeit = Ankunft − Laufzeit. Rammen und Katas bestimmen meist das Tempo einer Off,
  der AG ist die langsamste Einheit (z.B. 35 min/Feld).
- AGs haben eine **maximale Reichweite** (`snob_max_dist`, z.B. 40 Felder).

## Reihenfolge ohne Millisekunden (sehr wichtig)
Auf Welten mit `millis_arrival = 0` gilt: Befehle, die **in derselben Sekunde** landen, kommen in
der **Reihenfolge an, in der sie abgeschickt wurden**. Daraus folgt die harte Regel:

> **Ein AG landet nie ohne eine Off davor.** Entweder wird jede Off mindestens ein paar Sekunden
> (`off_send_gap_s`) *vor* jedem AG derselben Sekunde abgeschickt - oder die Offs landen eine
> Sekunde früher („Sekunde brechen“). Gleiche Sekunde wird meist bevorzugt.

Typische Falle: Off und AG aus demselben Dorf. Der AG ist langsamer und muss deshalb *früher*
abgeschickt werden - in derselben Sekunde landet er dann vor der Off. Lösung: Off aus einem
anderen Dorf oder Sekunde brechen. Eine Wing-Off zählt auch, wenn sie früher abgeschickt wird.

## Angriffsarten
- **Off**: volle Offensive. Stärke in Off-Plätzen (Axt 1, LKav 4, BB 5, Ramme 5, Kata 8). Was als
  „volle Off“ gilt, hängt vom Spielstand ab (Early Game z.B. 7.000, später 20.000+) → Profil.
- **Fusionsoff**: mehrere kleinere Offs aus verschiedenen Dörfern landen gleichzeitig und wirken
  wie eine große.
- **AG-Zug / Train**: mehrere AGs hintereinander auf ein Ziel. Sie dürfen aus verschiedenen
  Dörfern und von verschiedenen Spielern kommen. Jeder AG braucht etwas Begleitschutz.
- **Fake**: kleiner Angriff, um den Gegner zu täuschen. **Fake-Limit**: Ein Angriff braucht
  mindestens `fake_limit` % der Punkte des *angreifenden* Dorfs an Bauernhofplätzen
  (z.B. 1 % von 5.000 Punkten = 50 Plätze: 1 Ramme + 45 Speer).
- **Fake-AG**: Angriff mit AG-Laufzeit als Täuschung - verbraucht einen **echten** AG.
- **Flexdeff / Unterstützung nach dem Adeln**: Deff, die *nach dem letzten AG* landet (gleiche
  Sekunde später abgeschickt oder eine Sekunde danach). Landet sie *vor* dem letzten AG,
  verteidigt sie das Dorf des Gegners!
- **Readel**: Der Gegner adelt sein Dorf zurück. Schnellste Reaktion = Laufzeit seines nächsten
  Dorfs mit AG; vorgetimte AGs können schon eine Sekunde nach eurem letzten AG landen. Eigene
  Konter-Readel-Reserve = freie AGs in Reichweite (`ap op check`).

## Weitere Regeln
- **Nachtbonus** (z.B. 23-8 Uhr): Die Deff zählt doppelt - echte Angriffe dort vermeiden.
- **Fakeschutz**: Ein paar Einheiten (z.B. 50 Speer, 50 Schwert, 51 Späher) bleiben immer daheim,
  damit Dörfer nicht leer stehen und Späher abgewehrt werden.
- **Veraltete Truppendaten**: vor dem Losschicken neu importieren (Standard: älter als 24 h = Warnung).

## Arbeitsweise im Tool
`ap info` (Welt) → `ap troops import` → `/neue-operation` → `ap op solve` → `ap op check` →
DS-Ultimate-Pläne (`ap op dsu`) → `/discord-nachricht`. Vorgaben des Spielers stehen in
`data/<welt>/profil.yaml` (`ap profil`) - **immer lesen und respektieren**, auch `preferences`.
Daten nie von Hand ändern: Wünsche ins `operation.yaml` schreiben und neu rechnen.
