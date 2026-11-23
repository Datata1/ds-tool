"""In-game quickbar script that reads the tribe's troop pages (run by the player himself).

The readable source is ``truppen.js`` next to this file. For the quickbar it is turned into a
single ``javascript:`` line: comment lines are dropped and the rest is joined with spaces (the
source ends every statement with ``;`` and keeps comments on their own lines for that).
The script only reads game pages in the player's own browser, one after the other with a
pause, and never sends anything to another server; the planner itself never opens game pages.
"""

from pathlib import Path

SOURCE = Path(__file__).with_name("truppen.js")

STEPS = [
    "Im Spiel: Einstellungen → Schnellleiste → „Neuen Link hinzufügen“.",
    "Name z.B. „AP Truppen“, als Ziel-URL die ganze Zeile `javascript:…` einfügen → Speichern. "
    "Nimmt die Schnellleiste die lange Zeile nicht an: im Browser ein Lesezeichen mit dieser "
    "Zeile als Adresse anlegen und es auf der Spielseite anklicken.",
    "Stamm → Mitglieder → Truppen öffnen und in der Schnellleiste „AP Truppen“ klicken. Das "
    "Skript liest nacheinander alle Mitglieder, die ihre Truppen mit dem Stamm teilen "
    "(etwa 1 Sekunde pro Spieler).",
    "Am Ende „Kopieren“ klicken und den Text in den ap-planner einfügen (läuft der "
    "Sammel-Modus, reicht das Kopieren).",
]

WARNING = (
    "Keine Gewähr: Das Skript liest nur (keine Spielaktionen) und schickt nichts nach außen. "
    "Ob eigene Skripte auf deiner Welt erlaubt sind, entscheiden die Regeln von InnoGames."
)


def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def version() -> str:
    for line in source().splitlines():
        if line.strip().startswith('var VERSION = "'):
            return line.split('"')[1]
    return "?"


def quickbar_code() -> str:
    """The script as one ``javascript:`` line for the quickbar."""
    lines = [ln.strip() for ln in source().splitlines()]
    code = " ".join(ln for ln in lines if ln and not ln.startswith("//"))
    # javascript: URLs are percent-decoded by the browser, so a literal "%" must be escaped
    return f"javascript:{code}void 0;".replace("%", "%25")
