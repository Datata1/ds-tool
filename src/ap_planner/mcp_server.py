"""MCP server exposing the planner to Claude (Desktop / Code).

- Claude Code: ``.mcp.json`` (``uv run ap-planner-mcp``) in the project folder.
- Claude Desktop: the extension ``ap-planner.mcpb`` (``scripts/build_mcpb.py``), which sets
  ``AP_HOME`` to the player's data folder.

Every use case (``usecases.py``) is a tool, so players without a terminal can do everything
in the chat. The desktop app uses the same functions over HTTP (``api/``).
"""

import functools
import json
from collections.abc import Callable
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ap_planner import usecases
from ap_planner.models.operation import Operation
from ap_planner.models.profile import Profile
from ap_planner.usecases import EXPECTED_ERRORS, SKILLS_DIR

INSTRUCTIONS = """\
Angriffsplaner für Die Stämme / Tribal Wars. Du hilfst dem Spieler, eine Strategie in
konkrete Befehle zu verwandeln. Die Spieler sind meist keine Programmierer: einfach auf Deutsch
erklären, keine Dateipfade oder Befehle zeigen, immer den nächsten Schritt vorschlagen.

Regeln:
- Kein Botting: nie Spielaktionen automatisieren, nur öffentliche Weltdaten, vom Spieler
  eingefügte Truppen und DS-Ultimate-Pläne über Links des Spielers verwenden.
- Zu Beginn `overview` aufrufen. Fehlt die Welt: `setup_world`. Danach `get_profile` lesen:
  Stamm, Wing, Vorgaben und `preferences` des Spielers gelten immer.
- Spielregeln stehen im Prompt `ds-grundlagen` (u.a. ohne ms: gleiche Sekunde = Abschick-
  Reihenfolge, ein AG landet nie ohne Off davor).
- Unklare Angaben (Spieler, Stämme, Koordinaten) mit den Lookup-Tools auflösen.
- Strategie-Fragen (nächste Ziele, Laufzeiten, Readel): `strategie_ziele` und
  `readel_analyse`, Prompt `strategie-beratung`. Vorschläge kann der Spieler direkt als neue
  Operation übernehmen (`write_operation`).
- Nach jedem `solve_operation` das Ergebnis von `check_operation` beachten.
- Google Doc = Projektion des aktuellsten Plans: Liefert `solve_operation` (oder ein anderes
  Tool) `google_doc.schritte`, diese Schritte gleich danach ohne Rückfrage ausführen (vom
  Stammesleiter so festgelegt): beim ersten Plan Doc anlegen und für alle mit Link lesbar
  freigeben, danach immer dasselbe Doc neu befüllen, nie ein zweites anlegen. Das Review an
  die SF geht erst raus, wenn das Doc aktuell und freigegeben ist (Link steht dann drin).
- Was nach außen geht (DS-Ultimate-Pläne, Discord), erst zeigen und nach OK mit
  `bestaetigt=true` ausführen.
- Truppen: bevorzugt `troops_collect_start` (Sammel-Modus im Hintergrund: der Spieler kopiert
  alle Truppen-Seiten nacheinander mit Strg+A, Strg+C, ohne auf dich zu warten, und sagt
  „fertig“ → `troops_collect_stop`). Schneller: `truppen_skript` (Schnellleisten-Skript liest
  alle Mitglieder mit einem Klick; den Export kopieren, während der Sammel-Modus läuft).
  Für eine einzelne Seite: `import_troops_from_clipboard`.
  Lange eingefügte Tabellen nie selbst abtippen.
- Einrichtung (DS Ultimate, Discord-Bot, Google Docs, Connectoren): `setup_check` und Prompt
  `einrichtung`. Handbuch: `help_docs`.

Die Prompts (Skills) beschreiben Befehle für die Konsole (`uv run ap …`). Ohne Konsole nimm
stattdessen diese Tools - nie den Spieler bitten, etwas in einer Konsole auszuführen oder
Dateien anzulegen:
  ap init → setup_world | ap profil → get_profile (ändern: save_profile)
  ap sync → sync_world | ap info → world_summary | ap travel → travel_time
  ap villages → find_villages | ap troops sammeln → troops_collect_start/_status/_stop
  | ap troops import → import_troops_from_clipboard | ap troops skript → truppen_skript
  (kurze Texte aus dem Chat: import_troops) | ap troops show → troops_overview
  | ap troops status → troops_status | ap op neu / operation.yaml schreiben →
  write_operation (lesen: get_operation) | ap op solve → solve_operation
  | ap op check [--dsu] → check_operation | ap op dsu → dsu_publish (--manuell:
  workbench_text) | ap op links → dsu_links | ap op link → dsu_save_link
  | ap op status → set_status | ap op aktion → aktion_message | ap op rueckkehr → returns
  | ap op sim → simulate_train | ap op doc → operation_doc | ap op discord → discord_message
  bzw. discord_send (Befehle an Spieler: art='thread', wenn Kanal 'befehle' eingerichtet,
  sonst 'dm') | ap op fortschritt → dsu_progress | Erinnerungen → discord_remind
  | ap discord einrichten → discord_setup | ap discord spieler →
  discord_members + discord_assign | docs/*.md → help_docs. Dateien wie review.md oder
  check.md liefern die Tools direkt als Text.
"""
mcp = MCPServer("ap-planner", instructions=INSTRUCTIONS)


