"""MCP server exposing the planner to Claude (Code / Desktop).

Register in Claude Code via ``.mcp.json`` (``uv run ap-planner-mcp``).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from mcp.server.mcpserver import MCPServer

from ap_planner import services
from ap_planner.config import Settings
from ap_planner.export.announce import discord_players, discord_review, split_discord
from ap_planner.ingest.store import WorldStore
from ap_planner.models.map import Coord
from ap_planner.models.operation import Operation
from ap_planner.models.world import Unit

INSTRUCTIONS = """\
Angriffsplaner für Die Stämme / Tribal Wars. Du hilfst dem Spieler, eine Strategie in
konkrete Befehle zu verwandeln. Regeln:
- Kein Botting: nie Spielaktionen automatisieren, nur öffentliche Weltdaten, vom Spieler
  importierte Truppen und DS-Ultimate-Pläne über Links des Spielers verwenden.
- Zuerst `get_profile` lesen: Stamm, Wing, Vorgaben und `preferences` des Spielers gelten immer.
- Spielregeln stehen im Prompt `ds-grundlagen` (u.a. ohne ms: gleiche Sekunde = Abschick-
  Reihenfolge, ein AG landet nie ohne Off davor).
- Unklare Angaben (Spieler, Stämme, Koordinaten) mit den Lookup-Tools auflösen.
- Nach jedem `solve_operation` das Ergebnis von `check_operation` beachten.
"""
SKILLS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "skills"

mcp = MCPServer("ap-planner", instructions=INSTRUCTIONS)
settings = Settings()


def _store() -> WorldStore:
    if not settings.world:
        msg = "Keine Welt gesetzt - im Projekt `uv run ap init` ausführen."
        raise RuntimeError(msg)
    return WorldStore.open(settings)


@mcp.tool()
def sync_world(force: bool = False) -> list[str]:
    """Download/refresh public world config and map data (cached for 1h)."""
    return [
        f"{r.name}: {'downloaded' if r.downloaded else 'cached'}"
        for r in services.sync_world(settings, force=force)
    ]


@mcp.tool()
def world_summary() -> dict[str, Any]:
    """World speed, unit speeds (min/field), night bonus, ms setting, data freshness."""
    return services.world_summary(_store()).model_dump()


@mcp.tool()
def player_info(name: str) -> dict[str, Any]:
    """Look up a player by name, including their tribe."""
    store = _store()
    p = store.player_by_name(name)
    if p is None:
        msg = f"Unknown player {name!r}"
        raise LookupError(msg)
    return p.model_dump()


@mcp.tool()
def find_villages(
    player: str | None = None,
    ally: str | None = None,
    center: str | None = None,
    radius: float = 10.0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Find villages by player name, tribe tag/name, or within radius of 'x|y'."""
    store = _store()
    if player:
        p = store.player_by_name(player)
        result = store.villages_of_player(p.id) if p else []
    elif ally:
        a = store.ally_by_tag(ally)
        result = store.villages_of_ally(a.id) if a else []
    elif center:
        result = store.villages_in_radius(Coord.parse(center), radius)
    else:
        msg = "Provide player, ally or center."
        raise ValueError(msg)
    return [v.model_dump() | {"coord": str(v.coord)} for v in result[:limit]]


@mcp.tool()
def travel_time(
    source: str, target: str, unit: Unit, arrival: datetime | None = None
) -> dict[str, Any]:
    """Distance, runtime and (if arrival given, ISO with offset) send time between villages.

    source/target: village id or 'x|y'.
    """
    t = services.travel_info(_store(), settings, source, target, unit, arrival=arrival)
    return {
        "source": t.source.model_dump(),
        "target": t.target.model_dump(),
        "unit": t.unit.value,
        "distance": round(t.distance, 3),
        "travel_seconds": t.travel_seconds,
        "send": t.send.isoformat() if t.send else None,
        "arrival_in_night_bonus": t.arrival_in_night_bonus,
    }


@mcp.tool()
def import_troops(text: str) -> dict[str, Any]:
    """Import copied troop tables (own overview or tribe member pages; several may be
    pasted below each other). Counts are totals per village incl. troops outside."""
    stored = services.import_overview_text(_store(), text)
    return {
        "imported": len(stored),
        "not_on_map": [str(v.coord) for v in stored if v.village_id is None],
    }


