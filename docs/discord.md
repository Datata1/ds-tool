# Discord-Bot einrichten

Der Bot postet das SF-Review und die Ankündigung in eure Kanäle und schickt jedem Spieler
**seine** Befehle mit Plan-Link: entweder in einen **privaten Thread** (empfohlen) oder per
Direktnachricht.

## Private Threads oder Direktnachrichten?

| | Privater Thread (`--art thread`) | Direktnachricht (`--art dm`) |
|---|---|---|
| Wo | ein Kanal, z.B. `#befehle`, darin pro Spieler ein Thread „Befehle <Name>“ | Privatchat Bot ↔ Spieler |
| Wer sieht es | der Spieler, der Bot und alle mit dem Recht **Threads verwalten** (z.B. SF-Rolle) | nur der Spieler |
| Gesperrte DMs | egal | Spieler bekommt nichts |
| Mehrere Operationen | derselbe Thread wird wiederverwendet | neue Nachrichten im selben Chat |

Der Thread wird beim ersten Senden angelegt, der Spieler hinzugefügt und erwähnt (er sieht den
Thread sofort). Discord archiviert Threads nach 7 Tagen Ruhe; der Bot öffnet sie vor dem
Schreiben wieder. Löscht jemand einen Thread, legt der Bot beim nächsten Senden einen neuen an.
Private Threads gehen auf jedem Server, ohne Boost. Er sendet nur, wenn du es im Tool auslöst, und
zeigt vorher, wer was bekommt. Wird eine Operation neu gerechnet, **bearbeitet** er seine
Nachrichten, statt sie doppelt zu schicken. Weil Discord bei bearbeiteten Nachrichten
nicht benachrichtigt, schreibt er dann im privaten Thread zusätzlich einen kurzen Hinweis, der
die Spieler erwähnt: Plan aktualisiert, offenen DS-Ultimate-Plan bitte neu laden.

## Einmalig: Bot anlegen (ca. 5 Minuten)
1. <https://discord.com/developers/applications> → **New Application** → Name z.B. „RAK Planer“.
2. Links **Bot**:
   - **Reset Token** → Token kopieren. **Claude Desktop:** Einstellungen → Erweiterungen →
     AP-Planner → „Discord-Bot-Token“. **Claude Code/CLI:** in `.env` im Projektordner:
     `AP_DISCORD_BOT_TOKEN=dein-token`. Den Token **nie** teilen oder in den Chat posten.
   - Unter *Privileged Gateway Intents* **Server Members Intent** einschalten (für die
     Zuordnung der Spieler).
3. Links **OAuth2 → URL Generator**: Scope `bot`, Rechte *View Channels*, *Send Messages*,
   *Read Message History*, *Create Private Threads*, *Send Messages in Threads*. (In Claude
   Desktop erzeugt `setup_check` diesen Link automatisch. Wurde der Bot früher ohne die
   Thread-Rechte eingeladen: mit dem neuen Link nochmal einladen.) Den erzeugten Link öffnen und den Bot auf euren Server einladen.
4. In Discord: *Einstellungen → Erweitert → Entwicklermodus* an. Dann Rechtsklick auf den Server
   bzw. Kanal → **ID kopieren**.

## Im Tool
**Claude Desktop:** „Richte Discord ein“ sagen. Claude erzeugt den Einladungslink, und du
wählst Server und Kanäle per Name. Schritte 3 und 4 oben fallen weg.

**Konsole:**
```bash
uv run ap discord einrichten --server <Server-ID> --review <Kanal-ID> --ankuendigung <Kanal-ID>
uv run ap discord spieler        # DS-Namen den Discord-Mitgliedern zuordnen
```
`ap discord spieler` schlägt pro Stammesmitglied den passendsten Discord-Namen vor:
**Enter** = übernehmen, **n** = überspringen, oder die Nummer aus der Liste eingeben.
**Ein Account, mehrere Spieler:** Spielen mehrere Leute einen DS-Account, ordne ihm alle
zu (in `ap discord spieler` Nummern mit Komma, z.B. `3, 17`; in Claude Desktop einfach sagen,
wer dazugehört). Alle kommen in den privaten Thread und werden erwähnt, bei `--art dm`
bekommt jeder eine eigene Direktnachricht.
Alles steht in `data/<welt>/discord.yaml` und kann dort auch von Hand geändert werden.

## Senden
```bash
uv run ap op discord <op>/operation.yaml --art review  --senden   # SF-Review-Kanal
uv run ap op discord <op>/operation.yaml --art spieler --senden   # öffentliche Ankündigung
uv run ap op discord <op>/operation.yaml --art dm      --senden   # jedem Spieler seine Befehle
uv run ap op discord <op>/operation.yaml --art dm --senden --nur "Graf Scheißer"   # zum Testen
```
Ohne `--senden` wird der Text nur angezeigt und in `discord_<art>.md` gespeichert.

**Gut zu wissen**
- Ein Spieler bekommt keine DM, wenn er Direktnachrichten von Server-Mitgliedern gesperrt hat.
  Das Tool meldet das, die anderen bekommen ihre Nachricht trotzdem.
- Gibt es keinen eigenen Spieler-Plan, verlinkt die DM den Plan des Zieldorfs.
- Der Bot erwähnt nie `@everyone` oder `@here`. Rollen nur in der öffentlichen Ankündigung
  (siehe unten).

## Öffentliche Ankündigung beim finalen Plan
Ist die Operation freigegeben (`ap op status … approved`), schickt `--art spieler` eine
öffentliche Nachricht in den Kanal mit den privaten Threads (ohne den in `ankuendigung`):
- erwähnt die Discord-Rollen von **Stamm + Wing**, z.B. `@RAK @RAKK @RAKKK`. Die Rollen werden
  bei jedem Senden vom Server gelesen: Eine Rolle zählt, wenn sie wie ein Stammes-Tag aus dem
  Profil heißt (`own_tribes` + `allied_tribes`; Klammern wie `[RAK]` sind egal). Nichts ist
  fest eingetragen.
- Grunddaten ohne Details: Abschick- und Lande-Zeitraum, Gegner-Stamm, Regeln und der Aufruf,
  **zusätzliche Fakes** zu schicken (mehr Fakes = Gegner findet die echten Angriffe schwerer).
- verrät keine Ziele und nicht, was echt bzw. Fake ist. Einzige Namen: Accounts mit Befehlen,
  die noch keinem Discord-Nutzer zugeordnet sind (`ap discord spieler`). Sie bekommen ihre
  Befehle nicht und werden gebeten, sich bei der SF zu melden.

Damit die Erwähnung ankommt, muss die Rolle erwähnbar sein: Servereinstellungen → Rollen →
Rolle → „Erlaube jedem, diese Rolle zu @erwähnen“. Das Tool sagt, wenn das fehlt.
