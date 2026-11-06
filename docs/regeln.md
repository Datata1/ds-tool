# Regeln & Datenquellen

## Kein Botting
Das Tool soll Spielern Zeit beim **Planen** sparen. Es spielt nicht für sie.
- Es führt **keine Spielaktionen** aus und schickt keine Befehle ab.
- Es ruft **keine Spielseiten mit deinem Login** ab. Truppen kommen nur aus Tabellen, die du
  selbst kopierst. Für die Truppen aller Stammesmitglieder nutzt du die Stammes-Ansicht oder ein
  vom Spiel **freigegebenes** Skript und fügst dessen Ausgabe ein.
- Losgeschickt wird von Hand im Spiel, so wie bei jedem anderen Angriffsplan.

## Datenquellen
| Quelle | Was | Wie oft |
|---|---|---|
| `https://<welt>.die-staemme.de/interface.php?func=get_config` / `get_unit_info` | Welt- und Einheiten-Einstellungen | 1x pro Tag (Cache) |
| `https://<welt>.die-staemme.de/map/village.txt.gz`, `player.txt.gz`, `ally.txt.gz` | Karte, Spieler, Stämme | max. 1x pro Stunde (Bitte von InnoGames) |
| Deine kopierten Truppen-Tabellen | Truppen pro Dorf | wenn du importierst |
| DS-Ultimate-Pläne über deine Links | Bestehende Angriffe (nur lesen), Kontrolle nach dem Import | bei `solve` / `check` / `dsu` |

Alles liegt lokal in `data/` (SQLite + Rohdateien) und ist von Git ausgeschlossen.

## DS Ultimate
- Ohne API-Key legst du Pläne von Hand an. `ap op dsu` führt durch und prüft das Ergebnis.
- Geteilt werden nur **Ansehen-Links** (`/show/`). Mit einem Bearbeiten-Link (`/edit/`) kann
  jeder den Plan ändern oder löschen.
- Ein API-Key (`/toolAPI/attackPlanner/*`) wird von den DS-Ultimate-Admins auf ihrem Discord
  vergeben. Damit könnte das Tool Pläne selbst anlegen (noch nicht eingebaut).

## Planungsregeln, die der Planer immer einhält
- Ein **AG landet nie ohne Off davor**. Ohne ms gilt: gleiche Sekunde = Abschick-Reihenfolge.
- **Flexdeff landet nie vor dem letzten AG**, sonst würde sie den Gegner verteidigen.
- **Fakeschutz** und **Fake-Limit** werden eingehalten.
- AGs nur innerhalb der **AG-Reichweite** der Welt.
- Mehr dazu im Skill `.claude/skills/ds-grundlagen/SKILL.md`.
