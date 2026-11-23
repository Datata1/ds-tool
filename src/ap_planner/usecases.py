"""Use cases of the planner: one function per step, shared by all front ends.

- ``mcp_server.py`` exposes every use case as an MCP tool (Claude Desktop / Code).
- ``api/`` exposes the same functions over HTTP for the desktop app (no AI needed).

Each function takes plain JSON-able arguments and returns JSON-able data. Errors meant for
the player are raised as one of ``EXPECTED_ERRORS`` with a plain German message. The
docstrings double as tool descriptions for Claude.
"""

import json
import os
import sys
import time
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
import yaml

from ap_planner import builtin, discord_sync, ingame, services, troop_collect
from ap_planner.config import Settings, app_home
from ap_planner.discord_bot import (
    DiscordClient,
    DiscordError,
    application_id,
    invite_url,
    pick_by_name,
)
from ap_planner.domain import battle, strategy, travel
from ap_planner.dsu import DsuClient, DsuLinkError
from ap_planner.dsu_api import DsuApiClient, DsuApiError
from ap_planner.dsu_web import DsuWebClient, DsuWebError
from ap_planner.export.aktion import AktionOp, aktion_markdown, aktion_messages
from ap_planner.export.announce import (
    discord_players,
    discord_review,
    enemy_tribes,
    split_discord,
)
from ap_planner.export.review import kind_label, player_commands, unit_text, who
from ap_planner.google_client import GoogleClient, OAuthClient
from ap_planner.ingest.store import WorldStore
from ap_planner.models.discord import user_ids
from ap_planner.models.map import Coord
from ap_planner.models.operation import DsuMode, Operation, PlanKind, Status
from ap_planner.models.plan import Plan, PlannedCommand
from ap_planner.models.profile import Profile
from ap_planner.models.world import Unit

# Project root with docs/ and .claude/skills/. In the desktop app's single-file server
# (PyInstaller) they are unpacked next to the code into sys._MEIPASS.
ROOT = (
    Path(getattr(sys, "_MEIPASS", ""))
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2]
)
SKILLS_DIR = ROOT / ".claude" / "skills"
DOCS_DIR = ROOT / "docs"

# Claude Desktop / the desktop app start the server somewhere (often "/"): work in the
# player's folder, so .env, data/ and aktion.md are found there.
os.chdir(app_home())
settings = Settings()


# Every use case is registered here; the MCP server and the REST API expose all of them.
REGISTRY: dict[str, Callable[..., Any]] = {}

# Errors meant for the player ("Noch keine Welt …"): both servers pass their text on.
EXPECTED_ERRORS = (ValueError, LookupError, OSError, RuntimeError, httpx.HTTPError)


# Use cases only for the desktop app (Claude has its own Google connectors instead).
APP_ONLY: set[str] = set()


def usecase[F: Callable[..., Any]](fn: F) -> F:
    """Register a use case (name = function name, description = docstring)."""
    REGISTRY[str(getattr(fn, "__name__", fn))] = fn
    return fn


def app_usecase[F: Callable[..., Any]](fn: F) -> F:
    """A use case for the desktop app only (not offered to Claude as a tool)."""
    APP_ONLY.add(str(getattr(fn, "__name__", fn)))
    return usecase(fn)


def _reload_settings() -> None:
    global settings  # noqa: PLW0603 - settings change after setup_world
    settings = Settings()


def _store() -> WorldStore:
    if not settings.world:
        msg = "Noch keine Welt eingerichtet - zuerst `setup_world` (z.B. Welt de260)."
        raise RuntimeError(msg)
    return WorldStore.open(settings)


def _zone() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


# --- setup & overview -------------------------------------------------------------


@usecase
def overview() -> dict[str, Any]:
    """Wo steht der Spieler? Welt, Profil, Truppen, Operationen und der nächste Schritt.

    Zu Beginn jedes Gesprächs aufrufen.
    """
    out: dict[str, Any] = {"datenordner": str(Path.cwd()), "welt": settings.world or None}
    if not settings.world:
        out["naechster_schritt"] = (
            "Einrichten: Welt (z.B. de260), eigenen Stamm-Tag und Wing-Tags erfragen, dann "
            "setup_world."
        )
        return out
    profile = services.load_profile(settings.world_dir)
    out["profil"] = bool(profile)
    store = _store()
    troops = store.troops()
    out["truppen_doerfer"] = len(troops)
    if troops:
        newest = max(datetime.fromisoformat(c) for _, _, c in troops)
        out["truppen_stand"] = newest.astimezone(_zone()).strftime("%d.%m. %H:%M")
    ops = list_operations()
    out["operationen_anzahl"] = len(ops)
    # newest first, short: the full list is list_operations
    out["neueste_operationen"] = [
        {k: o.get(k) for k in ("name", "title", "status", "arrival")}
        for o in sorted(ops, key=lambda o: str(o.get("arrival", "")), reverse=True)[:5]
    ]
    out["discord_bot"] = bool(settings.discord_bot_token)
    if profile is None:
        step = "Profil fehlt: setup_world erneut ausführen."
    elif not troops:
        step = (
            "Truppen einlesen: Im Spiel Übersichten → Truppen (bzw. Stamm → Mitglieder → "
            "Truppen) → troops_collect_start, dann kopiert der Spieler alle Seiten mit "
            "Strg+A, Strg+C hintereinander und sagt „fertig“ → troops_collect_stop."
        )
    elif not ops:
        step = "Erste Operation planen (Prompt `neue-operation`)."
    else:
        step = "Operation weiterführen oder neue planen."
    out["naechster_schritt"] = step
    return out


@usecase
def setup_world(
    world: str,
    own_tribes: list[str],
    allied_tribes: list[str] | None = None,
    player: str = "",
    server: str = "die-staemme.de",
    overwrite_profile: bool = False,
) -> dict[str, Any]:
    """Ersteinrichtung (wie `ap init`): Welt merken, Weltdaten laden, Stamm-Profil anlegen.

    world z.B. "de260"; own_tribes/allied_tribes = Stamm-Tags (Wing = Verbündete).
    """
    world = world.strip().lower()
    services.write_env({"AP_WORLD": world, "AP_SERVER": server})
    os.environ.pop("AP_WORLD", None)
    os.environ.pop("AP_SERVER", None)
    _reload_settings()
    services.sync_world(settings)
    store = WorldStore.open(settings)
    tribes: list[str] = []
    for tag in [*own_tribes, *(allied_tribes or [])]:
        ally = store.ally_by_tag(tag)
        tribes.append(
            f"{tag}: gibt es auf {world} nicht - bitte prüfen"
            if ally is None
            else f"{tag}: {ally.name}, {ally.members} Mitglieder, {ally.villages} Dörfer"
        )
    existing = services.load_profile(settings.world_dir)
    if existing is not None and not overwrite_profile:
        profile_state = "Profil gab es schon - unverändert (ändern mit save_profile)."
    else:
        profile = Profile(
            world=world, server=server, player=player,
            own_tribes=own_tribes, allied_tribes=allied_tribes or [],
        )  # fmt: skip
        services.save_profile(profile, settings.world_dir)
        profile_state = "Profil angelegt."
    return {
        "welt": world,
        "staemme": tribes,
        "profil": profile_state,
        "naechste_schritte": [
            "Vorgaben festlegen (Prompt `profil-einrichten`)",
            "Truppen einfügen (import_troops)",
            "Operation planen (Prompt `neue-operation`)",
        ],
    }


@usecase
def sync_world(force: bool = False) -> list[str]:
    """Download/refresh public world config and map data (cached for 1h)."""
    return [
        f"{r.name}: {'downloaded' if r.downloaded else 'cached'}"
        for r in services.sync_world(settings, force=force)
    ]


@usecase
def world_summary() -> dict[str, Any]:
    """World speed, unit speeds (min/field), night bonus, ms setting, data freshness."""
    return services.world_summary(_store()).model_dump()


@usecase
def player_info(name: str) -> dict[str, Any]:
    """Look up a player by name, including their tribe."""
    store = _store()
    p = store.player_by_name(name)
    if p is None:
        msg = f"Unknown player {name!r}"
        raise LookupError(msg)
    return p.model_dump()