def tool[F: Callable[..., Any]](fn: F) -> F:
    """``@mcp.tool()`` that shows expected errors to Claude in plain words.

    mcp 2.x hides the text of ordinary exceptions ("Error executing tool x"); our errors are
    meant for the player, so they are passed on as ToolError.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - any tool result
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except EXPECTED_ERRORS as err:
            raise ToolError(str(err) or type(err).__name__) from err

    mcp.tool()(wrapper)
    return fn


for _name, _fn in usecases.REGISTRY.items():
    if _name not in usecases.APP_ONLY:
        tool(_fn)


# --- resources & prompts ----------------------------------------------------------


@mcp.resource("ap://operation-schema", name="operation-schema", mime_type="application/json")
def operation_schema() -> str:
    """JSON-Schema einer operation.yaml."""
    return json.dumps(Operation.model_json_schema(), ensure_ascii=False, indent=1)


@mcp.resource("ap://profile-schema", name="profile-schema", mime_type="application/json")
def profile_schema() -> str:
    """JSON-Schema des Profils (profil.yaml)."""
    return json.dumps(Profile.model_json_schema(), ensure_ascii=False, indent=1)


START_PROMPT = """\
Hilf mir mit dem Angriffsplaner. Ruf zuerst `overview` auf und sag mir in einfachen Worten,
wo ich stehe und was der nächste Schritt ist. Ablauf: Einrichten (Welt, Stamm) → Vorgaben
(profil-einrichten) → Truppen einfügen → Operation planen (neue-operation) → prüfen →
DS-Ultimate-Pläne → Freigabe → Nachrichten an die Spieler. Frag immer nur ein, zwei Dinge auf
einmal und schlag sinnvolle Antworten vor.
"""


@mcp.prompt(name="start", description="Einstieg: Wo stehe ich, was ist der nächste Schritt?")
def start() -> str:
    return START_PROMPT


DESKTOP_NOTE = (
    "Hinweis: Steht unten ein Konsolen-Befehl (`uv run ap …`) und du hast keine Konsole, nimm "
    "das passende ap-planner-Tool (Zuordnung in den Server-Anweisungen). Dateien liefern die "
    "Tools als Text. Fragen stellst du direkt im Chat.\n\n"
)


def _register_skill_prompts() -> None:
    """Expose the repo skills (.claude/skills/*/SKILL.md) as MCP prompts for other clients."""
    if not SKILLS_DIR.exists():
        return
    for skill_file in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        body = text
        if text.startswith("---"):
            _, front, body = text.split("---", 2)
            meta = yaml.safe_load(front) or {}
        name = str(meta.get("name", skill_file.parent.name))

        def make(content: str = DESKTOP_NOTE + body.strip()) -> str:
            return content

        mcp.prompt(name=name, description=str(meta.get("description", "")))(make)


_register_skill_prompts()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