@mcp.tool()
def troops_overview() -> list[dict[str, Any]]:
    """All imported troops per village (totals incl. troops outside), with owner and time."""
    store = _store()
    return [
        {
            "village_id": vt.village_id,
            "player": services.owner_name(store, vt.village_id),
            "coord": str(vt.coord),
            "name": vt.name,
            "units": {u.value: n for u, n in vt.units.items()},
            "outgoing_commands": vt.outgoing,
            "incoming_attacks": vt.incoming,
            "source": source,
            "captured_at": captured,
        }
        for vt, source, captured in store.troops()
    ]


# --- profile & operations ---------------------------------------------------------


def _op_path(name: str) -> Path:
    path = settings.world_dir / "ops" / name / "operation.yaml"
    if not path.exists():
        msg = f"Operation {name!r} nicht gefunden - siehe list_operations."
        raise FileNotFoundError(msg)
    return path


@mcp.tool()
def get_profile() -> dict[str, Any]:
    """Profil des Spielers (Stamm, Wing, Vorgaben, Strategie-Vorlieben). Immer zuerst lesen."""
    profile = services.load_profile(settings.world_dir)
    if profile is None:
        return {"error": "Kein Profil - im Projekt `uv run ap init` ausführen."}
    return profile.model_dump(mode="json")


@mcp.tool()
def list_operations() -> list[dict[str, Any]]:
    """Alle Operationen dieser Welt mit Status und Anzahl Ziele."""
    out: list[dict[str, Any]] = []
    for path in sorted((settings.world_dir / "ops").glob("*/operation.yaml")):
        try:
            op = services.load_operation(path)
        except ValueError as err:
            out.append({"name": path.parent.name, "error": str(err)[:200]})
            continue
        out.append(
            {
                "name": path.parent.name,
                "title": op.name,
                "status": op.status.value,
                "arrival": op.arrival.isoformat(),
                "targets": [str(t.coord) for t in op.targets],
                "planned": (path.parent / "plan.json").exists(),
            }
        )
    return out


@mcp.tool()
def write_operation(name: str, operation_yaml: str) -> dict[str, Any]:
    """Operation anlegen/überschreiben (YAML, Schema siehe Ressource operation-schema).

    Werte aus dem Profil müssen nicht wiederholt werden. Validiert vor dem Speichern.
    """
    folder = settings.world_dir / "ops" / services.safe_filename(name.lower())
    path = folder / "operation.yaml"
    folder.mkdir(parents=True, exist_ok=True)
    backup = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(operation_yaml, encoding="utf-8")
    try:
        op = services.load_operation(path)
    except ValueError as err:
        if backup is None:
            path.unlink()
        else:
            path.write_text(backup, encoding="utf-8")
        return {"error": f"Ungültig, nicht gespeichert: {err}"}
    return {"name": folder.name, "targets": len(op.targets)}


@mcp.tool()
def solve_operation(name: str) -> dict[str, Any]:
    """Operation planen; liefert Hinweise und den automatischen Review."""
    path = _op_path(name)
    out = services.solve_operation(_store(), settings, path)
    report = services.check_operation(_store(), settings, path)
    return {
        "commands": len(out.plan.commands),
        "warnings": out.plan.warnings,
        "check_errors": report.errors,
        "check_warnings": report.warnings,
        "review_md": out.review.read_text(encoding="utf-8"),
    }


@mcp.tool()
def check_operation(name: str, with_dsu: bool = False) -> str:
    """Automatischer Review (doppelte Zuweisung, Reihenfolge-Regel, freie Truppen, Zeiten).

    with_dsu=True vergleicht zusätzlich die angelegten DS-Ultimate-Pläne mit der Planung.
    """
    path = _op_path(name)
    report = services.check_operation(_store(), settings, path, with_dsu=with_dsu)
    return report.markdown(services.load_operation(path).name)


@mcp.tool()
def discord_message(name: str, art: str = "review") -> list[str]:
    """Discord-Nachricht(en): art='review' (SF, pro Ziel) oder 'spieler' (Ankündigung)."""
    path = _op_path(name)
    op, plan = services.load_operation(path), services.load_plan(path)
    if art == "spieler":
        text = discord_players(op, plan, settings.timezone)
    else:
        text = discord_review(op, plan, services.target_infos(_store(), op), settings.timezone)
    return split_discord(text)


@mcp.resource("ap://operation-schema", name="operation-schema", mime_type="application/json")
def operation_schema() -> str:
    """JSON-Schema einer operation.yaml."""
    return json.dumps(Operation.model_json_schema(), ensure_ascii=False, indent=1)


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

        def make(content: str = body.strip()) -> str:
            return content

        mcp.prompt(name=name, description=str(meta.get("description", "")))(make)


_register_skill_prompts()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