def _hms(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    h, rest = divmod(abs(seconds), 3600)
    return f"{sign}{h}:{rest // 60:02d}:{rest % 60:02d}"


def _reach(r: strategy.Reach | None) -> str | None:
    if r is None:
        return None
    who = f" ({r.player})" if r.player else ""
    return f"{_hms(r.seconds)} aus {r.coord}{who}"


@usecase
def strategie_ziele(
    gegner: str, max_ag_laufzeit_h: float = 12, deff_min_pop: int = 2000, limit: int = 15
) -> dict[str, Any]:
    """Strategie-Beratung: beste nächste Ziele in einem Gegner-Stamm (Tag/Name) oder bei einem
    Spieler, passend zu unseren eingelesenen Truppen.

    Pro Ziel: schnellste eigene AG-Laufzeit, AGs und volle Offs, die in max_ag_laufzeit_h
    ankommen, Readel-Vorteil (gegnerische AG-Laufzeit zurück minus unsere schnellste Deff mit
    mind. deff_min_pop Einwohnern; positiv = wir stehen zuerst), Gegner-Dichte (Dörfer im
    Umkreis 10 Felder), Moral. Gegner-AGs werden in jedem Gegnerdorf vermutet (vorsichtig).
    Daraus kann direkt eine Operation werden (write_operation).
    """
    store = _store()
    profile = services.load_profile(settings.world_dir)
    ranked, own_count = services.strategy_targets(
        store, profile, gegner, max_hours=max_ag_laufzeit_h, deff_min_pop=deff_min_pop,
        limit=limit,
    )  # fmt: skip
    ziele = []
    for s in ranked:
        margin = s.readel_margin_s
        ziele.append(
            {
                "ziel": f"{s.village.name} ({s.village.coord})",
                "besitzer": f"{s.owner} [{s.tribe}]",
                "punkte": s.village.points,
                "ag_laufzeit": _reach(s.ag),
                "ags_in_zeit": s.nobles_in_range,
                "volle_offs_in_zeit": s.offs_in_range,
                "eigene_deff": _reach(s.deff),
                "gegner_ag_zurueck": _reach(s.enemy_ag),
                "readel_vorteil": None if margin is None else _hms(margin),
                "gegner_doerfer_umkreis_10": s.density,
                "moral_pct": s.morale,
                "bewertung": s.score,
            }
        )
    out: dict[str, Any] = {"eigene_doerfer_mit_truppen": own_count, "ziele": ziele}
    if not ziele:
        out["hinweis"] = (
            f"Kein Dorf von {gegner} ist mit unseren AGs in {max_ag_laufzeit_h:g} h erreichbar "
            "(oder es sind keine AGs eingelesen). Größere Zeit oder anderen Gegner versuchen."
        )
    return out


@usecase
def readel_analyse(ziel: str, deff_min_pop: int = 2000, anzahl: int = 5) -> dict[str, Any]:
    """Detail zu einem Zieldorf (Koordinate oder Dorf-ID): wer von uns kann wie schnell adeln
    und stützen, wer vom Gegner kann wie schnell zurückadeln. Readel-Vorteil = schnellste
    Gegner-AG minus schnellste eigene Deff (positiv = wir halten das Dorf)."""
    store = _store()
    world = store.world_config()
    profile = services.load_profile(settings.world_dir)
    target = services.resolve_village(store, ziel)
    own = services.own_villages(store, profile.own_tribes if profile else [])
    if not own:
        msg = "Keine eingelesenen Truppen des eigenen Stamms - erst Truppen sammeln."
        raise ValueError(msg)

    def secs(o: strategy.OwnVillage, speed: float) -> int:
        dist = travel.distance(o.village.coord, target.coord)
        return travel.travel_seconds(dist, speed)

    snob = world.unit_speed_min(Unit.SNOB)
    ags = sorted(
        (
            (secs(o, snob), o)
            for o in own
            if o.units.get(Unit.SNOB, 0)
            and travel.distance(o.village.coord, target.coord) <= world.snob_max_dist
        ),
        key=lambda x: x[0],
    )[:anzahl]
    deffs = sorted(
        (
            (secs(o, speed), o)
            for o in own
            if (speed := o.deff_speed(world)) is not None and o.deff_pop(world) >= deff_min_pop
        ),
        key=lambda x: x[0],
    )[:anzahl]
    enemy = services.enemy_villages(store, target, float(world.snob_max_dist))
    enemy_sorted = sorted(enemy, key=lambda e: e.noble_seconds)[:anzahl]
    margin = enemy_sorted[0].noble_seconds - deffs[0][0] if enemy_sorted and deffs else None
    return {
        "ziel": f"{target.name} ({target.coord})",
        "eigene_ags": [
            f"{_hms(t)} aus {o.village.coord} ({o.player}, {o.units.get(Unit.SNOB, 0)} AG)"
            for t, o in ags
        ],
        "eigene_deff": [
            f"{_hms(t)} aus {o.village.coord} ({o.player}, {o.deff_pop(world)} Deff-Einwohner)"
            for t, o in deffs
        ],
        "gegner_zurueckadeln": [
            f"{_hms(e.noble_seconds)} aus {e.coord} ({e.player} [{e.tribe}])" for e in enemy_sorted
        ],
        "readel_vorteil": None if margin is None else _hms(margin),
        "hinweis": "Gegner-AGs werden in jedem Gegnerdorf vermutet; echte AG-Zahlen kennen wir "
        "nicht. Eigene Werte aus den eingelesenen Truppen (Alter: troops_status).",
    }


@usecase
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


@usecase
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


# --- troops -----------------------------------------------------------------------

_last_clipboard = {"text": ""}
# Claude Desktop cancels tool calls after about a minute: stay well below.
MAX_CLIPBOARD_WAIT = 40.0


@usecase
def import_troops_from_clipboard(wait_seconds: float = 30) -> dict[str, Any]:
    """Eine Truppen-Seite direkt aus der Zwischenablage einlesen, ohne Abtippen.

    Spieler: im Spiel die Truppen-Seite (eigene Übersicht oder Stamm → Mitglied → Truppen)
    öffnen, Strg+A, Strg+C. Das Tool wartet bis zu wait_seconds (max. 40) auf eine neue
    Kopie und importiert sie. Danach gleich wieder aufrufen, solange noch Spieler fehlen.
    """
    deadline = time.monotonic() + max(0.0, min(wait_seconds, MAX_CLIPBOARD_WAIT))
    store = _store()
    while True:
        text = troop_collect.read_clipboard()
        if text is None:
            return {
                "error": "Kein Zugriff auf die Zwischenablage. Ersatz: Text in den Chat "
                "einfügen → import_troops."
            }
        if text and text != _last_clipboard["text"] and troop_collect.looks_like_troops(text):
            break
        if time.monotonic() >= deadline:
            return {
                "importiert": 0,
                "hinweis": "Keine neue Truppen-Seite kopiert. Im Spiel Strg+A, Strg+C auf der "
                "Truppen-Seite, dann nochmal.",
            }
        time.sleep(0.7)
    _last_clipboard["text"] = text
    result = troop_collect.import_paste(store, text)
    log = settings.world_dir / "truppen" / f"{datetime.now(_zone()):%Y-%m-%d_%H%M}.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n\n")
    profile = services.load_profile(settings.world_dir)
    hours = profile.max_troop_age_hours if profile else 24
    since = datetime.now(UTC) - timedelta(hours=hours)
    status = troop_collect.status(store, list(profile.own_tribes) if profile else [], since)
    return {
        "importiert": len(result.rows),
        "pro_spieler": result.by_owner,
        "nicht_auf_karte": [str(v.coord) for v in result.unknown],
        "fertig": f"{len(status.done)}/{len(status.players)} Spieler",
        "fehlen_noch": [p.name for p in status.missing],
    }


_collector: troop_collect.ClipboardCollector | None = None


def _collect_report(p: troop_collect.CollectProgress) -> dict[str, Any]:
    store = _store()
    profile = services.load_profile(settings.world_dir)
    tribes = list(profile.own_tribes) if profile else []
    missing = troop_collect.status(store, tribes, p.started).missing if tribes else []
    return {
        "laeuft": p.running,
        "beendet_weil": p.stop_reason or None,
        "kopien_eingelesen": p.pages,
        "doerfer": p.villages,
        "pro_spieler": p.by_owner,
        "fehlen_noch": [f"{m.name} ({m.fresh}/{m.villages} Dörfer)" for m in missing],
        "nicht_auf_karte": p.unknown,
        "fehler": p.errors,
    }


@usecase
def troops_collect_start(minutes: float = 20) -> dict[str, Any]:
    """Sammel-Modus starten (empfohlen für viele Spieler): liest im Hintergrund JEDE neue
    Truppen-Seite aus der Zwischenablage, ohne dass der Spieler auf Claude warten muss.

    Danach dem Spieler sagen: alle Truppen-Seiten nacheinander öffnen, jeweils Strg+A, Strg+C,
    und am Ende „fertig“ schreiben. Dann troops_collect_stop. Endet auch von selbst nach
    `minutes` oder wenn alle Stammesmitglieder da sind. Zwischenstand: troops_collect_status.
    """
    global _collector  # noqa: PLW0603 - one collector per server
    if _collector is not None and _collector.running:
        return {"hinweis": "Sammeln läuft schon.", **troops_collect_status()}
    profile = services.load_profile(settings.world_dir)
    _store()  # fails early without a world
    world_settings = settings
    _collector = troop_collect.ClipboardCollector(
        lambda: WorldStore.open(world_settings),
        tribes=list(profile.own_tribes) if profile else [],
        log_path=settings.world_dir / "truppen" / f"{datetime.now(_zone()):%Y-%m-%d_%H%M}.txt",
    )
    p = _collector.start(minutes)
    return {
        "gestartet": True,
        "laeuft_bis": p.until.astimezone(_zone()).strftime("%H:%M"),
        "anleitung": "Jetzt im Spiel eine Truppen-Seite nach der anderen öffnen (eigene "
        "Übersicht bzw. Stamm → Mitglieder → Truppen), jeweils Strg+A, Strg+C. Nicht auf "
        "Claude warten. Am Ende „fertig“ schreiben.",
    }


