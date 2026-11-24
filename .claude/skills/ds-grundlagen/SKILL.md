---
name: ds-grundlagen
description: Spielwissen Die Stämme / Tribal Wars für die Angriffsplanung - Laufzeiten, Reihenfolge ohne Millisekunden, AG-Regeln, Fakes und Fake-Limit, Flexdeff, Readel, Nachtbonus, Fakeschutz. Laden, bevor du Angriffe planst, Pläne bewertest oder Spielfragen beantwortest.
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
  **Eine brauchbare Off braucht Axt UND LKav UND Rammen.** Nur die Plätze zählen reicht nicht:
  Ohne Axt fehlt die Kampfkraft gegen Deff, ohne Rammen bleibt der Wall stehen. Eine reine
  LKav-Off oder eine Off ohne Rammen ist keine volle Off. Ausnahme: Offs, die **kurz vor den AGs
  tabben** (Wall ist durch die Offs davor schon unten) - die brauchen keine Rammen.
- **AG-Zug / Train**: mehrere AGs hintereinander auf ein Ziel. Sie dürfen aus verschiedenen
  Dörfern und von verschiedenen Spielern kommen. Jeder AG braucht etwas Begleitschutz.
- **Fake**: kleiner Angriff, um den Gegner zu täuschen. **Fake-Limit**: Ein Angriff braucht
  mindestens `fake_limit` % der Punkte des *angreifenden* Dorfs an Bauernhofplätzen
  (z.B. 1 % von 5.000 Punkten = 50 Plätze: 1 Ramme + 45 Speer).
- **Fake-AG**: Angriff mit AG-Laufzeit als Täuschung - verbraucht einen **echten** AG und braucht wie
  ein echtes AG eine Off davor (sonst stirbt das AG).
- **Flexdeff / Unterstützung nach dem Adeln**: Deff, die *nach dem letzten AG* landet. Regel:
  möglichst **in derselben Sekunde wie die AGs**, aber nach dem letzten AG abgeschickt (mit dem
  Off-Abstand). Nur wenn ein Dorf das nicht schafft, landet es 1 s später (Sekunde brechen).
  Landet sie *vor* dem letzten AG, verteidigt sie das Dorf des Gegners!
- **Readel**: Der Gegner adelt sein Dorf zurück. Schnellste Reaktion = Laufzeit seines nächsten
  Dorfs mit AG; vorgetimte AGs können schon eine Sekunde nach eurem letzten AG landen. Eigene
  Konter-Readel-Reserve = freie AGs in Reichweite (`ap op check`).

## Weitere Regeln
- **Nachtbonus** (z.B. 23-8 Uhr): Die Deff zählt doppelt - echte Angriffe dort vermeiden.
- **Moral**: Greift ein großer Spieler einen kleinen an, kämpft er schwächer:
  `3 × Verteidiger-Punkte / Angreifer-Punkte + 0,3`, zwischen 30 % und 100 % (Barbaren: 100 %).
  Der Solver rechnet Offs damit ab (große Spieler eher auf große Ziele), `ap op check` zeigt
  jede Off unter 100 %. Wird mit wachsenden Punkteabständen wichtiger.
- **Punkteverhältnis-Schutz** (de260: 10:1 in den ersten 60 Tagen): Spieler können sich nicht
  angreifen, wenn einer mehr als 10× so viele Punkte hat (beide Richtungen, auch Fakes;
  Unterstützung geht). Solver plant so etwas nie, der Check meldet es als Fehler. Gilt pro
  Account `ratio_days` ab Beitritt: Profil `player_joined` > erste Sync, in der der Spieler
  auftaucht > `world_start` im Profil (ohne alles: gilt immer).
- **Fakeschutz**: Ein paar Einheiten (z.B. 50 Speer, 50 Schwert, 51 Späher) bleiben immer daheim,
  damit Dörfer nicht leer stehen und Späher abgewehrt werden.
- **Veraltete Truppendaten**: vor dem Losschicken neu importieren (Standard: älter als 24 h = Warnung).

## Arbeitsweise im Tool
`ap info` (Welt) → `ap troops import` → `/neue-operation` → `ap op solve` → `ap op check` →
DS-Ultimate-Pläne (`ap op dsu`) → `/discord-nachricht`. Vorgaben des Spielers stehen in
`data/<welt>/profil.yaml` (`ap profil`) - **immer lesen und respektieren**, auch `preferences`.
Daten nie von Hand ändern: Wünsche ins `operation.yaml` schreiben und neu rechnen.
