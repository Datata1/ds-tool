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
Im Spiel die Truppen-Tabelle kopieren, entweder deine Übersicht oder in der Stammes-Ansicht ein
Mitglied nach dem anderen. Alles untereinander in `stamm.txt` einfügen.
```bash
uv run ap sync                       # Karte aktualisieren (max. 1x pro Stunde)
uv run ap troops import stamm.txt    # zeigt, wie viele Dörfer pro Spieler erkannt wurden
uv run ap troops show
```
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
Für jedes Ziel öffnet sich ein neuer Plan. Der Text liegt in der Zwischenablage (`k` = nochmal
kopieren). **Titel setzen → Import/Export → Import Workbench → Importieren →** Link aus der
Adressleiste ins Terminal kopieren. Das Tool prüft jeden Plan. Danach:
```bash
uv run ap op links data/<welt>/ops/<name>/operation.yaml     # Ansehen-Links
uv run ap op check data/<welt>/ops/<name>/operation.yaml --dsu
```
und in Claude Code `/discord-nachricht` (review). Die Nachricht wird automatisch in Teile von
höchstens 2.000 Zeichen aufgeteilt.

**Änderungswünsche:** `operation.yaml` anpassen (oder dem Agenten sagen), neu rechnen, betroffene
Pläne in DS Ultimate löschen und mit `--alle` neu anlegen. Eine **Alternative** legst du als
eigene Operation in einem neuen Ordner an. Die bestehende bleibt so, wie sie ist.

## 6. Freigabe, Spieler-Pläne, Ankündigung
```bash
uv run ap op status data/<welt>/ops/<name>/operation.yaml approved --note "SF ok"
uv run ap op dsu data/<welt>/ops/<name>/operation.yaml --fuer spieler
```
Danach `/discord-nachricht` (spieler): Jeder Spieler bekommt die Zahl seiner Befehle, seinen
ersten Abschick und den Link zu seinem Plan.

## Wing / verbündete Stämme
Hat der Wing schon einen DS-Ultimate-Plan für ein Ziel, trägst du dessen Bearbeiten-Link als
`dsu_plan` ein. Das Tool liest die Wing-Angriffe (nur lesen) und stimmt den Main darauf ab. Eine
Wing-Off kann z.B. eure AGs decken, und eure Off deckt Wing-AGs. Siehe
[operation.md](operation.md#bestehende-ds-ultimate-pläne).