@usecase
def troops_collect_status() -> dict[str, Any]:
    """Zwischenstand des Sammel-Modus: eingelesene Seiten, wer fehlt noch."""
    p = _collector.snapshot() if _collector is not None else None
    if p is None:
        return {"laeuft": False, "hinweis": "Kein Sammeln gestartet (troops_collect_start)."}
    return _collect_report(p)


@usecase
def troops_collect_stop() -> dict[str, Any]:
    """Sammel-Modus beenden (wenn der Spieler „fertig“ sagt) und Ergebnis zeigen."""
    if _collector is None:
        return {"hinweis": "Kein Sammeln gestartet."}
    _collector.stop("vom Spieler beendet")
    p = _collector.snapshot()
    assert p is not None
    return _collect_report(p)


@usecase
def truppen_skript() -> dict[str, Any]:
    """Eigenes Schnellleisten-Skript: liest im Spiel mit einem Klick die Truppen aller
    Stammesmitglieder, die ihre Truppen teilen (nur lesen, nichts geht nach außen). Liefert die
    Zeile für die Schnellleiste und die Anleitung. Den Export (JSON) nimmt der Sammel-Modus,
    import_troops_from_clipboard und import_troops automatisch an."""
    return {
        "version": ingame.version(),
        "schnellleiste": ingame.quickbar_code(),
        "schritte": ingame.STEPS,
        "hinweis": ingame.WARNING,
    }


@usecase
def import_troops(text: str) -> dict[str, Any]:
    """Import copied troop tables (own overview or tribe member pages; several may be
    pasted below each other). Counts are totals per village incl. troops outside.

    Nur für kurze Texte, die der Spieler in den Chat eingefügt hat (unverändert übergeben).
    Ganze Truppen-Seiten besser mit import_troops_from_clipboard (kein Abtippen).
    """
    result = troop_collect.import_paste(_store(), text)
    return {
        "imported": len(result.rows),
        "per_player": result.by_owner,
        "not_on_map": [str(v.coord) for v in result.unknown],
    }


@usecase
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


@usecase
def troops_status(hours: float = 24) -> list[dict[str, Any]]:
    """Per member of the own tribes (profile): villages, villages with troop data younger than
    ``hours``, and whether the player is complete. Use it to say who still has to be copied."""
    profile = services.load_profile(settings.world_dir)
    tribes = list(profile.own_tribes) if profile else []
    since = datetime.now(UTC) - timedelta(hours=hours)
    return [
        {"player": p.name, "villages": p.villages, "fresh": p.fresh, "done": p.done}
        for p in troop_collect.status(_store(), tribes, since).players
    ]


# --- profile & operations ---------------------------------------------------------


def _op_path(name: str) -> Path:
    path = settings.world_dir / "ops" / name / "operation.yaml"
    if not path.exists():
        msg = f"Operation {name!r} nicht gefunden - siehe list_operations."
        raise FileNotFoundError(msg)
    return path


@usecase
def get_profile() -> dict[str, Any]:
    """Profil des Spielers (Stamm, Wing, Vorgaben, Strategie-Vorlieben). Immer zuerst lesen."""
    profile = services.load_profile(settings.world_dir)
    if profile is None:
        return {"error": "Kein Profil - zuerst setup_world."}
    return profile.model_dump(mode="json")


@usecase
def save_profile(profile_yaml: str) -> dict[str, Any]:
    """Profil komplett speichern (YAML, alle Felder wie von get_profile).

    Vorher get_profile lesen, nur die gewünschten Werte ändern. Wird vor dem Speichern geprüft.
    """
    try:
        profile = Profile.model_validate(yaml.safe_load(profile_yaml) or {})
    except ValueError as err:
        return {"error": f"Ungültig, nicht gespeichert: {err}"}
    services.save_profile(profile, settings.world_dir)
    return {"gespeichert": True, "profil": profile.model_dump(mode="json")}


@usecase
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


@usecase
def get_operation(name: str) -> dict[str, Any]:
    """operation.yaml einer Operation (zum Ändern) plus review.md und check.md, falls vorhanden."""
    path = _op_path(name)
    out: dict[str, Any] = {"operation_yaml": path.read_text(encoding="utf-8")}
    for extra in ("review.md", "check.md"):
        f = path.parent / extra
        if f.exists():
            out[extra] = f.read_text(encoding="utf-8")
    out["plan_veraltet"] = services.plan_is_outdated(path)
    return out


