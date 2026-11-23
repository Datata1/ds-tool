---
name: profil-einrichten
description: Stamm-Profil eines Spielers einrichten oder ändern - Welt, eigener Stamm, Wing, volle Off, Begleitschutz, Fakeschutz, Losschick-Zeiten und persönliche Strategie-Vorlieben, die alle Planungen übernehmen.
---

# /profil-einrichten

Das Profil enthält die Vorgaben eines Spielers. Jede neue Operation übernimmt sie, und
`ap op check` meldet Abweichungen. Der Spieler spricht meist Deutsch. Erkläre einfach.

1. Gibt es schon eine Welt? `cat .env`. Fehlt `AP_WORLD`: `uv run ap init` ausführen lassen
   (interaktiv: Welt, Stamm-Tag, Wing-Tags) - das lädt auch die Weltdaten.
2. Bestehendes Profil lesen: `uv run ap profil`. Nur fragen, was fehlt oder geändert werden soll.
3. Fragen (AskUserQuestion mit sinnvollen Vorschlägen, Empfehlung zuerst):
   - **Eigener Stamm** (`own_tribes`) und **Verbündete/Wing** (`allied_tribes`). Mit
     `uv run ap villages --ally <TAG>` bzw. der Ausgabe von `ap init` bestätigen.
   - **Volle Off ab wie vielen Off-Plätzen** (`off_min_pop`)? Zeige die stärksten importierten
     Offs (`uv run ap troops show`) als Orientierung. Early Game eher 5.000-8.000.
   - **Fusionsoff-Teil ab** (`fusion_min_pop`, z.B. 1.000).
   - **Begleitschutz pro AG** (`noble_escort`, z.B. 100 Axt).
   - **Fakeschutz** (`home_guard`, z.B. 50 Speer, 50 Schwert, 51 Späher).
   - **Losschicken wann** (`send_window`)? Ganztags = kürzeste Laufzeiten, sonst längere.
   - **Reihenfolge**: Sicherheitsabstand Off vor AG in Sekunden (`off_send_gap_s`, Standard 2) und
     ob Sekunden gebrochen werden dürfen (`allow_second_break`).
   - **Persönliche Vorlieben** als Freitext (`preferences`), z.B. „Fakes nie aus Dörfern mit
     eingehenden Angriffen“, „SF-Review über Discord“, „Flexdeff immer bei echten Adelungen“.
4. Schreiben: `data/<welt>/profil.yaml` (Schema: `src/ap_planner/models/profile.py`, unbekannte
   Felder sind verboten). Einheiten-Namen: spear, sword, axe, spy, light, heavy, ram, catapult,
   snob. Danach `uv run ap profil` zur Kontrolle zeigen.
5. Hinweis geben: Bestehende Operationen behalten ihre Werte. Nur neue Operationen übernehmen das
   geänderte Profil.

Das Profil liegt unter `data/` und kommt **nicht** ins Git-Repo - es ist persönlich.
