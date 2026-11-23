# AP-Planner in Claude Desktop

Mit dieser Anleitung planst du Angriffe direkt im Chat mit Claude. Du brauchst **keine
Programmierkenntnisse** und musst nichts in eine Konsole tippen.

## 1. Einmalig installieren (ca. 5 Minuten)

1. **Claude Desktop** installieren: [claude.com/download](https://claude.com/download)
   (Windows oder Mac) und mit deinem Claude-Konto anmelden.
2. Die Datei **`ap-planner.mcpb`** herunterladen: auf der
   [Release-Seite](https://github.com/Datata1/ds-tool/releases/latest) unter „Assets“.
   (Oder vom Stammesleiter schicken lassen.)
3. Die Datei **doppelt anklicken**. Claude Desktop öffnet sich und fragt, ob du die
   Erweiterung installieren willst → **Installieren**.
   - Klappt der Doppelklick nicht: In Claude Desktop **Einstellungen → Erweiterungen** öffnen
     und die Datei ins Fenster ziehen.
4. Im Einstellungsfenster der Erweiterung:
   - **Datenordner**: einfach so lassen (`ap-planner` in deinem Benutzerordner). Hier speichert
     der Planer deine Weltdaten, Truppen und Operationen. Du musst dort nie etwas selbst ablegen.
   - **Discord-Bot-Token** und **DS-Ultimate-API-Key**: leer lassen. Beides ist optional
     (siehe unten) und kann jederzeit nachgetragen werden.
5. Die Erweiterung **einschalten** (Schalter auf „An“).

Beim ersten Start lädt Claude Desktop im Hintergrund alles Nötige. Das kann 1-2 Minuten
dauern. Danach geht es sofort.

### Variante: als Plugin (z.B. Claude Desktop auf Linux)

Gibt es bei dir keine „Erweiterungen“, sondern nur **„Upload a plugin“ / „Plugin hochladen“**,
nimm stattdessen **`ap-planner-plugin.zip`** (gleiche Release-Seite):

1. Einmalig **uv** installieren (das Werkzeug, das den Planer startet):
   - Linux/Mac: Terminal öffnen, `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows: PowerShell öffnen,
     `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

   Danach einmal ab- und wieder anmelden (bzw. den Rechner neu starten).
2. Plugin hochladen: Datei `ap-planner-plugin.zip` ins Upload-Fenster ziehen.
3. In den Einstellungen des Plugins dieselben Felder wie oben (Datenordner leer lassen =
   `ap-planner` im Benutzerordner; Token und Key optional).
4. Claude Desktop neu starten, neuen Chat öffnen.

Das Plugin bringt die Abläufe (Einrichtung, neue Operation, …) als **Skills** mit. Claude
nutzt sie von selbst, wenn sie passen.

## 2. Geführte Einrichtung

Neuen Chat öffnen und schreiben:

> Richte den Angriffsplaner mit mir ein.

(Oder im Chatfeld **+** → **ap-planner** → **einrichtung**.) Claude prüft, was fertig ist, und
geht die offenen Punkte einzeln mit dir durch:

| Punkt | Was passiert | Nötig? |
|---|---|---|
| **Welt & Stamm** | Du nennst Welt (z.B. `de260`), Stamm-Tag und Wing-Tags. Claude lädt die öffentlichen Weltdaten. | ja |
| **Vorgaben** | Ein paar Fragen: ab wann eine Off „voll“ ist, Begleitschutz, Fakeschutz, wann du losschicken kannst | ja |
| **Truppen** | Claude startet den **Sammel-Modus**. Du öffnest im Spiel eine Truppen-Seite nach der anderen und drückst jeweils **Strg+A**, **Strg+C**, ohne auf Claude zu warten. Jede Kopie wird sofort im Hintergrund eingelesen. Am Ende „fertig“ schreiben: Claude sagt dir, wer noch fehlt. | ja |
| **DS Ultimate** | Nichts zu tun: kein Konto nötig. Claude legt die Pläne an und gibt dir die Links. Mit API-Key zusätzlich Live-Stand und Erinnerungen (siehe unten). | optional |
| **Discord-Bot** | siehe unten | optional |
| **Google Docs** | siehe unten | optional |

### Welche Connectoren müssen an sein?

| In Claude Desktop | Wofür | Nötig? |
|---|---|---|
| Einstellungen → Erweiterungen → **AP-Planner** | alles | **ja** |
| Einstellungen → Connectors → **Google Drive** | Spieler-Dokument als Google Doc anlegen und aktualisieren | optional |
| Websuche, andere Connectoren | werden nicht gebraucht | nein |

Wenn Claude zum ersten Mal ein Tool benutzen will, fragt Desktop nach. Wähle **„Immer
erlauben“**, dann kommt die Frage nicht bei jedem Schritt.

### Discord-Bot (optional)

Der Bot postet das SF-Review und die Ankündigung und schickt jedem Spieler **seine** Befehle:
am besten in einen **privaten Thread** pro Spieler in einem Kanal wie `#befehle` (klappt auch,
wenn jemand Direktnachrichten gesperrt hat, und eure SF-Rolle mit „Threads verwalten“ sieht alle
Threads), sonst per Direktnachricht. Er läuft **nicht dauerhaft** auf einem Server. Er sendet nur, wenn du es im Chat
auslöst, und Claude zeigt vorher, wer was bekommt. Ohne Bot schreibt Claude dir die Texte zum
Kopieren.

1. [discord.com/developers/applications](https://discord.com/developers/applications) →
   **New Application** → Name z.B. „AP-Planer“.
2. Links **Bot** → **Reset Token** → Token kopieren. Darunter **Server Members Intent**
   einschalten → Speichern.
3. Claude Desktop: **Einstellungen → Erweiterungen → AP-Planner** → Token bei
   „Discord-Bot-Token“ einfügen → Speichern. **Nie in den Chat schreiben.**
4. Neuen Chat: „Richte Discord ein“. Claude gibt dir den **Einladungslink** für den Bot und
   lässt dich danach Server und Kanäle **per Name** auswählen (SF-Review, Ankündigung und
   optional den Kanal für die privaten Threads). IDs kopieren oder Entwicklermodus brauchst du
   nicht. Danach ordnet Claude die Spieler ihren Discord-Namen zu
   (mit Vorschlägen, du bestätigst).

### DS-Ultimate-API-Key (optional)

Ohne Key funktioniert alles. Mit einem persönlichen Key von den DS-Ultimate-Admins:

- Pläne werden über die **offizielle Schnittstelle** angelegt (schneller, bricht nicht, wenn
  DS Ultimate seine Seite umbaut).
- **Live-Stand während der Operation:** „Wer hat schon abgeschickt?“ Claude zeigt pro Spieler,
  was in DS Ultimate als verschickt **abgehakt** ist und was überfällig ist. Das klappt nur,
  wenn die Spieler in ihrem Plan abhaken.
- **Erinnerungen:** „Erinner alle, die in den nächsten 15 Minuten schicken müssen.“ Claude
  zeigt, wen es trifft, und schickt nach deinem OK eine kurze Nachricht in den Thread bzw. per
  DM (braucht den Discord-Bot).

Eintragen: **Einstellungen → Erweiterungen → AP-Planner → DS-Ultimate-API-Key**. Der Key ist
persönlich: nie in den Chat schreiben, nie weitergeben.

### Google Docs (optional)

- **Mit Connector:** Google Drive in Claude Desktop verbinden (siehe oben). Claude legt das Doc
  an und aktualisiert später dasselbe Doc (der Link bleibt gleich).
- **Ohne Connector:** Claude öffnet das fertige Dokument im Browser. Dort **Strg+A**,
  **Strg+C**, dann [docs.new](https://docs.new) öffnen und **Strg+V**. Tabellen und Farben
  bleiben erhalten. Den Link des Docs Claude nennen, damit er ihn sich merkt.

## 3. Planen

> 2 Offs und 4 AGs auf 480|529 um 8:15, Fakes auf die Dörfer drumherum.

Claude rechnet, prüft (nie ein AG ohne Off davor, keine doppelt verplanten Truppen) und erklärt
Probleme. Danach legt Claude auf Wunsch die DS-Ultimate-Pläne an und schreibt die
Discord-Nachrichten. Bevor etwas nach außen geht (DS Ultimate, Discord), zeigt Claude dir
immer zuerst, was passiert, und wartet auf dein OK.

Über das **+** im Chatfeld → **ap-planner** findest du fertige Abläufe, z.B. `start`,
`neue-operation` oder `profil-einrichten`. Du kannst aber auch einfach normal schreiben.

## Kein Botting

Der Planer klickt nichts im Spiel und meldet sich nirgends mit deinem Konto an. Er nutzt nur
öffentliche Weltdaten, die Truppen, die du selbst einfügst, und DS-Ultimate-Links.
Abschicken musst du im Spiel immer selbst.

## Häufige Fragen

**Claude kennt die Tools nicht / sagt, es habe keinen Zugriff.**
Einstellungen → Erweiterungen → ap-planner muss **an** sein. Danach einen **neuen** Chat
öffnen.

**„Fehler beim Starten“ direkt nach der Installation.**
Claude Desktop einmal ganz beenden (auch im Infobereich/Menüleiste) und neu öffnen. Beim
ersten Start braucht der Download etwas Zeit.

**Wo sind meine Daten?** Im Datenordner (Standard: `ap-planner` im Benutzerordner, unter
Windows `C:\Users\<Name>\ap-planner`). Bei einem Update
der Erweiterung bleiben sie erhalten. Willst du sie mitnehmen, kopiere einfach den Ordner.

**Update installieren:** Neue `ap-planner.mcpb` herunterladen und wieder doppelt anklicken.

**Windows, Mac oder Linux?** Alle drei gehen. Ausnahme: Windows auf ARM-Prozessoren (z.B.
Surface/Snapdragon-Laptops). Dafür gibt es den Rechenkern (Google OR-Tools) nicht.

**„Zwischenablage nicht lesbar“.** Dann den kopierten Text einfach in den Chat einfügen. Bei
sehr langen Listen lieber pro Spieler einzeln, Claude liest sie dann ebenfalls ein.

**Ich nutze schon Claude Code im Projektordner.** Dann wähle als Datenordner den
Projektordner (der mit `data/` und `.env`). Dann sehen beide dieselben Daten.

## Für Entwickler: Erweiterung bauen

```bash
uv run python scripts/build_mcpb.py     # → dist/ap-planner.mcpb
```

Die Erweiterung nutzt den Server-Typ `uv`: Claude Desktop installiert Python und die
Abhängigkeiten selbst (`uv run --frozen --no-dev ap-planner-mcp`). Der Datenordner kommt über
`AP_HOME`. Ohne `AP_HOME` nutzt der Server den aktuellen Ordner, wenn dort `.env` oder `data/`
liegt, sonst `~/ap-planner`. Bei einem Git-Tag `v*` baut die CI die Datei und hängt sie an das
Release an.

Von Hand (ohne Erweiterung) in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ap-planner": {
      "command": "uv",
      "args": ["run", "--directory", "/pfad/zu/ap-planner", "--quiet", "ap-planner-mcp"],
      "env": { "AP_HOME": "/pfad/zu/ap-planner" }
    }
  }
}
```