@usecase
def write_operation(name: str, operation_yaml: str) -> dict[str, Any]:
    """Operation anlegen/überschreiben (YAML, Schema siehe Ressource operation-schema).

    Werte aus dem Profil müssen nicht wiederholt werden. Validiert vor dem Speichern.
    Bestehende Operation ändern: erst get_operation, dann geändertes YAML hier speichern.
    Eine Alternative immer unter neuem Namen anlegen.
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
            if not any(folder.iterdir()):
                folder.rmdir()  # no empty folder for a rejected new operation
        else:
            path.write_text(backup, encoding="utf-8")
        return {"error": f"Ungültig, nicht gespeichert: {err}"}
    return {"name": folder.name, "targets": len(op.targets)}


@app_usecase
def operation_form(name: str | None = None) -> dict[str, Any]:
    """Daten für das Operations-Formular der App: bestehende Operation (als JSON) oder eine
    neue mit den Vorgaben aus dem Profil."""
    profile = services.load_profile(settings.world_dir)
    if name:
        op = services.load_operation(_op_path(name))
        data = op.model_dump(mode="json", exclude={"dsu_links", "discord_messages"})
        return {"name": name, "operation": data, "neu": False}
    defaults = profile.operation_defaults() if profile else {"world": settings.world}
    tomorrow = (datetime.now(_zone()) + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    data = {
        **defaults,
        "name": "",
        "arrival": tomorrow.replace(tzinfo=None).isoformat(),
        "beschreibung": "",
        "targets": [{"coord": "", "offs": 3, "nobles": 4}],
    }
    return {"name": None, "operation": data, "neu": True}


@app_usecase
def save_operation_form(name: str, operation: dict[str, Any]) -> dict[str, Any]:
    """Operation aus dem App-Formular speichern (wird geprüft, ungültig = nicht gespeichert).
    Gespeicherte Werte wie DS-Ultimate-Links und gesendete Nachrichten bleiben erhalten."""
    folder = settings.world_dir / "ops" / services.safe_filename(name.lower())
    existing = folder / "operation.yaml"
    data = dict(operation)
    if existing.exists():
        old = services.load_operation(existing).model_dump(mode="json")
        for key in ("dsu_links", "discord_messages", "gdoc_id", "gdoc_stand", "gdoc_geteilt"):
            data.setdefault(key, old.get(key))
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    result = write_operation(name, text)
    if "error" in result:
        raise ValueError(result["error"])
    return result


@app_usecase
def village_lookup(ref: str) -> dict[str, Any]:
    """Dorf zu einer Koordinate (x|y) oder Dorf-ID: Name, Besitzer, Stamm, Punkte."""
    store = _store()
    v = services.resolve_village(store, ref)
    owner = store.player(v.player_id) if v.player_id else None
    tag = "-"
    if owner and owner.ally_id:
        row = store.conn.execute("SELECT tag FROM allies WHERE id = ?", (owner.ally_id,))
        hit = row.fetchone()
        tag = str(hit["tag"]) if hit else "-"
    return {
        "coord": str(v.coord),
        "name": v.name,
        "points": v.points,
        "owner": owner.name if owner else "Barbar",
        "tribe": tag,
    }


@usecase
def solve_operation(name: str) -> dict[str, Any]:
    """Operation planen; liefert Hinweise und den automatischen Review."""
    path = _op_path(name)
    out = services.solve_operation(_store(), settings, path)
    report = services.check_operation(_store(), settings, path)
    result = {
        "commands": len(out.plan.commands),
        "warnings": out.plan.warnings,
        "check_errors": report.errors,
        "check_warnings": report.warnings,
        "review_md": out.review.read_text(encoding="utf-8"),
    }
    if services.load_operation(path).dsu_links:
        result["achtung"] = (
            "Es gibt schon DS-Ultimate-Pläne. Nach dem Neuberechnen mit "
            "dsu_publish(aktualisieren=true) neu befüllen (Links bleiben gleich)."
        )
    if not report.errors:
        # the doc always mirrors the latest plan: create it on the first plan, then rewrite
        result["google_doc"] = _gdoc_report(name, path)
    return result


@app_usecase
def check_report(name: str, with_dsu: bool = False) -> dict[str, Any]:
    """Automatischer Review als Listen (für die App): Fehler, Hinweise, freie Truppen, ok."""
    path = _op_path(name)
    report = services.check_operation(_store(), settings, path, with_dsu=with_dsu)
    (path.parent / "check.md").write_text(
        report.markdown(services.load_operation(path).name), encoding="utf-8"
    )
    return {
        "fehler": report.errors,
        "hinweise": report.warnings,
        "freie_truppen": report.free,
        "bestanden": report.ok,
        "plan_veraltet": services.plan_is_outdated(path),
    }


@app_usecase
def plan_commands(name: str) -> dict[str, Any]:
    """Alle Befehle des Plans für die App-Tabelle, nach Abschickzeit (Serverzeit)."""
    path = _op_path(name)
    store = _store()
    plan = services.load_plan(path)
    coords = services.plan_coords(store, plan)
    zone = _zone()
    rows = [
        {
            "abschicken": c.send.astimezone(zone).strftime("%d.%m. %H:%M:%S"),
            "ankunft": c.arrival.astimezone(zone).strftime("%d.%m. %H:%M:%S"),
            "spieler": c.note.split(" -> ")[0],
            "von": coords.get(c.source_id, str(c.source_id)),
            "nach": coords.get(c.target_id, str(c.target_id)),
            "art": kind_label(c),
            "einheiten": unit_text(c),
            "wer": who(c),
        }
        for c in sorted(player_commands(plan), key=lambda c: c.send)
    ]
    return {"befehle": rows, "warnungen": plan.warnings}


@usecase
def check_operation(name: str, with_dsu: bool = False) -> str:
    """Automatischer Review (doppelte Zuweisung, Reihenfolge-Regel, freie Truppen, Zeiten).

    with_dsu=True vergleicht zusätzlich die angelegten DS-Ultimate-Pläne mit der Planung.
    """
    path = _op_path(name)
    report = services.check_operation(_store(), settings, path, with_dsu=with_dsu)
    text = report.markdown(services.load_operation(path).name)
    (path.parent / "check.md").write_text(text, encoding="utf-8")
    return text


@usecase
def set_status(
    name: str, status: Literal["draft", "in_review", "approved"], note: str | None = None
) -> str:
    """Review-Status setzen (draft / in_review / approved = von der SF freigegeben)."""
    path = _op_path(name)
    op = services.load_operation(path)
    op = op.model_copy(
        update={
            "status": Status(status),
            "review_notes": [*op.review_notes, *([note] if note else [])],
        }
    )
    services.save_operation(op, path)
    if status == "in_review":
        doc = _gdoc_report(name, path)
        if doc.get("schritte"):
            return (
                f"Status: {status}. Vor dem Review das Google Doc auf den aktuellen Plan "
                f"bringen: {json.dumps(doc, ensure_ascii=False)}"
            )
    return f"Status: {status}"


def _require_doc_for_review(name: str, path: Path) -> None:
    """The SF review always carries the link to the doc with the latest plan."""
    doc = _gdoc_report(name, path)
    if doc.get("schritte"):
        msg = (
            "Das Review enthält den Link zum Google Doc mit dem aktuellen Plan - das Doc ist "
            f"noch nicht so weit ({doc['status']}, geteilt={doc['geteilt']}). Erst diese "
            "Schritte ausführen, dann erneut: " + " | ".join(doc["schritte"])
        )
        raise ValueError(msg)


# --- DS Ultimate ------------------------------------------------------------------


def _kind(fuer: str) -> PlanKind:
    if fuer not in ("ziele", "spieler"):
        msg = "fuer = 'ziele' (SF-Review) oder 'spieler'"
        raise ValueError(msg)
    return "target" if fuer == "ziele" else "player"


def _dsu_action(op: Operation, g: services.DsuGroup, *, alle: bool, update: bool) -> str | None:
    saved = op.dsu_link(g.kind, g.key)
    if g.existing_plan:
        return "in Wing-Plan ergänzen" if saved is None else None
    if update and saved is not None and saved.edit_link:
        return "leeren + neu befüllen"
    if saved is None or alle:
        return "neu anlegen"
    return None


def _register_kept_plans(dsu: DsuClient, op: Operation, path: Path) -> Operation:
    for t in op.targets:
        if t.dsu_plan is None or t.dsu_mode != DsuMode.KEEP or op.dsu_link("target", str(t.coord)):
            continue
        info = dsu.inspect(t.dsu_plan)
        group = services.DsuGroup("target", str(t.coord), info.title, [])
        op = services.add_dsu_link(op, group, info)
    services.save_operation(op, path)
    return op


def _links(op: Operation, kind: PlanKind) -> dict[str, str]:
    return {x.key: x.show_link for x in op.dsu_links if x.kind == kind}


@usecase
def dsu_publish(
    name: str,
    fuer: Literal["ziele", "spieler"] = "ziele",
    aktualisieren: bool = False,
    alle: bool = False,
    bestaetigt: bool = False,
) -> dict[str, Any]:
    """DS-Ultimate-Pläne automatisch anlegen (wie `ap op dsu`): pro Ziel (SF) oder pro Spieler.

    Ohne bestaetigt=true wird nur gezeigt, was passieren würde - dem Spieler zeigen und nach
    seinem OK erneut mit bestaetigt=true aufrufen. aktualisieren=true leert gespeicherte Pläne
    und befüllt sie neu (Links bleiben gleich). alle=true legt auch gespeicherte neu an.
    Ergebnis: Ansehen-Links (nie Bearbeiten-Links teilen).
    """
    path = _op_path(name)
    kind = _kind(fuer)
    store = _store()
    op = services.load_operation(path)
    plan = services.load_plan(path)
    groups = services.dsu_groups(store, op, plan, kind)
    dsu = DsuClient()
    web: DsuWebClient | None = None
    api: DsuApiClient | None = None
    try:
        if kind == "target":
            op = _register_kept_plans(dsu, op, path)
        actions = {g.key: _dsu_action(op, g, alle=alle, update=aktualisieren) for g in groups}
        todo = [g for g in groups if actions[g.key]]
        geplant = [
            {"plan": g.title, "befehle": len(g.commands), "aktion": actions[g.key]} for g in todo
        ]
        if not todo:
            return {
                "hinweis": "Alle Pläne sind schon angelegt (aktualisieren=true = neu befüllen).",
                "links": _links(op, kind),
            }
        if not bestaetigt:
            return {
                "vorschau": geplant,
                "hinweis": "Noch nichts angelegt. Dem Spieler zeigen, nach OK mit "
                "bestaetigt=true erneut aufrufen.",
            }
        web = DsuWebClient()
        api = DsuApiClient(settings.dsu_api_key) if settings.dsu_api_key else None
        ergebnis: list[str] = []
        for g in todo:
            try:
                op, res = services.publish_dsu_group(web, dsu, op, g, update=aktualisieren, api=api)
            except (DsuWebError, DsuApiError, DsuLinkError, httpx.HTTPError) as err:
                ergebnis.append(f"{g.title}: Fehler - {err}")
                continue
            services.save_operation(op, path)
            probleme = "; ".join(res.problems)
            ergebnis.append(
                f"{g.title}: {res.action}" + (f", aber: {probleme}" if probleme else ", geprüft")
            )
    finally:
        dsu.close()
        if web is not None:
            web.close()
        if api is not None:
            api.close()
    weg = "API-Key" if api is not None else "Webseite (ohne API-Key)"
    out: dict[str, Any] = {"ergebnis": ergebnis, "links": _links(op, kind), "angelegt_ueber": weg}
    if op.gdoc_id and not services.plan_is_outdated(path):
        # the doc shows the DS Ultimate links too -> bring it to the latest state
        doc = _gdoc_report(name, path)
        if doc.get("schritte"):
            out["google_doc"] = doc
    return out


@usecase
def dsu_links(name: str) -> dict[str, dict[str, str]]:
    """Gespeicherte Ansehen-Links der DS-Ultimate-Pläne (pro Ziel und pro Spieler)."""
    op = services.load_operation(_op_path(name))
    return {"pro_ziel": _links(op, "target"), "pro_spieler": _links(op, "player")}


@usecase
def dsu_save_link(name: str, key: str, link: str) -> dict[str, Any]:
    """Einen von Hand angelegten DS-Ultimate-Plan prüfen und speichern.

    key = Ziel (x|y) oder Spielername; link = Bearbeiten-Link aus der Adressleiste.
    """
    path = _op_path(name)
    op = services.load_operation(path)
    plan = services.load_plan(path)
    kind: PlanKind = "target" if "|" in key else "player"
    group = next((g for g in services.dsu_groups(_store(), op, plan, kind) if g.key == key), None)
    if group is None:
        return {"error": f"{key} kommt im Plan nicht vor."}
    dsu = DsuClient()
    try:
        info = dsu.inspect(link)
    finally:
        dsu.close()
    problems = services.check_dsu_plan(op, group, info)
    if problems:
        return {"gespeichert": False, "probleme": problems}
    services.save_operation(services.add_dsu_link(op, group, info), path)
    return {"gespeichert": True}


@usecase
def workbench_text(
    name: str, fuer: Literal["ziele", "spieler"] = "ziele", key: str | None = None
) -> dict[str, Any]:
    """Notfall-Weg, falls dsu_publish nicht klappt (wie `ap op dsu --manuell`).

    Liefert pro Plan Titel und Workbench-Text. Spieler: Link „neuer Plan“ öffnen, Titel setzen,
    Reiter Import/Export → „Import Workbench“ → Text einfügen → Importieren, dann den
    Bearbeiten-Link aus der Adressleiste hier nennen (dsu_save_link).
    key = nur dieses Ziel (x|y) bzw. diesen Spieler.
    """
    path = _op_path(name)
    op = services.load_operation(path)
    groups = services.dsu_groups(_store(), op, services.load_plan(path), _kind(fuer))
    return {
        "neuer_plan_link": services.dsu_create_url(op.world),
        "plaene": [
            {
                "key": g.key,
                "titel": g.title,
                "angelegt": op.dsu_link(g.kind, g.key) is not None,
                "workbench": g.workbench,
            }
            for g in groups
            if key is None or g.key == key
        ],
    }


# --- outputs ----------------------------------------------------------------------


@usecase
def aktion_message(names: list[str]) -> dict[str, Any]:
    """aktion.md für die Stammesführung (wie `ap op aktion`): Discord-fertig, mit Bearbeiten-Links.

    names = eine oder mehrere Operationen (z.B. Adeln + Fakes). Liefert die Nachrichten
    (je < 2000 Zeichen) zum Kopieren und speichert sie in aktion.md im Datenordner.
    """
    store = _store()
    ops: list[AktionOp] = []
    hinweise: list[str] = []
    for name in names:
        path = _op_path(name)
        if services.plan_is_outdated(path):
            hinweise.append(f"{name}: Planung ist älter als die Operation - erst solve_operation.")
        op = services.load_operation(path)
        ops.append(AktionOp(op, services.load_plan(path), services.target_infos(store, op)))
    messages = aktion_messages(ops, settings.timezone)
    Path("aktion.md").write_text(aktion_markdown(ops, settings.timezone), encoding="utf-8")
    return {"nachrichten": messages, "hinweise": hinweise}


@usecase
def returns(name: str | None = None) -> str:
    """Rückkehrzeiten: wer ist wann wieder daheim? (Markdown-Tabelle)

    Mit name: eine Operation. Ohne: alle noch kommenden Rückkehrer aus freigegebenen
    Operationen der Welt.
    """
    store = _store()
    if name:
        path = _op_path(name)
        op = services.load_operation(path)
        out = services.write_returns(store, op, services.load_plan(path), path, settings.timezone)
        return out.read_text(encoding="utf-8")
    zone = _zone()
    rows = services.upcoming_returns(store, settings.world_dir / "ops", datetime.now(zone))
    lines = [
        "| zurück | frühestens | Spieler | Dorf | Was | Ziel | Operation |",
        "|---|---|---|---|---|---|---|",
    ]
    for op_name, t in rows:
        c = t.cmd
        src, dst = store.village(c.source_id), store.village(c.target_id)
        back = t.back or c.arrival
        early = t.back_earliest or back
        lines.append(
            f"| **{back.astimezone(zone):%d.%m. %H:%M:%S}** | "
            f"{early.astimezone(zone):%d.%m. %H:%M:%S} | {c.note.split(' -> ')[0]} | "
            f"{_cell(src.coord if src else c.source_id)} | {kind_label(c)} | "
            f"{_cell(dst.coord if dst else c.target_id)} | {op_name} |"
        )
    if not rows:
        return "Keine freigegebene Operation mit Rückkehrern."
    return "\n".join(lines)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _units(units: dict[str, int]) -> dict[Unit, int]:
    return {Unit(k): int(v) for k, v in units.items()}


@usecase
def simulate_train(
    name: str,
    target: str,
    deff_package: dict[str, int] | None = None,
    wall: int = 20,
    wall_ags: int | None = None,
    known_deff: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Wie viel Deff blockt diesen Train? Kampf-Näherung Welle für Welle (wie `ap op sim`).

    target 'x|y'; deff_package z.B. {"spear": 1000, "sword": 1000}; known_deff = bekannte Deff
    im Dorf (dann Ergebnis Welle für Welle). Näherung - im Spiel-Simulator gegenprüfen.
    """
    store = _store()
    plan = services.load_plan(_op_path(name))
    waves, notes = services.train_waves(store, plan, Coord.parse(target), settings.timezone)
    if not waves:
        return {"error": "Keine Angriffe mit bekannten Truppen auf dieses Ziel.", "notes": notes}
    cfg = store.world_config()
    package = _units(deff_package or {"spear": 1000, "sword": 1000})
    w_ags = wall if wall_ags is None else wall_ags
    out: dict[str, Any] = {"hinweise": notes, "wellen": len(waves)}
    table: dict[str, dict[str, str]] = {}
    for luck in (-0.25, 0.0, 0.25):
        row = {}
        for sure, label in ((True, "sicher (≤2 AGs)"), (False, "wahrscheinlich (≤3 AGs)")):
            k = battle.deff_needed(
                cfg, waves, package, wall=wall, wall_ags=w_ags, luck=luck, sure=sure
            )
            row[label] = "> 500 Pakete" if k is None else f"{k:.2f} Pakete"
        table[f"Glück {luck:+.0%}"] = row
    out["deff_pakete_noetig"] = table
    if known_deff:
        res = battle.run_train(cfg, waves, _units(known_deff), wall=wall, wall_ags=w_ags)
        out["wellen_verlauf"] = [
            {"welle": label, "angreifer_gewinnt": won, "deff_uebrig": pop}
            for label, won, pop in res.rows
        ]
        out["ags_durch"] = f"{res.ags_through}/{res.ags_total}"
        out["geblockt"] = battle.blocked(res.ags_through)
    return out


