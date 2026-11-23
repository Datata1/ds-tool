# Google Doc pro Operation

Für jede Operation kann das Tool ein Dokument für die Spieler erzeugen, aufgebaut wie unsere
Docs von Hand:

- Titel und Untertitel (Ziele, Stand)
- **Worum geht es?** aus dem Feld `beschreibung` in `operation.yaml` (sonst eine kurze
  Übersicht pro Ziel)
- **Wichtig beim Abschicken** (sekundengenau, Offs vor AGs, Begleitschutz, Flexdeff, Fakeschutz)
- pro Ziel: Anzahl Offs/AGs/Flexdeff, ein Satz zum Aufbau („Um 08:59:59 kommen 2 Offs …“), der
  DS-Ultimate-Ansehen-Link und eine Tabelle in Landungs-Reihenfolge
- am Ende alle Befehle aller Ziele nach Abschickzeit

```bash
uv run ap op doc data/de260/ops/<name>/operation.yaml     # schreibt doc.html
```

## Immer aktuell, immer verlinkt

Das Doc ist die **Projektion des aktuellsten Plans**:

- Sobald der erste Plan einer Aktion steht (`ap op solve` ohne Fehler), legt Claude das Doc
  automatisch an und gibt es frei: **„Jeder mit dem Link: Betrachter“** (nur ansehen).
- Bei jeder Änderung (neu gerechnet, neue DS-Ultimate-Links, neue Beschreibung) wird **dasselbe
  Doc** neu befüllen - der Link bleibt gleich. Ob das Doc veraltet ist, merkt sich das Tool in
  `operation.yaml` (`gdoc_stand`, `gdoc_geteilt`); `ap op solve` sagt es an.
- Das SF-Review (`ap op discord --art review`) enthält oben den Ansehen-Link zum Doc. In Claude
  Desktop geht das Review erst raus, wenn das Doc aktuell und freigegeben ist.

## Hochladen

**Mit Claude (empfohlen, keine Einrichtung):** In Claude Code `/google-doc` sagen. Claude lädt
`doc.html` über den Google-Drive-Connector hoch, Google macht daraus ein normales Doc, und die ID
wird in der Operation gemerkt. Dafür muss der Google-Drive-Connector in Claude aktiviert sein.

**Von Hand:** In Google Drive „Neu → Datei hochladen“ → `doc.html` wählen → Rechtsklick
„Öffnen mit → Google Docs“. Danach die ID merken:

```bash
uv run ap op doc data/de260/ops/<name>/operation.yaml --gdoc <Link oder ID> --geteilt
```

`--geteilt` erst, wenn unter „Teilen“ „Jeder mit dem Link: Betrachter“ eingestellt ist. Nach
einem Neu-Befüllen des bestehenden Docs: `--geschrieben`.

## Nach einer Neuberechnung
Es bleibt **dasselbe Doc mit demselben Link**. Claude liest, wie lang das Doc ist, erzeugt mit
`ap op doc PFAD --ende <endIndex>` die Änderungen (`doc_update.json`) und schreibt den Inhalt
über den Google-Docs-Connector komplett neu, im selben Format wie beim ersten Hochladen.
Handschriftliche Ergänzungen im Doc gehen dabei verloren - Anmerkungen lieber als Kommentar.

## Format (Vorlage)

Alle Docs haben dasselbe Format wie das Vorbild „RAK Aktion Do 12.11.“:

- **Seite:** A4 quer, Schrift Arial 10,5.
- **Überschriften:** Titel und Überschriften dunkelrot.
- **Tabellen:** grauer Tabellenkopf, feste Spaltenbreiten.
- **Spalte „Was“ farbig:**
  - Off: rot
  - AG: gelb
  - Flexdeff: blau
  - Fake: grau

Das Format steht an einer Stelle: in den Stil-Konstanten oben in `src/ap_planner/export/gdoc.py`. Wer das Aussehen ändern will, ändert es nur dort, dann sehen alle künftigen Docs gleich aus.

## Desktop-App: eigener Google-Login (einmalig für den Betreuer)

Die Desktop-App braucht keinen Claude-Connector. Spieler klicken nur **„Mit Google anmelden“**.
Die App darf dann ausschließlich Dateien sehen und ändern, die sie selbst angelegt hat
(Berechtigung `drive.file`). Google verlangt dafür keine App-Prüfung.

Dafür legt der Betreuer der App **einmal** einen Google-Zugang an:
1. <https://console.cloud.google.com> → neues Projekt, z.B. „AP-Planer“.
2. „APIs & Dienste“ → **Google Drive API** und **Google Docs API** aktivieren.
3. „OAuth-Zustimmungsbildschirm“: Typ **Extern**, App-Name, Support-Mail, Bereich
   `.../auth/drive.file` hinzufügen. Status **„In Produktion“** setzen (sonst nur Testnutzer).
4. „Anmeldedaten“ → **OAuth-Client-ID** → Typ **Desktop-App** → Client-ID und
   Client-Secret kopieren.
5. Beim Bauen der App als GitHub-Secrets `AP_GOOGLE_CLIENT_ID` / `AP_GOOGLE_CLIENT_SECRET`
   hinterlegen (landen in `src/ap_planner/builtin.py`). Zum Testen reicht `.env`:
   `AP_GOOGLE_CLIENT_ID=…` und `AP_GOOGLE_CLIENT_SECRET=…`.

Bei Desktop-Apps gilt das Client-Secret laut Google nicht als geheim. Die Anmeldung jedes
Spielers (Token) liegt nur auf seinem Rechner in `google_token.json` im Datenordner.

In der App erledigt **„Google Doc aktualisieren“** alles auf einmal: beim ersten Mal anlegen
und für alle mit Link lesbar freigeben, danach dasselbe Doc neu befüllen.
