---
name: google-doc
description: Legt das Google Doc zu einer Operation an oder aktualisiert es (Ablauf, Wichtig beim Abschicken, Tabelle pro Ziel, Abschick-Reihenfolge) - über den Google-Drive-Connector, ohne eigene Google-Einrichtung.
---

# /google-doc

Erzeugt das Spieler-Dokument einer Operation und lädt es als Google Doc hoch.

**Das Doc ist die Projektion des aktuellsten Plans** (Wunsch des Stammesleiters):
- Es wird **automatisch** angelegt, sobald der erste Plan einer Aktion steht (nach `ap op solve`
  ohne Fehler) - nicht erst auf Nachfrage. Das Anlegen im eigenen Drive braucht kein extra OK.
- Danach wird bei jeder Änderung (neu gerechnet, neue DS-Ultimate-Links, neue Beschreibung)
  **dasselbe Doc** neu befüllen - nie ein zweites anlegen. Ob es veraltet ist, merkt sich das Tool
  (`gdoc_stand` in operation.yaml); `ap op solve` sagt es an.
- Es ist immer freigegeben als **„Jeder mit dem Link: Betrachter“** (nur ansehen) und der
  Ansehen-Link steht im SF-Review (`/discord-nachricht` review). Ohne aktuelles, freigegebenes
  Doc geht das Review nicht raus.

In Claude Desktop (MCP-Tools) liefert `solve_operation` bzw. `operation_doc` die fertigen Schritte
unter `google_doc.schritte` - einfach der Reihe nach ausführen.

1. Operation finden (`ls data/*/ops/*/operation.yaml`, neueste vorschlagen). Ist `plan.json`
   älter als `operation.yaml`, zuerst `uv run ap op solve`.
2. Optional „Worum geht es?“: Hat die Operation kein `beschreibung`, kurz fragen oder aus dem
   Kontext vorschlagen (2-4 Sätze/Stichpunkte, Zeilen mit `- ` werden Aufzählungen, `**fett**`
   geht). Per YAML laden → `beschreibung` setzen → speichern (nie Schlüssel anhängen).
3. `uv run ap op doc <pfad>/operation.yaml` schreibt `<pfad>/doc.html`.
4. Hochladen bzw. aktualisieren (automatisch, siehe oben):
   - **Neu** (`gdoc_id` leer): Drive-Connector `create_file` mit `title` = Name der Operation,
     `textContent` = Inhalt von `doc.html`, `contentMimeType: text/html` (Google wandelt es in
     ein Doc um). Dann freigeben: Drive-Connector `share_file` mit `fileId` = id,
     `permissionId: anyoneWithLink`, `role: reader`. Danach
     `uv run ap op doc <pfad> --gdoc <id> --geteilt` zum Merken (Doc, Stand, Freigabe).
   - **Schon vorhanden** (`gdoc_id` gesetzt): **immer dasselbe Doc bearbeiten, nie ein neues
     anlegen** (Link bleibt gleich):
     1. Google-Docs-Connector `read_doc` mit der `gdoc_id` → `endIndex` des letzten Elements von
        `tabs[0].documentTab.body.content` merken (nur diese Zahl, Rest ignorieren).
     2. `uv run ap op doc <pfad>/operation.yaml --ende <endIndex>` → `<pfad>/doc_update.json`.
     3. `update_doc` mit `documentId` = `gdoc_id` und `requests` = Inhalt von `doc_update.json`
        (unverändert übernehmen). Sehr große Pläne: in mehreren Aufrufen in der gegebenen
        Reihenfolge schicken, nie umsortieren.
     4. Kurz prüfen: `read_doc` → erste Tabellenzelle heißt „Ankunft“. Bei Fehler nichts von Hand
        flicken, Fehlermeldung zeigen.
     5. `uv run ap op doc <pfad> --geschrieben` - merkt, dass das Doc jetzt den aktuellen Plan
        zeigt (ist es noch nicht freigegeben: erst `share_file` wie oben, dann zusätzlich
        `--geteilt`).
     Hat jemand im Doc von Hand etwas ergänzt, ist es danach weg (Doc wird komplett neu
     geschrieben) - vorher fragen, wenn das möglich ist.
5. Format nie von Hand nachbauen: Das Aussehen (A4 quer, Farben, Spaltenbreiten) kommt fest aus
   `export/gdoc.py` (siehe `docs/google.md`, Abschnitt „Format“).
6. Link ausgeben: `https://docs.google.com/document/d/<id>/view` (Ansehen-Link). Ohne
   Google-Drive-Connector: Der Nutzer fügt das Dokument in docs.new ein und stellt unter „Teilen“
   „Jeder mit dem Link: Betrachter“ ein; dann `--gdoc <Link> --geteilt`.

Nie Bearbeiten-Links von DS Ultimate (`/edit/`) ins Doc schreiben - das Tool nimmt nur
Ansehen-Links. Daten im Doc nie von Hand ändern, sondern neu rechnen und neu erzeugen.