def _gdoc_steps(name: str, state: services.GdocState, gdoc_id: str | None) -> list[str]:
    """Connector steps that bring the Google Doc to the latest plan (empty = nothing to do)."""
    file_id = f"'{gdoc_id}'" if gdoc_id else "<id>"
    share = (
        f"Drive-Connector share_file(fileId={file_id}, "
        "permissionId='anyoneWithLink', role='reader') - jeder mit dem Link darf ansehen."
    )
    if state.status == "fehlt":
        return [
            f"operation_doc(name='{name}') → html",
            "Drive-Connector create_file(title=<titel>, textContent=<html>, "
            "contentMimeType='text/html') → id des neuen Docs",
            share,
            f"operation_doc(name='{name}', gdoc_id=<id>, geteilt=true) - merkt Doc, Stand und "
            "Freigabe.",
            "Ohne Google-Drive-Connector: operation_doc(open_in_browser=true), der Spieler fügt "
            "es in docs.new ein und stellt „Jeder mit dem Link: Betrachter“ ein; dann "
            "operation_doc(gdoc_id=<Link>, geteilt=true).",
        ]
    steps: list[str] = []
    if state.status == "veraltet":
        steps += [
            f"Google-Docs-Connector read_doc('{gdoc_id}') → endIndex des letzten Elements von "
            "tabs[0].documentTab.body.content (nur diese Zahl).",
            f"operation_doc(name='{name}', end_index=<endIndex>) → requests",
            f"Google-Docs-Connector update_doc(documentId='{gdoc_id}', requests=<requests>) - "
            "unverändert und in dieser Reihenfolge; nie ein neues Doc anlegen.",
        ]
    if not state.geteilt:
        steps.append(share)
    if steps:
        flags = ", ".join(
            f
            for f, on in (
                ("geschrieben=true", state.status == "veraltet"),
                ("geteilt=true", not state.geteilt),
            )
            if on
        )
        steps.append(f"operation_doc(name='{name}', {flags}) - merkt den neuen Stand.")
    return steps


def _gdoc_report(name: str, path: Path) -> dict[str, Any]:
    op = services.load_operation(path)
    plan = services.load_plan(path)
    state = services.gdoc_state(_store(), op, plan, settings.timezone)
    out: dict[str, Any] = {"status": state.status, "geteilt": state.geteilt}
    if state.view_link:
        out["link"] = state.view_link
    steps = _gdoc_steps(name, state, op.gdoc_id)
    if steps:
        out["schritte"] = steps
    return out


@usecase
def operation_doc(
    name: str,
    gdoc_id: str | None = None,
    end_index: int | None = None,
    open_in_browser: bool = False,
    geschrieben: bool = False,
    geteilt: bool | None = None,
) -> dict[str, Any]:
    """Spieler-Dokument = Google Doc mit dem aktuellsten Plan (siehe Prompt `google-doc`).

    - ohne Parameter: HTML für ein neues Doc (Drive-Connector create_file, text/html) bzw.
      Status des Docs mit den nötigen Schritten (`google_doc`)
    - gdoc_id: ID oder Link des angelegten Google Docs merken (Stand = aktueller Plan)
    - end_index: bestehendes Doc neu befüllen → requests für update_doc (Link bleibt gleich)
    - geschrieben=true: nach update_doc - das Doc zeigt jetzt den aktuellen Plan
    - geteilt=true: nach share_file (anyoneWithLink, reader) - jeder mit Link kann ansehen
    - open_in_browser: ohne Google-Connector - öffnet das Dokument im Browser; der Spieler
      kopiert es mit Strg+A, Strg+C in ein neues Google Doc (docs.new), Format bleibt erhalten.
    """
    path = _op_path(name)
    op = services.load_operation(path)
    if gdoc_id is not None or geschrieben or geteilt is not None:
        if services.plan_is_outdated(path):
            msg = "Planung ist älter als die Operation - erst solve_operation, dann das Doc."
            raise ValueError(msg)
        doc_id = services.parse_gdoc_id(gdoc_id) if gdoc_id is not None else None
        if doc_id is None and not op.gdoc_id:
            msg = "Noch kein Google Doc gemerkt - erst gdoc_id angeben."
            raise ValueError(msg)
        op = services.mark_gdoc(_store(), path, settings.timezone, doc_id=doc_id, geteilt=geteilt)
        assert op.gdoc_id is not None
        return {
            "gespeichert": services.gdoc_link(op.gdoc_id),
            "google_doc": _gdoc_report(name, path),
        }
    store = _store()
    plan = services.load_plan(path)
    out: dict[str, Any] = {"titel": op.name, "gdoc_id": op.gdoc_id}
    if services.plan_is_outdated(path):
        out["hinweis"] = "Planung ist älter als die Operation - erst solve_operation."
    if end_index is not None:
        out["requests"] = services.build_doc_update(store, op, plan, settings.timezone, end_index)
    else:
        html = services.build_operation_doc(store, op, plan, settings.timezone)
        doc = services.doc_path(path)
        doc.write_text(html, encoding="utf-8")
        if open_in_browser:
            webbrowser.open(doc.resolve().as_uri())
            out["geoeffnet"] = (
                "Im Browser: Strg+A, Strg+C → docs.new öffnen → Strg+V. Danach den Link des "
                "Docs hier nennen (operation_doc mit gdoc_id)."
            )
        else:
            out["html"] = html
    out["google_doc"] = _gdoc_report(name, path)
    return out


