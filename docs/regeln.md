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
| DS-Ultimate-Pläne über deine Links | Bestehende Angriffe lesen, Kontrolle nach dem Import | bei `solve` / `check` / `dsu` |
| DS Ultimate: Plan anlegen, Titel, Import, Leeren | Eigene Pläne der Operation (nach Rückfrage) | bei `dsu` |

Alles liegt lokal in `data/` (SQLite + Rohdateien) und ist von Git ausgeschlossen.

## DS Ultimate
- `ap op dsu` legt die Pläne selbst an (kein API-Key nötig) und prüft sie. Nach einer
  Neuberechnung befüllt `--aktualisieren` dieselben Pläne neu, die Links bleiben gleich.
  `--manuell` ist der alte Weg von Hand.
- Geteilt werden nur **Ansehen-Links** (`/show/`). Mit einem Bearbeiten-Link (`/edit/`) kann
  jeder den Plan ändern oder löschen.

## Planungsregeln, die der Planer immer einhält
- Ein **AG landet nie ohne Off davor**. Ohne ms gilt: gleiche Sekunde = Abschick-Reihenfolge.
- **Flexdeff landet nie vor dem letzten AG**, sonst würde sie den Gegner verteidigen. Sie landet
  möglichst in derselben Sekunde wie die AGs (nach dem letzten AG abgeschickt); nur wenn ein Dorf
  das nicht schafft, 1 s später.
- **Fakeschutz** und **Fake-Limit** werden eingehalten.
- AGs nur innerhalb der **AG-Reichweite** der Welt.
- **Punkteverhältnis-Schutz** (z.B. 10:1 in den ersten 60 Tagen eines Accounts): Angriffe, die
  das Spiel sperren würde, werden nie geplant; `ap op check` meldet sie als Fehler. Gezählt wird
  **pro Account** ab Beitritt. Das Spiel veröffentlicht den Beitritt nicht, daher:
  1. von Hand im Profil: `player_joined: {Name: 2026-11-01}`
  2. sonst der Tag, an dem der Spieler zum ersten Mal in `ap sync` auftaucht (nur für Spieler,
     die nach unserer ersten Sync dazukamen)
  3. sonst der Weltstart `world_start: 2026-10-01` im Profil - fehlt er, gilt der Schutz als aktiv.
- **Moral**: Offs großer Spieler auf kleine Ziele zählen schwächer (30-100 %). Der Planer
  bevorzugt Offs mit voller Moral, `ap op check` zeigt jede Off unter 100 %.
- Mehr dazu im Skill `.claude/skills/ds-grundlagen/SKILL.md`.
