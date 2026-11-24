# ap-planner

**KI-gestützter Angriffsplaner für Die Stämme / Tribal Wars**, mit Export nach
[DS Ultimate](https://ds-ultimate.de).

*AI-assisted attack planner for Tribal Wars (German servers first). You describe the strategy,
an agent turns it into a validated plan and DS-Ultimate attack plans.*

Du beschreibst deine Strategie im Chat, z.B. „2 Offs und 4 AGs auf 480|529 um 8:15, Fakes auf die
umliegenden Dörfer, Flexdeff nach dem letzten AG“. Der Planungs-Agent macht daraus:

- eine **berechnete Planung**: welches Dorf wann was schickt, mit Laufzeiten auf die Sekunde und
  Truppenbudgets pro Dorf
- einen **automatischen Review**: keine doppelt verplanten Truppen oder AGs, nie ein AG ohne Off
  davor, freie Truppen, veraltete Daten
- **DS-Ultimate-Pläne** pro Zieldorf (für die Stammesführung) und pro Spieler
- fertige **Discord-Nachrichten** für Review und Ankündigung

> **Kein Botting.** Das Tool führt keine Spielaktionen aus und ruft keine Spielseiten mit deinem
> Login ab. Es nutzt nur öffentliche Weltdaten, Truppen-Übersichten, die du selbst kopierst, und
> DS-Ultimate-Pläne über Links, die du angibst. Details: [docs/regeln.md](docs/regeln.md)

## Installieren (kostenlos, ohne KI)

Die **Desktop-App** kann alles per Formular: Truppen einlesen, Operation anlegen, rechnen,
prüfen, DS-Ultimate-Pläne, Google Doc, Discord. Download auf der
[Release-Seite](https://github.com/Datata1/ds-tool/releases/latest), Schritt für Schritt:

- [Windows](docs/installation/windows.md)
- [macOS (Apple-Chip)](docs/installation/macos.md)
- [Linux](docs/installation/linux.md)

**Truppen-Skript** für die Schnellleiste im Spiel (liest die Truppen des ganzen Stamms mit
einem Klick): [truppen-schnellleiste.txt](https://github.com/Datata1/ds-tool/releases/latest/download/truppen-schnellleiste.txt)
öffnen, Zeile kopieren, im Spiel als Schnellleisten-Link einfügen ([mehr](docs/truppen-skript.md)).

Version veröffentlichen (Maintainer): [docs/release.md](docs/release.md).

## Schnellstart mit Claude Desktop (ohne Programmierkenntnisse)

1. [Claude Desktop](https://claude.com/download) installieren.
2. **`ap-planner.mcpb`** von der [Release-Seite](https://github.com/Datata1/ds-tool/releases/latest)
   herunterladen und **doppelt anklicken** → Installieren → Schalter auf „An“.
   (Nur Plugin-Upload, z.B. auf Linux? Dann `ap-planner-plugin.zip`, siehe Anleitung.)
3. Neuen Chat öffnen: **„Richte den Angriffsplaner mit mir ein.“** Claude führt dich durch Welt,
   Vorgaben, Truppen (im Spiel nur Strg+A, Strg+C), optional Discord-Bot und Google Docs.
   Danach einfach die Idee beschreiben: „2 Offs und 4 AGs auf 480|529 um 8:15“.

Ausführliche Anleitung mit häufigen Fragen: [docs/claude-desktop.md](docs/claude-desktop.md).

## Schnellstart mit Claude Code (für Fortgeschrittene)

Voraussetzungen: [uv](https://docs.astral.sh/uv/) und
[Claude Code](https://claude.com/claude-code). Alternativ geht jeder MCP-fähige Client.

```bash
git clone https://github.com/Datata1/ds-tool.git ap-planner && cd ap-planner
uv sync
uv run ap init                      # Welt, Stamm, Wing → lädt Weltdaten, legt dein Profil an
```

1. **Truppen einlesen:** Im Spiel *Übersichten → Truppen* (oder die Stammes-Ansicht pro
   Mitglied) markieren und kopieren. Alles untereinander in `stamm.txt` einfügen, dann:
   ```bash
   uv run ap troops import stamm.txt
   ```
2. **Claude Code im Projektordner starten** und tippen:
   - `/profil-einrichten`: deine Vorgaben (volle Off, Fakeschutz, Zeitfenster, Vorlieben)
   - `/neue-operation`: geführter Fragebogen → Plan → Review → DS-Ultimate-Pläne
   - `/discord-nachricht`: Review- oder Ankündigungs-Nachricht

Der ganze Ablauf mit allen Schritten: [docs/ablauf.md](docs/ablauf.md).

## Was das Tool kann

| | |
|---|---|
| Weltdaten | Laufzeiten, Nachtbonus, ms-Einstellung, AG-Reichweite, Fake-Limit (öffentlich, max. 1×/h) |
| Truppen | Copy-&-Paste der eigenen Übersicht und der Stammes-Ansicht pro Mitglied |
| Planung | Offs, AG-Züge aus mehreren Dörfern, Fakes, Fake-AGs, Flexdeff, Pflicht-Offs |
| Regeln | Gleiche Sekunde = Abschick-Reihenfolge: Offs vor AGs, sonst Sekunde brechen; Fakeschutz |
| Wing/Verbündete | Bestehende DS-Ultimate-Pläne lesen und einbinden (`merge`/`split`/`keep`/`copy`), Angriffe umleiten |
| Review | Doppelte Zuweisung, Reihenfolge, Zeiten, freie Truppen, Readel-Gefahr, Abgleich mit DS Ultimate |
| Export | Workbench-Texte pro Ziel und Spieler, geführtes Anlegen in DS Ultimate, Discord-Nachrichten |

## Dokumentation

- [Claude Desktop: Installation & Einstieg](docs/claude-desktop.md)
- [Ablauf einer Operation](docs/ablauf.md)
- [Befehle (CLI)](docs/befehle.md)
- [operation.yaml](docs/operation.md) und [Profil](docs/profil.md)
- [Regeln & Datenquellen](docs/regeln.md)
- [Entwicklung & Architektur](docs/entwicklung.md)

## Agenten-Wissen (Skills)

| Skill | Zweck |
|---|---|
| `ds-grundlagen` | Spielwissen: Laufzeiten, Reihenfolge ohne ms, Fakes, Flexdeff, Readel |
| `ds-ultimate` | Pläne anlegen, Links, Titel, Wing-Pläne einbinden |
| `profil-einrichten` | Persönliche Vorgaben und Strategie-Vorlieben festlegen |
| `neue-operation` | Geführte Planung von der Idee bis zur Freigabe |
| `train-planung` | Praxis: Offs vor AGs, Sekunden brechen, Flexdeff im NB, Fake-Auswahl, Umplanen |
| `discord-nachricht` | Review- und Ankündigungs-Nachrichten |

In Claude Code liegen sie unter `.claude/skills/`. Claude Desktop und andere Clients bekommen sie
über den MCP-Server als Prompts (im Chat: **+** → ap-planner). Jeden CLI-Schritt gibt es dort
auch als Tool, eine Konsole ist nicht nötig.

## Lizenz

[MIT](LICENSE). Kein offizielles Produkt von InnoGames oder DS Ultimate.