# --- Discord ----------------------------------------------------------------------


@usecase
def discord_message(
    name: str, art: Literal["review", "spieler", "dm", "thread"] = "review"
) -> list[str]:
    """Discord-Nachricht(en) zum Kopieren: 'review' (SF, pro Ziel), 'spieler' (Ankündigung)
    oder 'dm' (jeder Spieler seine Befehle). Je < 2000 Zeichen."""
    path = _op_path(name)
    op, plan = services.load_operation(path), services.load_plan(path)
    if art in ("dm", "thread"):
        texts = discord_sync.dm_texts(_store(), op, plan, tz=settings.timezone)
        return [p for text in texts.values() for p in split_discord(text)]
    if art == "spieler":
        _require_final(op)
        cfg = discord_sync.load_config(settings.world_dir)
        ping = discord_sync.role_ping(cfg) or " ".join(f"@{t}" for t in _tribe_tags())
        enemies = enemy_tribes(services.target_infos(_store(), op))
        text = discord_players(
            op,
            plan,
            settings.timezone,
            enemies=enemies,
            ping=ping,
            unassigned=discord_sync.unassigned_players(plan, cfg),
        )
    else:
        _require_doc_for_review(name, path)
        text = discord_review(op, plan, services.target_infos(_store(), op), settings.timezone)
    return split_discord(text)


def _tribe_tags() -> list[str]:
    return services.tribe_tags(settings.world_dir)


def _require_final(op: Operation) -> None:
    """The public announcement (with the call for extra fakes) is only for a final plan."""
    if op.status != Status.APPROVED:
        msg = (
            "Die öffentliche Ankündigung geht erst beim finalen Plan raus - die SF hat die "
            f"Operation noch nicht freigegeben (Status: {op.status.value}). Nach der Freigabe: "
            "set_status(status='approved')."
        )
        raise ValueError(msg)


DISCORD_TOKEN_STEPS = [
    "discord.com/developers/applications öffnen → „New Application“ → Name z.B. „AP-Planer“.",
    "Links „Bot“ → „Reset Token“ → Token kopieren. Unter „Privileged Gateway Intents“ "
    "„Server Members Intent“ einschalten → Speichern.",
    "Claude Desktop: Einstellungen → Erweiterungen bzw. Plugins → AP-Planner → "
    "Discord-Bot-Token einfügen → Speichern. Den Token nie in den Chat schreiben.",
    "Neuen Chat öffnen und „Discord weiter einrichten“ sagen: Der Einladungslink für den Bot "
    "wird dann automatisch erzeugt.",
]


def _discord_invite() -> str | None:
    app_id = application_id(settings.discord_bot_token)
    return invite_url(app_id) if app_id else None


def _choose_guild(
    guilds: list[dict[str, str]], server: str | None, saved: str | None
) -> dict[str, str] | None:
    if server:
        return pick_by_name(guilds, server)
    if len(guilds) == 1:
        return guilds[0]
    return next((g for g in guilds if g["id"] == saved), None)


@usecase
def discord_setup(
    server: str | None = None,
    review_channel: str | None = None,
    announce_channel: str | None = None,
    commands_channel: str | None = None,
) -> dict[str, Any]:
    """Discord einrichten - ohne IDs kopieren. Server und Kanäle per Name (oder ID).

    Ohne Angaben: zeigt die Server des Bots und deren Textkanäle zur Auswahl. review_channel =
    Kanal für das SF-Review, announce_channel = Kanal für die Ankündigung an die Spieler,
    commands_channel = Kanal, in dem jeder Spieler einen privaten Thread mit seinen Befehlen
    bekommt (empfohlen statt Direktnachrichten; optional).
    Der Bot läuft nicht dauerhaft: er sendet nur, wenn hier im Chat discord_send ausgelöst wird.
    """
    if not settings.discord_bot_token:
        return {"error": "Noch kein Bot-Token.", "anleitung": DISCORD_TOKEN_STEPS}
    client = DiscordClient(settings.discord_bot_token)
    try:
        bot = client.me()
        guilds = client.guilds()
        if not guilds:
            return {
                "bot": bot.get("username"),
                "hinweis": "Der Bot ist noch auf keinem Server. Diesen Link öffnen, Server "
                "wählen, „Autorisieren“, dann nochmal discord_setup.",
                "einladen": _discord_invite(),
            }
        cfg = discord_sync.load_config(settings.world_dir)
        guild = _choose_guild(guilds, server, cfg.guild_id)
        if guild is None:
            return {"server_zur_auswahl": [g["name"] for g in guilds]}
        channels = client.text_channels(guild["id"])
        match = discord_sync.match_roles(client.roles(guild["id"]), _tribe_tags())
    except DiscordError as err:
        return {"error": str(err), "anleitung": DISCORD_TOKEN_STEPS}
    finally:
        client.close()
    kanaele = dict(cfg.kanaele) if guild["id"] == cfg.guild_id else {}
    probleme: list[str] = []
    refs = (
        ("review", review_channel),
        ("ankuendigung", announce_channel),
        ("befehle", commands_channel),
    )
    for alias, ref in refs:
        if not ref:
            continue
        chan = pick_by_name(channels, ref)
        if chan is None:
            probleme.append(f"Kanal {ref!r} nicht gefunden oder nicht eindeutig.")
        else:
            kanaele[alias] = chan["id"]
    cfg = cfg.model_copy(
        update={"guild_id": guild["id"], "kanaele": kanaele, "rollen": match.found}
    )
    discord_sync.save_config(cfg, settings.world_dir)
    names = {c["id"]: c["name"] for c in channels}
    out: dict[str, Any] = {
        "bot": bot.get("username"),
        "server": guild["name"],
        "kanaele": {alias: names.get(cid, cid) for alias, cid in kanaele.items()},
        "rollen": discord_sync.role_report(match),
        "probleme": probleme,
    }
    if missing := [a for a in ("review", "ankuendigung") if a not in kanaele]:
        out["fehlt"] = missing
        out["kanaele_zur_auswahl"] = [c["name"] for c in channels]
    else:
        out["naechster_schritt"] = "Spieler zuordnen: discord_members, dann discord_assign."
    if "befehle" not in kanaele:
        out["tipp"] = (
            "Optional: commands_channel setzen - dann bekommt jeder Spieler einen privaten "
            "Thread statt einer Direktnachricht (klappt auch bei gesperrten DMs, die SF sieht "
            "alles an einem Ort, wenn ihre Rolle „Threads verwalten“ darf)."
        )
    return out


@usecase
def discord_members() -> dict[str, Any]:
    """Discord-Mitglieder des Servers mit Vorschlag pro Stammesmitglied (für discord_assign)."""
    cfg = discord_sync.load_config(settings.world_dir)
    if not cfg.guild_id:
        return {"error": "Erst discord_setup mit server_id."}
    profile = services.load_profile(settings.world_dir)
    names = discord_sync.own_players(_store(), profile.own_tribes if profile else [])
    client = DiscordClient(settings.discord_bot_token)
    try:
        members = client.members(cfg.guild_id)
    except DiscordError as err:
        return {
            "error": str(err),
            "tipp": "Im Discord-Entwicklerportal beim Bot „Server Members Intent“ einschalten.",
        }
    finally:
        client.close()
    by_id = {m.id: m for m in members}
    vorschlaege: dict[str, Any] = {}
    for n in names:
        assigned = cfg.spieler.get(n, [])
        if assigned:
            vorschlaege[n] = {
                "zugeordnet": [
                    {"id": i, "name": by_id[i].label if i in by_id else "(nicht auf dem Server)"}
                    for i in assigned
                ]
            }
            continue
        guess = discord_sync.suggest_member(n, members)
        vorschlaege[n] = {
            "zugeordnet": [],
            "vorschlag": {"id": guess.id, "name": guess.label} if guess else None,
        }
    return {
        "stammesmitglieder": vorschlaege,
        "discord_mitglieder": [{"id": m.id, "name": m.label} for m in members],
    }


