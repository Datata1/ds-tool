# Ablauf einer Operation

```
Einrichten ─▶ Truppen ─▶ Planen ─▶ Prüfen ─▶ SF-Review ─▶ Freigabe ─▶ Spieler-Pläne ─▶ Ankündigung
 ap init      import     solve     check     dsu ziele     status      dsu spieler      discord
```

## 1. Einmalig: Einrichten
```bash
uv sync
uv run ap init          # fragt Welt (z.B. de260), Stamm-Tag, Wing-Tags
```
Das Tool schreibt `.env` (deine Welt), lädt die Weltdaten und legt `data/<welt>/profil.yaml` an.
Danach in Claude Code `/profil-einrichten`: volle Off, Begleitschutz, Fakeschutz, Zeitfenster
und deine Vorlieben ([Profil](profil.md)).

## 2. Vor jeder Operation: Truppen einlesen
Am bequemsten mit dem **Sammel-Modus**: Das Tool beobachtet die Zwischenablage. Du öffnest im
Spiel die Truppen-Seite eines Mitglieds nach dem anderen und drückst jeweils nur Strg+A, Strg+C.
```bash
uv run ap sync                       # Karte aktualisieren (max. 1x pro Stunde)
uv run ap troops sammeln             # importiert jede Kopie sofort, zeigt "fehlen noch: ..."
uv run ap troops status              # wer hat aktuelle Daten, wer fehlt
uv run ap troops show                # alle Truppen mit Alter der Daten
```
Der Sammel-Modus hört auf, wenn alle Spieler deines Stamms da sind (oder mit Strg+C). Die
Kopien landen zusätzlich in `data/<welt>/truppen/`. Das Tool öffnet dabei **keine** Spielseiten,
es liest nur, was du selbst kopierst.

**Noch schneller mit dem Truppen-Skript:** `uv run ap troops skript` legt eine Zeile für die
Schnellleiste in die Zwischenablage (Anleitung wird angezeigt). Im Spiel auf Stamm → Mitglieder
→ Truppen einmal klicken: Das Skript liest nacheinander alle Mitglieder, die ihre Truppen mit
dem Stamm teilen, und zeigt einen Text zum Kopieren. Läuft der Sammel-Modus, reicht
„Kopieren“; sonst `uv run ap troops import` und einfügen. Das Skript liest nur, schickt nichts
an fremde Server und lädt keinen Code nach. Keine Gewähr: Ob eigene Skripte auf deiner Welt
erlaubt sind, regeln die Spielregeln von InnoGames.

Ohne Zwischenablage-Zugriff geht es wie früher: alles untereinander in `stamm.txt` einfügen und
`uv run ap troops import stamm.txt`.

Die Spieler werden über die Koordinaten aus den Kartendaten erkannt. Gezählt werden alle
Truppen eines Dorfes, auch die gerade unterwegs.

## 3. Planen
In Claude Code: **`/neue-operation`**. Der Agent fragt Ziele, Offs, AGs, Fakes, Flexdeff und
Zeiten ab, schreibt `data/<welt>/ops/<name>/operation.yaml` ([Format](operation.md)) und rechnet:
```bash
uv run ap op solve data/<welt>/ops/<name>/operation.yaml
```
Ergebnis im Ordner der Operation:

| Datei | Inhalt |
|---|---|
| `review.md` | Ziele, Hinweise, Befehle pro Ziel in Lande-Reihenfolge, Readel-Gefahr, Readel-Reserve |
| `ziele/*.txt` | Workbench-Text pro Zieldorf (für die Stammesführung) |
| `spieler/*.txt` | Workbench-Text pro Spieler (nur seine Befehle) |
| `plan.json` | die Planung maschinenlesbar |

## 4. Automatischer Review
```bash
uv run ap op check data/<welt>/ops/<name>/operation.yaml
```
**Fehler** (doppelt verplante Truppen oder AGs, AG ohne Off davor, Abschickzeit vorbei) müssen
behoben werden. Dazu kommen **Hinweise** (Fakeschutz, Nachtbonus, alte Daten, Abweichung vom
Profil) und eine Liste **freier Truppen**. Das Ergebnis steht in `check.md`.

## 5. SF-Review in DS Ultimate
```bash
uv run ap op dsu data/<welt>/ops/<name>/operation.yaml --fuer ziele
```
Das Tool zeigt, welche Pläne es anlegt, und fragt einmal nach. Danach legt es für jedes Ziel einen
Plan bei DS Ultimate an, setzt den Titel, importiert die Angriffe und prüft jeden Plan. Du musst
nichts kopieren. (Falls DS Ultimate einmal streikt: `--manuell` ist der alte Weg von Hand.) Danach:
```bash
uv run ap op links data/<welt>/ops/<name>/operation.yaml     # Ansehen-Links
uv run ap op check data/<welt>/ops/<name>/operation.yaml --dsu
```
und in Claude Code `/discord-nachricht` (review). Die Nachricht wird automatisch in Teile von
höchstens 2.000 Zeichen aufgeteilt.

**Änderungswünsche:** `operation.yaml` anpassen (oder dem Agenten sagen), neu rechnen und
`ap op dsu … --aktualisieren`: Die Pläne werden geleert und neu befüllt, **die Links bleiben gleich**. Eine **Alternative** legst du als
eigene Operation in einem neuen Ordner an. Die bestehende bleibt so, wie sie ist.

## 6. Freigabe, Spieler-Pläne, Ankündigung
```bash
uv run ap op status data/<welt>/ops/<name>/operation.yaml approved --note "SF ok"
uv run ap op dsu data/<welt>/ops/<name>/operation.yaml --fuer spieler
```
Danach `/discord-nachricht`: Die Ankündigung (spieler) ist bewusst neutral (Zeitraum, Hinweis
dass auch andere schicken und gefaket wird, Regeln) und verrät keine Ziele, Links oder was echt
bzw. Fake ist. Seine Befehle und seinen Plan-Link bekommt jeder privat (thread bzw. dm).

## Wing / verbündete Stämme
Hat der Wing schon einen DS-Ultimate-Plan für ein Ziel, trägst du dessen Bearbeiten-Link als
`dsu_plan` ein. Das Tool liest die Wing-Angriffe und stimmt den Main darauf ab. Eine
Wing-Off kann z.B. eure AGs decken, und eure Off deckt Wing-AGs. Siehe
[operation.md](operation.md#bestehende-ds-ultimate-pläne).
