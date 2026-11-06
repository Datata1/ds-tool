---
name: discord-nachricht
description: Erstellt die Discord-Nachricht zu einer fertig geplanten Operation - entweder für das SF-Review (welcher DS-Ultimate-Plan welches Ziel/welchen Spieler fokussiert) oder die Ankündigung an die Spieler mit ihren Plan-Links.
---

# /discord-nachricht

Erzeuge die Discord-Nachricht für eine Operation. Der Nutzer spricht Deutsch und möchte einfache
Erklärungen.

1. Operation finden: `ls data/*/ops/*/operation.yaml`. Gibt es mehrere, frag nach welcher (die
   neueste zuerst vorschlagen).
2. Art klären (AskUserQuestion, falls nicht genannt):
   - **review**: für die SF, ein Block pro Zieldorf mit Ziel, Besitzer, Ankunft, wer was schickt
     (Main/Wing) und Ansehen-Link. Voraussetzung: Ziel-Pläne angelegt (`ap op dsu … --fuer ziele`).
   - **spieler**: Ankündigung nach der Freigabe, pro Spieler Anzahl Befehle, erster Abschick und
     Plan-Link. Voraussetzung: Spieler-Pläne angelegt (`ap op dsu … --fuer spieler`).
3. Erzeugen: `uv run ap op discord <pfad>/operation.yaml --art <review|spieler> --kopieren`.
   Die Nachricht liegt dann auch in der Zwischenablage und in `<pfad>/discord_<art>.md`.
4. Prüfen, bevor du sie zeigst:
   - Fehlende Links stehen als „(Link folgt)“ drin. Sag, welche fehlen und wie man sie bekommt.
   - Ist `plan.json` älter als `operation.yaml`? Dann zuerst `uv run ap op solve` vorschlagen.
5. Gib die Nachricht in einem Codeblock aus, damit sie 1:1 kopiert werden kann. Davor eine Zeile
   „Geschrieben für: …“. Discord-Limit: 2000 Zeichen pro Nachricht. Ist sie länger, teile sie
   sinnvoll auf (z.B. echte Angriffe / Fakes).
6. Wünscht der Nutzer andere Formulierungen, passe nur den Text an. Daten (Zeiten, Links, Spieler)
   nie von Hand ändern - dafür neu rechnen.

Nie Bearbeiten-Links (`/edit/`) in die Nachricht schreiben, nur Ansehen-Links (`/show/`).