@usecase
def discord_assign(mapping: dict[str, list[str] | str]) -> dict[str, Any]:
    """DS-Spieler → Discord-User-ID(s) speichern, z.B. {"Name": "1234"} oder bei Accounts,
    die mehrere Leute spielen, {"Name": ["1234", "5678"]}. Alle Personen kommen in den
    privaten Thread bzw. bekommen je eine Direktnachricht. Ersetzt die bisherige Zuordnung
    dieses Spielers; leere Liste = Zuordnung löschen."""
    cfg = discord_sync.load_config(settings.world_dir)
    spieler = dict(cfg.spieler)
    for name, ids in mapping.items():
        users = user_ids(ids)
        if users:
            spieler[name] = users
        else:
            spieler.pop(name, None)
    cfg = cfg.model_copy(update={"spieler": spieler})
    discord_sync.save_config(cfg, settings.world_dir)
    return {
        "zugeordnet": len(cfg.spieler),
        "geaendert": {n: cfg.spieler.get(n, []) for n in mapping},
    }


@usecase
def discord_send(
    name: str,
    art: Literal["review", "spieler", "dm", "thread"] = "review",
    nur: list[str] | None = None,
    bestaetigt: bool = False,
) -> dict[str, Any]:
    """Nachricht per Discord-Bot senden (schon gesendete werden bearbeitet, nicht doppelt).

    art: 'review' (SF-Kanal), 'spieler' (öffentliche Ankündigung beim finalen Plan, Status
    approved: in den Kanal mit den privaten Threads, sonst 'ankuendigung'; Grunddaten ohne
    Ziele, Aufruf zu zusätzlichen Fakes, erwähnt die Discord-Rollen von Stamm + Wing),
    'thread' (jeder Spieler seine Befehle in seinem privaten Thread - empfohlen, wenn der Kanal
    'befehle' eingerichtet ist) oder 'dm' (Direktnachricht). Ohne bestaetigt=true nur Vorschau
    (wer bekommt was) - nach OK des Spielers erneut mit bestaetigt=true.
    nur = bei 'thread'/'dm' nur an diese Spieler.
    """
    if not settings.discord_bot_token:
        return {"error": "Noch kein Bot-Token.", "anleitung": DISCORD_TOKEN_STEPS}
    path = _op_path(name)
    if art == "review":
        _require_doc_for_review(name, path)
    store = _store()
    op, plan = services.load_operation(path), services.load_plan(path)
    cfg = discord_sync.load_config(settings.world_dir)
    rollen: dict[str, object] | None = None
    if art == "spieler":
        _require_final(op)
        # read the roles fresh each time: new or renamed roles are picked up, nothing hard-coded
        client = DiscordClient(settings.discord_bot_token)
        try:
            cfg, match = discord_sync.refresh_roles(client, cfg, _tribe_tags())
        finally:
            client.close()
        discord_sync.save_config(cfg, settings.world_dir)
        rollen = discord_sync.role_report(match)
    prepared = discord_sync.prepare(store, op, plan, cfg, art, tz=settings.timezone, only=nur)
    vorschau = [
        {
            "an": {"thread": f"Thread {m.key}", "dm": f"DM {m.key}"}.get(m.kind, f"#{m.key}"),
            "teile": len(m.parts),
            "aktion": discord_sync.planned_action(op, m),
        }
        for m in prepared.messages
    ]
    todo = [m for m in prepared.messages if discord_sync.planned_action(op, m) != "unverändert"]
    if not todo or not bestaetigt:
        return {
            "vorschau": vorschau,
            **({"rollen": rollen} if rollen is not None else {}),
            **({"text": prepared.messages[0].parts} if art == "spieler" and todo else {}),
            "fehlt": prepared.missing,
            "hinweis": "Alles schon aktuell gesendet."
            if not todo
            else "Noch nichts gesendet. Nach OK mit bestaetigt=true erneut aufrufen.",
        }
    client = DiscordClient(settings.discord_bot_token)
    ergebnis: list[str] = []
    try:
        for msg in todo:
            try:
                op, action = discord_sync.deliver(client, op, msg)
            except DiscordError as err:
                ergebnis.append(f"{msg.key}: Fehler - {err}")
                continue
            services.save_operation(op, path)
            ergebnis.append(f"{msg.key}: {action}")
    finally:
        client.close()
        if art == "thread":
            discord_sync.save_config(discord_sync.remember_threads(cfg, op), settings.world_dir)
    return {"ergebnis": ergebnis, "fehlt": prepared.missing}


# --- progress & reminders (DS Ultimate API key) -----------------------------------


def _progress(name: str) -> tuple[Operation, Plan, list[services.PlayerProgress], list[str]]:
    if not settings.dsu_api_key:
        msg = (
            "Dafür braucht es einen DS-Ultimate-API-Key (Claude Desktop: Einstellungen → "
            "Erweiterungen bzw. Plugins → AP-Planner)."
        )
        raise RuntimeError(msg)
    path = _op_path(name)
    op, plan = services.load_operation(path), services.load_plan(path)
    api = DsuApiClient(settings.dsu_api_key)
    try:
        progress, notes = services.dsu_progress(api, op, plan, datetime.now(UTC))
    finally:
        api.close()
    return op, plan, progress, notes


@usecase
def dsu_progress(name: str) -> dict[str, Any]:
    """Live-Stand einer laufenden Operation: wer hat in DS Ultimate „verschickt“ abgehakt?

    Pro Spieler: abgehakt/gesamt, überfällig (Zeit vorbei, nicht abgehakt) und der nächste
    offene Befehl. Braucht den DS-Ultimate-API-Key. Zählt nur, wenn die Spieler abhaken.
    """
    _, plan, progress, notes = _progress(name)
    zone = _zone()
    coords = services.plan_coords(_store(), plan)

    def short(c: PlannedCommand) -> str:
        src = coords.get(c.source_id, c.source_id)
        dst = coords.get(c.target_id, c.target_id)
        return f"{c.send.astimezone(zone):%H:%M:%S} {src} → {dst} ({kind_label(c)})"

    rows = sorted(progress, key=lambda p: (-len(p.overdue), p.total - p.sent, p.player.lower()))
    return {
        "gesamt": f"{sum(p.sent for p in progress)}/{sum(p.total for p in progress)} abgehakt",
        "spieler": [
            {
                "spieler": p.player,
                "abgehakt": f"{p.sent}/{p.total}",
                "ueberfaellig": [short(c) for c in p.overdue],
                "naechster": short(p.upcoming[0]) if p.upcoming else None,
            }
            for p in rows
        ],
        "hinweise": notes,
    }


@usecase
def discord_remind(
    name: str, minuten: float = 15, nur: list[str] | None = None, bestaetigt: bool = False
) -> dict[str, Any]:
    """Erinnerung an Spieler, die noch nicht abgehakt haben (Thread oder Direktnachricht).

    Erinnert, wer etwas Überfälliges hat oder in den nächsten `minuten` schicken muss. Braucht
    DS-Ultimate-API-Key und Discord-Bot. Ohne bestaetigt=true nur Vorschau.
    """
    if not settings.discord_bot_token:
        return {"error": "Noch kein Bot-Token.", "anleitung": DISCORD_TOKEN_STEPS}
    op, plan, progress, notes = _progress(name)
    now = datetime.now(UTC)
    coords = services.plan_coords(_store(), plan)
    cfg = discord_sync.load_config(settings.world_dir)
    due = [
        p
        for p in progress
        if discord_sync.reminder_due(p, now, minuten) and (not nur or p.player in nur)
    ]
    msgs: list[discord_sync.Outgoing] = []
    fehlt: list[str] = []
    for p in due:
        text = discord_sync.reminder_text(
            op, p, coords=coords, tz=settings.timezone, now=now, minutes=minuten
        )
        player_msgs = discord_sync.to_player(cfg, p.player, split_discord(text))
        if not player_msgs:
            fehlt.append(f"{p.player}: keine Discord-Zuordnung")
        msgs += player_msgs
    if not msgs or not bestaetigt:
        return {
            "wuerde_erinnern": sorted({m.player for m in msgs}),
            "fehlt": fehlt,
            "hinweise": notes,
            "beispiel": msgs[0].parts[0] if msgs else None,
            "hinweis": "Niemand zu erinnern."
            if not msgs
            else "Noch nichts gesendet. Nach OK mit bestaetigt=true erneut aufrufen.",
        }
    client = DiscordClient(settings.discord_bot_token)
    ergebnis: list[str] = []
    threads = dict(cfg.threads)
    try:
        for msg in msgs:
            try:
                channel = discord_sync.post(client, msg)
            except DiscordError as err:
                ergebnis.append(f"{msg.key}: Fehler - {err}")
                continue
            if msg.kind == "thread":
                threads[msg.key] = channel
            ergebnis.append(f"{msg.key}: erinnert")
    finally:
        client.close()
        discord_sync.save_config(cfg.model_copy(update={"threads": threads}), settings.world_dir)
    return {"ergebnis": ergebnis, "fehlt": fehlt}


# --- settings of the desktop app ---------------------------------------------------

_SECRET_KEYS = {"discord_bot_token": "AP_DISCORD_BOT_TOKEN", "dsu_api_key": "AP_DSU_API_KEY"}


