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
     (Main/Wing) und Ansehen-Link, oben der Link zum Google Doc (nur ansehen, jeder mit Link).
     Voraussetzung: Ziel-Pläne angelegt (`ap op dsu … --fuer ziele`) und das Google Doc ist
     aktuell und freigegeben (`/google-doc`) - sonst erst das Doc anlegen bzw. neu befüllen.
   - **spieler**: öffentliche Ankündigung beim finalen Plan (Status `approved`), im Kanal mit
     den privaten Threads (sonst `ankuendigung`). Erwähnt die Discord-Rollen von Stamm + Wing
     (Rolle heißt wie der Stammes-Tag, z.B. @RAK, @RAKK - wird vom Server gelesen, nie fest
     eingetragen). Grunddaten: Abschick- und Lande-Zeitraum, Gegner-Stamm, Aufruf zu
     zusätzlichen Fakes, Regeln. Accounts mit Befehlen ohne Discord-Zuordnung werden genannt
     und gebeten, sich bei der SF zu melden. Sonst nie Ziele, Spieler, Links oder was echt
     bzw. Fake ist. Die Befehle selbst gehen privat raus (`--art thread` bzw. `dm`, Voraussetzung:
     Spieler-Pläne angelegt, `ap op dsu … --fuer spieler`).
3. Erzeugen: `uv run ap op discord <pfad>/operation.yaml --art <review|spieler> --kopieren`.
   Die Nachricht liegt dann auch in der Zwischenablage und in `<pfad>/discord_<art>.md`.
4. Prüfen, bevor du sie zeigst:
   - Fehlende Links stehen als „(Link folgt)“ drin. Sag, welche fehlen und wie man sie bekommt.
   - Ist `plan.json` älter als `operation.yaml`? Dann zuerst `uv run ap op solve` vorschlagen.
5. Gib die Nachricht in einem Codeblock aus, damit sie 1:1 kopiert werden kann. Davor eine Zeile
   „Geschrieben für: …“. Discord-Limit: 2000 Zeichen pro Nachricht. Ist sie länger, teile sie
   sinnvoll auf (z.B. echte Angriffe / Fakes).
6. **Per Bot senden** (wenn `data/<welt>/discord.yaml` und der Token eingerichtet sind, siehe
   `docs/discord.md`): `uv run ap op discord <pfad> --art review|spieler|thread|dm --senden`.
   `thread` (empfohlen, wenn der Kanal `befehle` eingerichtet ist) schreibt jedem Spieler seine
   eigenen Befehle in seinen **privaten Thread** (wird beim ersten Mal angelegt und für alle
   weiteren Operationen wiederverwendet), `dm` als Direktnachricht. Senden ist nach außen sichtbar: nur nach
   ausdrücklichem OK des Nutzers, `--ja` nur dann. Der Befehl im Terminal des Nutzers fragt
   sonst selbst nach. Erneutes Senden bearbeitet die alten Nachrichten (keine Doppel-Posts).
7. Wünscht der Nutzer andere Formulierungen, passe nur den Text an. Daten (Zeiten, Links, Spieler)
   nie von Hand ändern - dafür neu rechnen.

Nie Bearbeiten-Links (`/edit/`) in die Nachricht schreiben, nur Ansehen-Links (`/show/`).
