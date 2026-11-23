---
name: einrichtung
description: Geführte Einrichtung des Angriffsplaners für Nicht-Programmierer - Welt und Stamm, Vorgaben, Truppen einlesen, DS Ultimate (optional API-Key), Discord-Bot mit privaten Threads, Google Docs, welche Connectoren nötig sind. Laden, wenn jemand den Planer einrichten will oder fragt, was noch fehlt.
---

# /einrichtung

Der Spieler ist meist kein Programmierer. Immer nur **einen** Schritt, in einfachen Worten, mit
Klick-Anleitung. Nie eine Konsole, Dateipfade oder Konfigurationsdateien verlangen.

Ruf zuerst `setup_check` auf und geh die offenen Punkte der Reihe nach durch:

1. **Welt und Stamm** (`setup_world`: Welt z.B. de260, eigener Stamm-Tag, Wing-Tags), dann die
   Vorgaben (Skill `profil-einrichten`).
2. **Truppen:** `troops_collect_start` starten, dann dem Spieler sagen: im Spiel eine
   Truppen-Seite nach der anderen öffnen (eigene Übersicht bzw. Stamm → Mitglieder →
   Truppen), jeweils Strg+A, Strg+C, **ohne auf dich zu warten**, am Ende „fertig“ schreiben.
   Dann `troops_collect_stop` und sagen, wer noch fehlt.
3. **DS Ultimate:** funktioniert ohne Einrichtung. Optional ein eigener API-Key von den
   DS-Ultimate-Admins: Er gehört in die Einstellungen des AP-Planners (Claude Desktop:
   Einstellungen → Erweiterungen bzw. Plugins → AP-Planner), **nie in den Chat**. Bringt
   Live-Stand, wer abgehakt hat (`dsu_progress`), und Erinnerungen (`discord_remind`).
4. **Discord-Bot** (optional, erst fragen, ob er ihn will): Token-Schritte aus `setup_check`
   (Token ebenfalls nur in die Einstellungen), Einladungslink aus `setup_check`, dann
   `discord_setup` (Server und Kanäle per Name auswählen lassen; für die Befehle an die Spieler
   einen Kanal für **private Threads** empfehlen, z.B. `#befehle`, und der SF-Rolle dort
   „Threads verwalten“ geben), dann `discord_members` und `discord_assign` (Vorschläge zeigen,
   der Spieler bestätigt).
5. **Google Docs** (optional): Google-Drive-Connector in Claude verbinden, oder ohne Connector
   den Browser-Weg (`operation_doc` mit `open_in_browser`).
6. **Claude:** Bei der ersten Tool-Frage „Immer erlauben“ wählen.

Am Ende `setup_check` nochmal aufrufen und kurz zusammenfassen, was fertig ist und was der
nächste Schritt ist (meist: erste Operation mit dem Skill `neue-operation`).