@app_usecase
def app_settings() -> dict[str, Any]:
    """Welche Zugänge sind eingetragen (nur ja/nein, nie die Werte)?"""
    return {
        "datenordner": str(Path.cwd()),
        "welt": settings.world or None,
        "discord_bot_token": bool(settings.discord_bot_token),
        "dsu_api_key": bool(settings.dsu_api_key),
        "google": google_status(),
    }


@app_usecase
def save_app_settings(
    discord_bot_token: str | None = None, dsu_api_key: str | None = None
) -> dict[str, Any]:
    """Discord-Bot-Token bzw. DS-Ultimate-API-Key speichern (lokal in .env im Datenordner).
    Leerer Text = löschen, nicht angegeben = unverändert."""
    values = {
        env: value.strip()
        for key, env in _SECRET_KEYS.items()
        if (value := {"discord_bot_token": discord_bot_token, "dsu_api_key": dsu_api_key}[key])
        is not None
    }
    if values:
        services.write_env(values)
        for env in values:
            os.environ.pop(env, None)
        _reload_settings()
    return app_settings()


# --- Google Docs with the app's own login (desktop app) ----------------------------


def _google() -> GoogleClient:
    oauth = OAuthClient(
        settings.google_client_id or builtin.GOOGLE_CLIENT_ID,
        settings.google_client_secret or builtin.GOOGLE_CLIENT_SECRET,
    )
    return GoogleClient(oauth, app_home() / "google_token.json")


@app_usecase
def google_status() -> dict[str, Any]:
    """Ist die App bei Google angemeldet (für das Google Doc)?"""
    client = _google()
    return {"eingebaut": bool(client.oauth.client_id), "angemeldet": client.logged_in}


@app_usecase
def google_login() -> dict[str, Any]:
    """Mit Google anmelden: öffnet den Browser, wartet bis zu 5 Minuten auf die Anmeldung.
    Zugriff nur auf Dateien, die der Planer selbst anlegt (drive.file)."""
    _google().login()
    return google_status()


@app_usecase
def google_logout() -> dict[str, Any]:
    """Google-Anmeldung auf diesem Rechner löschen."""
    _google().logout()
    return google_status()


@app_usecase
def google_doc_sync(name: str) -> dict[str, Any]:
    """Google Doc auf den aktuellen Plan bringen: beim ersten Mal anlegen und für alle mit
    Link lesbar freigeben, danach dasselbe Doc neu befüllen (Link bleibt gleich)."""
    path = _op_path(name)
    if services.plan_is_outdated(path):
        msg = "Planung ist älter als die Operation - erst neu rechnen, dann das Doc."
        raise ValueError(msg)
    store = _store()
    op, plan = services.load_operation(path), services.load_plan(path)
    state = services.gdoc_state(store, op, plan, settings.timezone)
    client = _google()
    done: list[str] = []
    doc_id = op.gdoc_id
    if state.status == "fehlt":
        html = services.build_operation_doc(store, op, plan, settings.timezone)
        services.doc_path(path).write_text(html, encoding="utf-8")
        doc_id = client.create_doc_from_html(op.name, html)
        services.mark_gdoc(store, path, settings.timezone, doc_id=doc_id)
        done.append("angelegt")
    elif state.status == "veraltet" and doc_id:
        end = client.doc_end_index(doc_id)
        client.batch_update(
            doc_id, services.build_doc_update(store, op, plan, settings.timezone, end)
        )
        services.mark_gdoc(store, path, settings.timezone)
        done.append("neu befüllt")
    if doc_id and not services.load_operation(path).gdoc_geteilt:
        client.share_anyone_reader(doc_id)
        services.mark_gdoc(store, path, settings.timezone, geteilt=True)
        done.append("freigegeben (jeder mit Link: ansehen)")
    assert doc_id is not None
    return {
        "aktion": done or ["schon aktuell"],
        "link": services.gdoc_view_link(doc_id),
        "bearbeiten": services.gdoc_link(doc_id),
    }


# --- guided setup -----------------------------------------------------------------

GOOGLE_STEPS = (
    "Für das Spieler-Dokument als Google Doc (wird nach dem ersten Plan automatisch angelegt, "
    "für alle mit Link lesbar freigegeben und im Review verlinkt): Claude Desktop → "
    "Einstellungen → Connectors → Google Drive → Verbinden (mit dem Google-Konto, in dem "
    "die Docs liegen sollen). Ohne Connector geht es auch: "
    "operation_doc(open_in_browser=true) öffnet das Dokument im Browser, dann Strg+A, Strg+C "
    "und in ein neues Google Doc (docs.new) einfügen."
)


def _discord_check() -> dict[str, Any]:
    if not settings.discord_bot_token:
        return {
            "status": "optional - nicht eingerichtet",
            "wozu": "Der Bot postet SF-Review und Ankündigung und schickt jedem Spieler seine "
            "Befehle per Direktnachricht. Er läuft nicht dauerhaft, sondern sendet nur, wenn du "
            "es hier im Chat auslöst. Ohne Bot schreibt Claude die Texte zum Kopieren.",
            "anleitung": DISCORD_TOKEN_STEPS,
        }
    client = DiscordClient(settings.discord_bot_token)
    try:
        bot = client.me()
        guilds = client.guilds()
    except DiscordError as err:
        return {"status": "Fehler", "fehler": str(err), "anleitung": DISCORD_TOKEN_STEPS}
    finally:
        client.close()
    out: dict[str, Any] = {"bot": bot.get("username"), "server": [g["name"] for g in guilds]}
    cfg = discord_sync.load_config(settings.world_dir) if settings.world else None
    if not guilds:
        out["status"] = "Bot noch auf keinem Server"
        out["einladen"] = _discord_invite()
    elif cfg is None or not cfg.guild_id or not {"review", "ankuendigung"} <= set(cfg.kanaele):
        out["status"] = "Kanäle fehlen → discord_setup (zeigt die Kanäle zur Auswahl)"
    else:
        profile = services.load_profile(settings.world_dir)
        names = discord_sync.own_players(_store(), profile.own_tribes if profile else [])
        done = sum(1 for n in names if n in cfg.spieler)
        out["spieler_zugeordnet"] = f"{done}/{len(names)}"
        out["befehle_an_spieler"] = (
            "private Threads"
            if "befehle" in cfg.kanaele
            else "Direktnachrichten (Tipp: "
            "Kanal für private Threads mit discord_setup(commands_channel=…) einrichten)"
        )
        out["status"] = "fertig" if done == len(names) else "Spieler zuordnen → discord_members"
    return out


@usecase
def setup_check() -> dict[str, Any]:
    """Einrichtungs-Check: Was ist fertig, was fehlt noch, wie geht es? (Prompt `einrichtung`)

    Prüft Welt/Profil, Truppen, Zwischenablage, DS Ultimate, Discord-Bot und nennt die
    Connectoren in Claude Desktop.
    """
    out: dict[str, Any] = {"datenordner": str(Path.cwd())}
    if not settings.world:
        out["1_welt"] = "fehlt → Welt, Stamm-Tag und Wing-Tags erfragen, dann setup_world"
    else:
        profile = services.load_profile(settings.world_dir)
        out["1_welt"] = (
            f"{settings.world}, Stamm {', '.join(profile.own_tribes) if profile else '?'}"
        )
        out["2_vorgaben"] = (
            "Profil da (anpassen: Prompt `profil-einrichten`)" if profile else "fehlt"
        )
        out["3_truppen"] = f"{len(_store().troops())} Dörfer eingelesen"
    out["zwischenablage"] = (
        "ok" if troop_collect.read_clipboard() is not None else "nicht lesbar → Text einfügen"
    )
    out["ds_ultimate"] = (
        {
            "status": "API-Key eingetragen",
            "kann": "Pläne über die offizielle Schnittstelle anlegen, Live-Stand wer "
            "abgehakt hat (dsu_progress), Erinnerungen (discord_remind).",
        }
        if settings.dsu_api_key
        else {
            "status": "fertig ohne Key - Pläne werden über die normale Seite angelegt",
            "optional": "Mit eigenem DS-Ultimate-API-Key (von den DS-Ultimate-Admins, in "
            "Einstellungen → Erweiterungen bzw. Plugins → AP-Planner eintragen, nie in den "
            "Chat): stabileres Anlegen, Live-Stand wer abgehakt hat, Erinnerungen.",
        }
    )
    out["discord"] = _discord_check()
    out["google_docs"] = GOOGLE_STEPS
    out["claude_desktop"] = [
        "Erweiterung AP-Planner: an (sonst gäbe es diesen Check nicht).",
        "Bei der ersten Tool-Frage „Immer erlauben“ wählen, dann fragt Claude nicht jedes Mal.",
        "Sonst ist kein weiterer Connector nötig. Websuche braucht der Planer nicht.",
    ]
    return out


@usecase
def help_docs(
    thema: Literal[
        "claude-desktop",
        "ablauf",
        "operation",
        "profil",
        "regeln",
        "discord",
        "google",
        "desktop-app",
    ],
) -> str:
    """Handbuch-Kapitel (Markdown): Installation, Ablauf, Felder von Operation und Profil,
    Regeln & Datenquellen, Discord-Bot, Google Doc."""
    path = DOCS_DIR / f"{thema}.md"
    if not path.exists():
        return f"Kapitel {thema!r} ist in dieser Installation nicht enthalten."
    return path.read_text(encoding="utf-8")
