"""Command-line interface: ``uv run ap --help``."""

import json
import sys
import time
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from ap_planner import discord_sync, ingame, services, troop_collect
from ap_planner.config import Settings
from ap_planner.discord_bot import DiscordClient, DiscordError
from ap_planner.domain import battle
from ap_planner.dsu import DsuClient, DsuLinkError
from ap_planner.dsu_api import DsuApiClient, DsuApiError
from ap_planner.dsu_web import DsuWebClient, DsuWebError
from ap_planner.export.aktion import AktionOp, aktion_markdown
from ap_planner.export.announce import (
    discord_players,
    discord_review,
    enemy_tribes,
    split_discord,
)
from ap_planner.export.review import kind_label, safe_filename
from ap_planner.ingest.store import WorldStore
from ap_planner.models.discord import user_ids
from ap_planner.models.map import Coord
from ap_planner.models.operation import DsuMode, Operation, PlanKind, Status
from ap_planner.models.plan import Plan
from ap_planner.models.profile import Profile
from ap_planner.models.world import Unit

app = typer.Typer(
    no_args_is_help=True, help="KI-gestützter Angriffsplaner für Die Stämme (kein Botting)."
)
troops_app = typer.Typer(no_args_is_help=True, help="Truppen importieren und anzeigen.")
app.add_typer(troops_app, name="troops")
op_app = typer.Typer(no_args_is_help=True, help="Operationen planen, prüfen, exportieren.")
app.add_typer(op_app, name="op")
discord_app = typer.Typer(no_args_is_help=True, help="Discord-Bot einrichten (Kanäle, Spieler).")
app.add_typer(discord_app, name="discord")
console = Console()

WorldOpt = Annotated[str | None, typer.Option("--world", "-w", help="e.g. de260")]


def _settings(world: str | None) -> Settings:
    settings = Settings(world=world) if world else Settings()
    if not settings.world:
        raise typer.BadParameter(
            "Keine Welt gesetzt. Einmal `uv run ap init` ausführen oder --world de260 angeben."
        )
    return settings


def _tags(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


@app.command()
def init(
    *,
    world: Annotated[str, typer.Option(prompt="Welt (z.B. de260)")],
    stamm: Annotated[str, typer.Option(prompt="Dein Stamm-Tag (mehrere mit Komma)")],
    wing: Annotated[
        str, typer.Option(prompt="Verbündete / Wing-Tags (mit Komma, leer = keine)")
    ] = "",
    spieler: Annotated[str, typer.Option(prompt="Dein Spielername (optional)")] = "",
    server: str = "die-staemme.de",
    force: Annotated[bool, typer.Option(help="bestehendes Profil überschreiben")] = False,
) -> None:
    """Ersteinrichtung: Welt merken, Weltdaten laden, Stamm-Profil anlegen."""
    services.write_env({"AP_WORLD": world, "AP_SERVER": server})
    settings = Settings(world=world, server=server)
    console.print(f"[bold]1/3[/] .env geschrieben (AP_WORLD={world}).")
    services.sync_world(settings)
    console.print(f"[bold]2/3[/] Weltdaten von {settings.world_url} geladen.")
    store = WorldStore.open(settings)
    for tag in [*_tags(stamm), *_tags(wing)]:
        ally = store.ally_by_tag(tag)
        if ally is None:
            console.print(f"[yellow]  Stamm '{tag}' gibt es auf {world} nicht - bitte prüfen.[/]")
        else:
            console.print(
                f"  {tag}: {ally.name}, {ally.members} Mitglieder, {ally.villages} Dörfer"
            )
    existing = services.load_profile(settings.world_dir)
    if existing is not None and not force:
        console.print(
            f"[bold]3/3[/] Profil existiert schon: {services.profile_path(settings.world_dir)} "
            "(mit --force überschreiben)."
        )
    else:
        profile = Profile(
            world=world, server=server, player=spieler,
            own_tribes=_tags(stamm), allied_tribes=_tags(wing),
        )  # fmt: skip
        path = services.save_profile(profile, settings.world_dir)
        console.print(f"[bold]3/3[/] Profil angelegt: {path}")
    console.print(
        "\n[green]Fertig![/] Nächste Schritte:\n"
        "  1. Truppen kopieren → stamm.txt → [bold]uv run ap troops import stamm.txt[/]\n"
        "  2. In Claude Code: [bold]/profil-einrichten[/] (Vorlieben festlegen)\n"
        "  3. In Claude Code: [bold]/neue-operation[/]"
    )


@app.command()
def profil(world: WorldOpt = None) -> None:
    """Stamm-Profil anzeigen (Vorgaben für alle Operationen)."""
    settings = _settings(world)
    path = services.profile_path(settings.world_dir)
    if not path.exists():
        raise typer.BadParameter("Noch kein Profil - `uv run ap init` ausführen.")
    console.print(f"[dim]{path}[/]")
    print(path.read_text(encoding="utf-8"))


@app.command()
def sync(world: WorldOpt = None, force: bool = False) -> None:
    """Weltdaten laden (Einstellungen + Karte, höchstens 1x pro Stunde)."""
    settings = _settings(world)
    for r in services.sync_world(settings, force=force):
        state = "downloaded" if r.downloaded else "cached"
        console.print(f"  {r.name:<16} {state}")
    console.print(f"[green]World {settings.world} ready:[/] {settings.db_path}")


@app.command()
def info(world: WorldOpt = None) -> None:
    """Welt-Einstellungen anzeigen, die fürs Planen wichtig sind."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    summary = services.world_summary(store)
    table = Table(title=f"World {summary.world}", show_header=False)
    for key, value in summary.model_dump(exclude={"minutes_per_field"}).items():
        table.add_row(key, str(value))
    for unit, mpf in summary.minutes_per_field.items():
        table.add_row(f"  {unit}", f"{mpf:g} min/field")
    console.print(table)


@app.command()
def travel(
    source: Annotated[str, typer.Argument(help="village id or x|y")],
    target: Annotated[str, typer.Argument(help="village id or x|y")],
    unit: Unit = Unit.RAM,
    arrival: Annotated[
        str | None, typer.Option(help="local arrival, e.g. '2026-11-07 06:00:00'")
    ] = None,
    world: WorldOpt = None,
) -> None:
    """Entfernung, Laufzeit und Abschickzeit zwischen zwei Dörfern."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    arr = (
        datetime.fromisoformat(arrival).replace(tzinfo=ZoneInfo(settings.timezone))
        if arrival
        else None
    )
    t = services.travel_info(store, settings, source, target, unit, arrival=arr)
    console.print(
        f"{t.source.name} ({t.source.coord}) -> {t.target.name} ({t.target.coord})\n"
        f"distance {t.distance:.2f}  {unit.value}: {timedelta(seconds=t.travel_seconds)}"
    )
    if t.send is not None:
        night = "  [red]NIGHT BONUS[/]" if t.arrival_in_night_bonus else ""
        console.print(
            f"send {t.send.astimezone(ZoneInfo(settings.timezone)):%Y-%m-%d %H:%M:%S}{night}"
        )


@app.command()
def villages(
    player: str | None = None,
    ally: str | None = None,
    center: Annotated[str | None, typer.Option(help="x|y")] = None,
    radius: float = 10.0,
    world: WorldOpt = None,
) -> None:
    """Dörfer eines Spielers, eines Stamms oder um eine Koordinate auflisten."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    if player:
        p = store.player_by_name(player)
        if p is None:
            raise typer.BadParameter(f"unknown player {player}")
        result = store.villages_of_player(p.id)
    elif ally:
        a = store.ally_by_tag(ally)
        if a is None:
            raise typer.BadParameter(f"unknown tribe {ally}")
        result = store.villages_of_ally(a.id)
    elif center:
        result = store.villages_in_radius(Coord.parse(center), radius)
    else:
        raise typer.BadParameter("give --player, --ally or --center")
    table = Table("id", "coord", "name", "points", "player_id")
    for v in sorted(result, key=lambda v: (v.y, v.x)):
        table.add_row(str(v.id), str(v.coord), v.name, str(v.points), str(v.player_id))
    console.print(table)


@troops_app.command("import")
def troops_import(
    files: Annotated[
        list[Path] | None, typer.Argument(help="text files; omit to read from stdin")
    ] = None,
    world: WorldOpt = None,
) -> None:
    """Import copied troop tables (own overview or member pages), several pasted below each other.

    Owners are resolved from the map via coordinates, so no player name is needed.
    """
    text = "\n".join(f.read_text(encoding="utf-8") for f in files) if files else sys.stdin.read()
    store = WorldStore.open(_settings(world))
    result = troop_collect.import_paste(store, text)
    console.print(f"[green]{len(result.rows)} villages imported.[/]")
    for name, count in sorted(result.by_owner.items()):
        console.print(f"  {name}: {count}")
    for v in result.unknown:
        console.print(f"[yellow]  not on map (run `ap sync`?): {v.name} ({v.coord})[/]")


@troops_app.command("skript")
def troops_script(
    kopieren: Annotated[bool, typer.Option(help="Zeile in die Zwischenablage")] = True,
) -> None:
    """Schnellleisten-Skript, das die Truppen aller Stammesmitglieder mit einem Klick ausliest.

    Das Skript läuft im Spiel im Browser des Spielers, liest nur und schickt nichts nach außen.
    Den Export einfach kopieren: `ap troops sammeln` bzw. `ap troops import` nehmen ihn an.
    """
    code = ingame.quickbar_code()
    console.print(f"[bold]ap-planner Truppen-Skript v{ingame.version()}[/]")
    for i, step in enumerate(ingame.STEPS, 1):
        console.print(f"{i}. {step}")
    console.print(f"[yellow]{ingame.WARNING}[/]")
    if kopieren and services.copy_to_clipboard(code):
        console.print("[green]Zeile für die Schnellleiste ist in der Zwischenablage.[/]")
    else:
        print(code)


def _max_age_h(settings: Settings) -> int:
    profile = services.load_profile(settings.world_dir)
    return profile.max_troop_age_hours if profile else 24


@troops_app.command("show")
def troops_show(world: WorldOpt = None) -> None:
    """Importierte Truppen anzeigen (mit Alter der Daten)."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    cfg = store.world_config()
    max_age = timedelta(hours=_max_age_h(settings))
    now = datetime.now(UTC)
    units = [u for u in cfg.units if u.value != "militia"]
    table = Table("player", "coord", "name", *(u.value for u in units), "out", "in", "Alter")
    for vt, _source, captured in store.troops():
        at = datetime.fromisoformat(captured)
        age = troop_collect.age_text(at, now)
        table.add_row(
            services.owner_name(store, vt.village_id),
            str(vt.coord),
            vt.name,
            *(str(vt.units.get(u, 0)) for u in units),
            str(vt.outgoing),
            f"[red]{vt.incoming}[/]" if vt.incoming else "0",
            f"[yellow]{age}[/]" if now - at > max_age else age,
        )
    console.print(table)


def _tribes(settings: Settings, stamm: list[str] | None) -> list[str]:
    if stamm:
        return stamm
    profile = services.load_profile(settings.world_dir)
    if profile is None or not profile.own_tribes:
        raise typer.BadParameter("Kein eigener Stamm im Profil: --stamm RAK angeben.")
    return list(profile.own_tribes)


StammOpt = Annotated[
    list[str] | None, typer.Option("--stamm", help="Stamm-Kürzel (Standard: eigene laut Profil)")
]


def _print_collect_status(status: troop_collect.CollectStatus, *, short: bool) -> None:
    done, missing = status.done, status.missing
    console.print(f"[bold]{len(done)}/{len(status.players)} Spieler fertig.[/]")
    if not missing:
        return
    if short:
        names = ", ".join(f"{p.name} ({p.fresh}/{p.villages})" for p in missing)
        console.print(f"Fehlen noch: {names}")
        return
    now = datetime.now(UTC)
    table = Table("Spieler", "Dörfer", "aktuell", "älteste Daten")
    for p in missing:
        table.add_row(
            p.name,
            str(p.villages),
            str(p.fresh),
            troop_collect.age_text(p.oldest, now) if p.oldest else "[red]fehlt[/]",
        )
    console.print(table)


@troops_app.command("status")
def troops_status(
    stunden: Annotated[
        float | None,
        typer.Option("--stunden", help="Daten jünger als so viele Stunden zählen (Profil)"),
    ] = None,
    stamm: StammOpt = None,
    world: WorldOpt = None,
) -> None:
    """Wer im Stamm hat aktuelle Truppendaten, wer fehlt noch?"""
    settings = _settings(world)
    store = WorldStore.open(settings)
    hours = stunden if stunden is not None else _max_age_h(settings)
    since = datetime.now(UTC) - timedelta(hours=hours)
    console.print(f"Aktuell = jünger als {hours:g} h.")
    _print_collect_status(troop_collect.status(store, _tribes(settings, stamm), since), short=False)


@troops_app.command("sammeln")
def troops_collect(
    stunden: Annotated[
        float,
        typer.Option("--stunden", help="Daten jünger als so viele Stunden zählen schon als fertig"),
    ] = 0,
    stamm: StammOpt = None,
    world: WorldOpt = None,
) -> None:
    """Zwischenablage beobachten: jede kopierte Truppen-Seite wird sofort importiert.

    Im Spiel pro Spieler die Truppen-Seite öffnen, Strg+A, Strg+C - fertig. Das Tool zeigt,
    wer noch fehlt. Beenden mit Strg+C.
    """
    settings = _settings(world)
    store = WorldStore.open(settings)
    tribes = _tribes(settings, stamm)
    since = datetime.now(UTC) - timedelta(hours=stunden)
    last = troop_collect.read_clipboard()
    if last is None:
        console.print(
            "[red]Kein Zugriff auf die Zwischenablage (Linux: xclip oder wl-clipboard fehlt).[/]"
        )
        console.print("Ersatz: Text in eine Datei kopieren und `ap troops import datei.txt`.")
        raise typer.Exit(1)
    log = (
        settings.world_dir
        / "truppen"
        / f"{datetime.now(ZoneInfo(settings.timezone)):%Y-%m-%d_%H%M}.txt"
    )
    console.print(f"Sammeln für {', '.join(tribes)}. Truppen-Seiten kopieren, Strg+C hier beendet.")
    _print_collect_status(troop_collect.status(store, tribes, since), short=True)
    try:
        while True:
            time.sleep(0.7)
            text = troop_collect.read_clipboard()
            if not text or text == last:
                continue
            last = text
            if not troop_collect.looks_like_troops(text):
                continue
            result = troop_collect.import_paste(store, text)
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n\n")
            owners = ", ".join(f"{n} ({c})" for n, c in sorted(result.by_owner.items()))
            console.print(f"[green]+ {len(result.rows)} Dörfer:[/] {owners}")
            for v in result.unknown:
                console.print(f"[yellow]  nicht auf der Karte: {v.name} ({v.coord})[/]")
            status = troop_collect.status(store, tribes, since)
            _print_collect_status(status, short=True)
            if not status.missing:
                console.print("[bold green]Alle Spieler da.[/]")
                break
    except KeyboardInterrupt:
        console.print()
    if log.exists():
        console.print(f"Kopien gespeichert in {log}")


OpPath = Annotated[Path, typer.Argument(help="path to operation.yaml")]


OP_TEMPLATE = """\
# Neue Operation - Werte, die hier fehlen, kommen aus data/{world}/profil.yaml.
# Vollständiges Schema: docs/operation.md
name: {name}
arrival: "{arrival}"   # Serverzeit
targets:
  # - coord: "500|500"
  #   offs: 2            # volle Offs (fusion: true = mehrere kleine zusammen)
  #   nobles: 4          # AGs, dürfen aus verschiedenen Dörfern kommen
  #   fakes: 0
  #   support: {{min_pop: 3000}}   # Flexdeff nach dem letzten AG
  #   note: "Hauptziel"
"""


@op_app.command("neu")
def op_new(
    name: str,
    ankunft: Annotated[str, typer.Option(help="z.B. '2026-11-10 08:15:00'")],
    world: WorldOpt = None,
) -> None:
    """Neue Operation anlegen: data/<welt>/ops/<name>/operation.yaml (Vorlage)."""
    settings = _settings(world)
    datetime.fromisoformat(ankunft)  # validate early
    folder = settings.world_dir / "ops" / safe_filename(name.lower())
    path = folder / "operation.yaml"
    if path.exists():
        raise typer.BadParameter(f"{path} existiert schon.")
    folder.mkdir(parents=True)
    path.write_text(
        OP_TEMPLATE.format(world=settings.world, name=name, arrival=ankunft), encoding="utf-8"
    )
    console.print(f"Angelegt: {path}")


@op_app.command("solve")
def op_solve(path: OpPath, world: WorldOpt = None) -> None:
    """Operation planen: review.md, Workbench-Texte pro Ziel (SF) und pro Spieler, Kurz-Review."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    out = services.solve_operation(store, settings, path)
    console.print(f"[green]{len(out.plan.commands)} Befehle geplant.[/]")
    report = services.check_operation(store, settings, path)
    color = "red" if report.errors else "green"
    console.print(
        f"[{color}]Automatischer Review: {len(report.errors)} Fehler, "
        f"{len(report.warnings)} Hinweise[/] - Details: `ap op check`"
    )
    if services.load_operation(path).dsu_links:
        console.print(
            "[red]Achtung: Es gibt schon DS-Ultimate-Pläne zu dieser Operation. Nach dem "
            "Neuberechnen sind sie evtl. veraltet - mit `ap op dsu --alle` neu anlegen.[/]"
        )
    for w in out.plan.warnings:
        console.print(f"[yellow]- {w}[/]")
    console.print(f"Review (SF):  {out.review}")
    console.print(f"Gesamt:       {out.total}")
    console.print(f"Pro Ziel (SF, {len(out.target_files)}):     {out.folder / 'ziele'}")
    console.print(f"Pro Spieler ({len(out.player_files)}): {out.folder / 'spieler'}")
    state = services.gdoc_state(store, services.load_operation(path), out.plan, settings.timezone)
    if state.status != "aktuell":
        console.print(
            f"Google Doc {state.status} - mit /google-doc anlegen bzw. neu befüllen "
            "(gleicher Link), damit es den aktuellen Plan zeigt."
        )


@op_app.command("status")
def op_status(path: OpPath, status: Status, note: str | None = None) -> None:
    """Review-Status setzen (draft / in_review / approved), optional mit Notiz."""
    op = services.load_operation(path)
    op = op.model_copy(
        update={"status": status, "review_notes": [*op.review_notes, *([note] if note else [])]}
    )
    services.save_operation(op, path)
    console.print(f"Status: {status.value}")


@op_app.command("dsu")
def op_dsu(
    path: OpPath,
    fuer: Annotated[str, typer.Option(help="ziele (SF-Review) oder spieler")] = "ziele",
    alle: Annotated[
        bool, typer.Option(help="auch Pläne mit gespeichertem Link neu anlegen")
    ] = False,
    aktualisieren: Annotated[
        bool,
        typer.Option(
            help="gespeicherte Pläne leeren und neu befüllen (Links bleiben gleich), "
            "fehlende neu anlegen"
        ),
    ] = False,
    manuell: Annotated[
        bool, typer.Option(help="Pläne von Hand im Browser anlegen (alter Ablauf)")
    ] = False,
    ja: Annotated[bool, typer.Option("--ja", "-y", help="ohne Rückfrage")] = False,
    world: WorldOpt = None,
) -> None:
    """DS-Ultimate-Pläne anlegen: pro Ziel (für die SF) oder pro Spieler.

    Standard: Das Tool legt die Pläne selbst bei DS Ultimate an, setzt den Titel,
    importiert die Angriffe und prüft das Ergebnis. Mit --manuell öffnet es stattdessen
    den Browser und legt den Workbench-Text in die Zwischenablage.
    """
    if fuer not in ("ziele", "spieler"):
        raise typer.BadParameter("--fuer ziele oder --fuer spieler")
    if manuell and aktualisieren:
        raise typer.BadParameter("--aktualisieren geht nur automatisch (ohne --manuell)")
    settings = _settings(world)
    store = WorldStore.open(settings)
    op = services.load_operation(path)
    plan = services.load_plan(path)
    kind: PlanKind = "target" if fuer == "ziele" else "player"
    groups = services.dsu_groups(store, op, plan, kind)
    dsu = DsuClient()
    if kind == "target":
        op = _register_kept_plans(dsu, op, path)
    try:
        if manuell:
            todo = [g for g in groups if alle or op.dsu_link(g.kind, g.key) is None]
            console.print(f"{len(todo)} von {len(groups)} Plänen anzulegen ({fuer}).")
            op = _dsu_manual(dsu, op, todo, path)
        else:
            op = _dsu_auto(
                dsu, op, groups, path, alle=alle, update=aktualisieren, yes=ja,
                api_key=settings.dsu_api_key,
            )  # fmt: skip
    finally:
        dsu.close()
    _print_links(op, kind)


def _dsu_manual(
    dsu: DsuClient, op: Operation, todo: list[services.DsuGroup], path: Path
) -> Operation:
    """Old flow: the player creates each plan in the browser, the tool checks the link."""
    create_url = services.dsu_create_url(op.world)
    for n, g in enumerate(todo, 1):
        console.rule(f"[bold]{n}/{len(todo)}: {g.title}[/] ({len(g.commands)} Befehle)")
        _to_clipboard(g.workbench, path.parent / "_zwischenablage.txt")
        if g.existing_plan:
            op = _import_into_existing(dsu, op, g, path)
            continue
        webbrowser.open(create_url)
        console.print(
            "1. Im Browser ist ein neuer Plan offen.\n"
            f"2. [bold]Titel setzen:[/] {g.title}\n"
            "3. Bei [bold]Import Workbench[/] einfügen (Strg+V) und importieren.\n"
            "   (Reiter [bold]Import/Export[/] → Feld „Import Workbench“ → grüner Knopf "
            "[bold]Importieren[/])\n"
            "4. Den Link aus der [bold]Adressleiste[/] kopieren (…/edit/…).\n"
            "   [dim]k = Workbench-Text nochmal in die Zwischenablage[/]"
        )
        while True:
            link = typer.prompt(
                "Link (k = Text kopieren, leer = überspringen, q = abbrechen)", default=""
            ).strip()
            if link.lower() == "q":
                raise typer.Exit
            if link.lower() == "k":
                _to_clipboard(g.workbench, path.parent / "_zwischenablage.txt")
                continue
            if not link:
                break
            try:
                info = dsu.inspect(link)
            except (DsuLinkError, httpx.HTTPError) as err:
                console.print(f"[red]{err}[/]")
                continue
            problems = services.check_dsu_plan(op, g, info)
            console.print(f"Plan {info.plan_id}: '{info.title}', {info.item_count} Angriffe.")
            if problems:
                for p in problems:
                    console.print(f"[red]- {p}[/]")
                console.print("Bitte korrigieren und den Link nochmal einfügen.")
                continue
            op = services.add_dsu_link(op, g, info)
            services.save_operation(op, path)
            console.print("[green]Geprüft und gespeichert.[/]")
            break
    return op


def _dsu_action(op: Operation, g: services.DsuGroup, *, alle: bool, update: bool) -> str | None:
    """What the automatic run does with one plan (None = nothing to do)."""
    saved = op.dsu_link(g.kind, g.key)
    if g.existing_plan:
        # Wing plans are never cleared: adding again would duplicate our attacks.
        return "in Wing-Plan ergänzen" if saved is None else None
    if update and saved is not None and saved.edit_link:
        return "leeren + neu befüllen"
    if saved is None or alle:
        return "neu anlegen"
    return None


def _dsu_auto(
    dsu: DsuClient,
    op: Operation,
    groups: list[services.DsuGroup],
    path: Path,
    *,
    alle: bool,
    update: bool,
    yes: bool,
    api_key: str = "",
) -> Operation:
    """Create/refill the plans at DS Ultimate without browser clicks (API if key is set)."""
    actions = {g.key: _dsu_action(op, g, alle=alle, update=update) for g in groups}
    todo = [g for g in groups if actions[g.key]]
    if update and any(g.existing_plan and op.dsu_link(g.kind, g.key) for g in groups):
        console.print(
            "[yellow]Wing-Pläne werden nicht geleert. Was dort nicht mehr passt, zeigt "
            "`ap op check --dsu`.[/]"
        )
    if not todo:
        console.print("Alle Pläne sind schon angelegt. (--aktualisieren = neu befüllen)")
        return op
    table = Table("Plan", "Befehle", "Aktion")
    for g in todo:
        table.add_row(g.title, str(len(g.commands)), actions[g.key])
    console.print(table)
    if not yes and not typer.confirm(f"{len(todo)} Pläne bei DS Ultimate bearbeiten?"):
        raise typer.Exit
    web = DsuWebClient()
    api = DsuApiClient(api_key) if api_key else None
    console.print(f"[dim]Weg: {'DS-Ultimate-API' if api else 'Webseite (ohne API-Key)'}[/]")
    failed = 0
    try:
        for n, g in enumerate(todo, 1):
            console.print(f"[bold]{n}/{len(todo)}[/] {g.title} …", end=" ")
            try:
                op, res = services.publish_dsu_group(web, dsu, op, g, update=update, api=api)
            except (DsuWebError, DsuApiError, DsuLinkError, httpx.HTTPError) as err:
                failed += 1
                console.print(f"[red]Fehler: {err}[/]")
                continue
            services.save_operation(op, path)
            failed += _print_publish(res)
    finally:
        web.close()
        if api is not None:
            api.close()
    if failed:
        console.print(
            f"[yellow]{failed} Plan/Pläne mit Problemen. Nochmal mit --aktualisieren versuchen "
            "oder --manuell.[/]"
        )
    return op


def _print_publish(res: services.DsuPublishResult) -> int:
    """Print the outcome of one plan; returns 1 if it has problems."""
    if not res.problems:
        console.print(f"[green]{res.action}, geprüft.[/]")
        return 0
    console.print(f"[red]{res.action}, aber:[/]")
    for p in res.problems:
        console.print(f"[red]  - {p}[/]")
    return 1


def _register_kept_plans(dsu: DsuClient, op: Operation, path: Path) -> Operation:
    """Targets with dsu_mode keep: the existing plan IS the target plan - store its link."""
    for t in op.targets:
        if t.dsu_plan is None or t.dsu_mode != DsuMode.KEEP or op.dsu_link("target", str(t.coord)):
            continue
        info = dsu.inspect(t.dsu_plan)
        group = services.DsuGroup("target", str(t.coord), info.title, [])
        op = services.add_dsu_link(op, group, info)
        console.print(f"Ziel {t.coord}: bestehender Plan '{info.title}' übernommen.")
    services.save_operation(op, path)
    return op


def _import_into_existing(
    dsu: DsuClient, op: Operation, g: services.DsuGroup, path: Path
) -> Operation:
    """Import our attacks into an existing (wing) plan and verify the count."""
    assert g.existing_plan is not None
    before = dsu.inspect(g.existing_plan)
    webbrowser.open(g.existing_plan)
    console.print(
        f"Bestehender Plan ist offen: [bold]{before.title}[/] ({before.item_count} Angriffe).\n"
        "1. Reiter [bold]Import/Export[/] → „Import Workbench“ → Strg+V → "
        "[bold]Importieren[/]\n"
        "2. Danach hier Enter drücken - das Tool prüft den Plan.\n"
        "   [dim]k = Text nochmal kopieren, s = überspringen, q = abbrechen[/]"
    )
    while True:
        answer = typer.prompt("Enter = prüfen", default="", show_default=False).strip().lower()
        if answer == "q":
            raise typer.Exit
        if answer == "s":
            return op
        if answer == "k":
            _to_clipboard(g.workbench, path.parent / "_zwischenablage.txt")
            continue
        try:
            after = dsu.inspect(g.existing_plan)
        except (DsuLinkError, httpx.HTTPError) as err:
            console.print(f"[red]{err}[/]")
            continue
        problems = services.check_dsu_plan(op, g, after, baseline=before.item_count)
        console.print(f"Plan {after.plan_id}: {after.item_count} Angriffe.")
        if problems:
            for p in problems:
                console.print(f"[red]- {p}[/]")
            continue
        op = services.add_dsu_link(op, g, after)
        services.save_operation(op, path)
        console.print("[green]Geprüft und gespeichert.[/]")
        return op


def _to_clipboard(text: str, fallback: Path) -> None:
    if services.copy_to_clipboard(text):
        console.print("Workbench-Text ist in der [green]Zwischenablage[/].")
    else:
        fallback.write_text(text, encoding="utf-8")
        console.print(f"[yellow]Zwischenablage nicht verfügbar - Text steht in {fallback}[/]")


def _print_links(op: Operation, kind: PlanKind) -> None:
    links = [x for x in op.dsu_links if x.kind == kind]
    if not links:
        return
    console.rule("Ansehen-Links")
    for x in links:
        # soft_wrap: never break the URL into two lines (a click would open half a link)
        console.print(f"{x.key}: [link={x.show_link}]{x.show_link}[/link]", soft_wrap=True)


@op_app.command("aktion")
def op_aktion(
    paths: Annotated[list[Path], typer.Argument(help="eine oder mehrere operation.yaml")],
    datei: Annotated[Path, typer.Option(help="Zieldatei")] = Path("aktion.md"),
    kopieren: Annotated[bool, typer.Option(help="erste Nachricht in die Zwischenablage")] = False,
    world: WorldOpt = None,
) -> None:
    """aktion.md schreiben: Discord-fertig, immer gleiches Format, Bearbeiten-Links.

    Pro Operation: Kopf (Name, Doc), Pläne pro Dorf, Pläne pro Spieler. Mehrere Operationen
    (z.B. Adeln + Fakes) landen nacheinander in derselben Datei. Nachrichten < 2000 Zeichen.
    """
    settings = _settings(world)
    store = WorldStore.open(settings)
    ops: list[AktionOp] = []
    for path in paths:
        if services.plan_is_outdated(path):
            console.print(f"[yellow]{path}: plan.json ist älter als operation.yaml.[/]")
        op = services.load_operation(path)
        ops.append(AktionOp(op, services.load_plan(path), services.target_infos(store, op)))
    text = aktion_markdown(ops, settings.timezone)
    datei.write_text(text, encoding="utf-8")
    print(text)
    console.print(f"[dim]Gespeichert in {datei}[/]")
    if kopieren:
        _to_clipboard(text.split("\n\n✂️")[0], datei)


@op_app.command("rueckkehr")
def op_rueckkehr(
    paths: Annotated[
        list[Path] | None, typer.Argument(help="operation.yaml (leer = alle freigegebenen)")
    ] = None,
    world: WorldOpt = None,
) -> None:
    """Rückkehrzeiten von Offs, AGs und Fakes (sortiert: wer ist wann wieder daheim?).

    Mit Pfad: rueckkehr.md + rueckkehr.json der Operation neu schreiben (macht `op solve`
    automatisch). Ohne Pfad: alle noch kommenden Rückkehrer aus freigegebenen bzw. an die
    Spieler verteilten Operationen der Welt in data/<welt>/rueckkehr.md.
    """
    settings = _settings(world)
    store = WorldStore.open(settings)
    zone = ZoneInfo(settings.timezone)
    if paths:
        for path in paths:
            op = services.load_operation(path)
            out = services.write_returns(
                store, op, services.load_plan(path), path, settings.timezone
            )
            print(out.read_text(encoding="utf-8"))
            console.print(f"[dim]Gespeichert in {out} (+ rueckkehr.json)[/]")
        return
    ops_dir = settings.world_dir / "ops"
    rows = services.upcoming_returns(store, ops_dir, datetime.now(zone))
    lines = [
        f"# Rückkehr - alle laufenden Operationen ({settings.world})",
        "",
        "| zurück | frühestens | Spieler | Dorf | Was | Ziel | Operation |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, t in rows:
        c = t.cmd
        src, dst = store.village(c.source_id), store.village(c.target_id)
        src_c = str(src.coord if src else c.source_id).replace("|", "\\|")
        dst_c = str(dst.coord if dst else c.target_id).replace("|", "\\|")
        back = t.back or c.arrival
        early = t.back_earliest or back
        lines.append(
            f"| **{back.astimezone(zone):%d.%m. %H:%M:%S}** | "
            f"{early.astimezone(zone):%d.%m. %H:%M:%S} | {c.note.split(' -> ')[0]} | "
            f"{src_c} | {kind_label(c)} | {dst_c} | {name} |"
        )
    if not rows:
        lines.append("| - | - | - | - | - | - | keine freigegebene Operation mit Rückkehrern |")
    text = "\n".join(lines) + "\n"
    out = settings.world_dir / "rueckkehr.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    console.print(f"[dim]Gespeichert in {out}[/]")


def _units(text: str) -> dict[Unit, int]:
    """ "spear=1000,sword=1000" -> {Unit.SPEAR: 1000, Unit.SWORD: 1000}."""
    out: dict[Unit, int] = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        name, _, n = part.partition("=")
        try:
            out[Unit(name.strip())] = int(n)
        except ValueError as e:
            msg = f"Einheiten wie spear=1000,sword=1000 angeben (nicht {part!r})"
            raise typer.BadParameter(msg) from e
    return out


@op_app.command("sim")
def op_sim(
    path: OpPath,
    ziel: Annotated[str, typer.Option(help="Zieldorf x|y")],
    deff: Annotated[
        str, typer.Option(help="ein Deff-Paket, z.B. spear=1000,sword=1000,heavy=100")
    ] = "spear=1000,sword=1000",
    wall: Annotated[int, typer.Option(help="Wallstufe beim ersten Einschlag")] = 20,
    wall_ags: Annotated[
        int | None, typer.Option(help="Wallstufe, wenn die AGs landen (Standard: wie --wall)")
    ] = None,
    vorhanden: Annotated[
        str | None, typer.Option(help="bekannte Deff im Dorf: Kampf Welle für Welle zeigen")
    ] = None,
    world: WorldOpt = None,
) -> None:
    """Wie viel Deff blockt diesen Train? Kampf-Simulation Welle für Welle (Näherung).

    Rechnet mit Moral, Nachtbonus und Wall. Ergebnis: Anzahl Deff-Pakete, ab der zu wenige
    AGs durchkommen (sicher: höchstens 2 AGs, weil ein AG max. 35 Zustimmung senkt).
    """
    settings = _settings(world)
    store = WorldStore.open(settings)
    plan = services.load_plan(path)
    waves, notes = services.train_waves(store, plan, Coord.parse(ziel), settings.timezone)
    for n in notes:
        console.print(f"[yellow]- {n}[/]")
    if not waves:
        console.print("[red]Keine Angriffe mit bekannten Truppen auf dieses Ziel.[/]")
        raise typer.Exit(1)
    cfg = store.world_config()
    package = _units(deff)
    w_ags = wall if wall_ags is None else wall_ags
    ags = sum(1 for w in waves if w.is_noble)
    console.print(
        f"Train auf {ziel}: {len(waves)} Wellen, {ags} AGs · Wall {wall} (AGs: {w_ags}) · "
        f"Nachtbonus: {'ja' if any(w.night for w in waves) else 'nein'} · "
        f"Moral: {min(w.morale for w in waves):.0%}-{max(w.morale for w in waves):.0%}"
    )
    pkg_text = ", ".join(f"{n} {u.value}" for u, n in package.items())
    table = Table("Glück Angreifer", "sicher geblockt (≤2 AGs)", "wahrscheinlich (≤3 AGs)")
    for luck in (-0.25, 0.0, 0.25):
        cells = []
        for sure in (True, False):
            k = battle.deff_needed(
                cfg, waves, package, wall=wall, wall_ags=w_ags, luck=luck, sure=sure
            )
            cells.append("> 500 Pakete" if k is None else f"{k:.2f} Pakete")
        table.add_row(f"{luck:+.0%}", *cells)
    console.print(f"Deff-Paket: {pkg_text}")
    console.print(table)
    if vorhanden:
        res = battle.run_train(cfg, waves, _units(vorhanden), wall=wall, wall_ags=w_ags)
        t = Table("Welle", "Angreifer gewinnt", "Deff übrig (Plätze)")
        for label, won, pop in res.rows:
            t.add_row(label, "ja" if won else "[red]nein[/]", f"{pop:,}".replace(",", "."))
        console.print(t)
        state = "GEBLOCKT" if battle.blocked(res.ags_through) else "nicht sicher geblockt"
        console.print(f"{res.ags_through}/{res.ags_total} AGs kommen durch → {state}")
    console.print(
        "[dim]Näherung wie DS-Simulator: Rammen-Schaden am Wall nicht gerechnet (--wall-ags "
        "setzen), keine Kirche/Flaggen/Paladin-Items. Vor Entscheidungen im Spiel-Simulator "
        "gegenprüfen.[/]"
    )


@op_app.command("doc")
def op_doc(
    path: OpPath,
    gdoc: Annotated[
        str | None,
        typer.Option("--gdoc", help="ID oder Link des hochgeladenen Google Docs speichern"),
    ] = None,
    ende: Annotated[
        int | None,
        typer.Option(
            "--ende",
            help="Bestehendes Doc neu befüllen: endIndex des Doc-Inhalts (aus read_doc). "
            "Schreibt doc_update.json für update_doc - Link bleibt gleich.",
        ),
    ] = None,
    geschrieben: Annotated[
        bool, typer.Option(help="Nach update_doc: das Doc zeigt jetzt den aktuellen Plan")
    ] = False,
    geteilt: Annotated[
        bool, typer.Option(help="Doc ist freigegeben: jeder mit dem Link kann ansehen")
    ] = False,
    world: WorldOpt = None,
) -> None:
    """Dokument für die Spieler erzeugen (doc.html, wird zum Google Doc).

    Hochladen geht über Claude (Google-Drive-Connector) oder von Hand: in Google Drive
    "Neu > Datei hochladen", dann "Öffnen mit Google Docs". Danach die ID mit --gdoc merken.
    """
    settings = _settings(world)
    op = services.load_operation(path)
    store = WorldStore.open(settings)
    if gdoc is not None or geschrieben or geteilt:
        if gdoc is None and not op.gdoc_id:
            raise typer.BadParameter("Noch kein Google Doc gemerkt - erst --gdoc <ID/Link>.")
        doc_id = services.parse_gdoc_id(gdoc) if gdoc is not None else None
        op = services.mark_gdoc(
            store, path, settings.timezone, doc_id=doc_id, geteilt=True if geteilt else None
        )
        assert op.gdoc_id is not None
        console.print(f"Google Doc gespeichert: {services.gdoc_link(op.gdoc_id)}")
        if not op.gdoc_geteilt:
            console.print(
                "[yellow]Noch freigeben: Teilen → „Jeder mit dem Link“ → Betrachter, "
                "dann --geteilt.[/]"
            )
        return
    if services.plan_is_outdated(path):
        console.print("[yellow]plan.json ist älter als operation.yaml - erst `ap op solve`.[/]")
    if ende is not None:
        reqs = services.build_doc_update(
            store, op, services.load_plan(path), settings.timezone, ende
        )
        out = path.parent / "doc_update.json"
        out.write_text(json.dumps(reqs, ensure_ascii=False, separators=(",", ":")), "utf-8")
        console.print(f"{len(reqs)} Änderungen für das bestehende Doc: {out}")
        if op.gdoc_id:
            console.print(f"Doc: {services.gdoc_link(op.gdoc_id)}")
        return
    html = services.build_operation_doc(store, op, services.load_plan(path), settings.timezone)
    out = services.doc_path(path)
    out.write_text(html, encoding="utf-8")
    console.print(f"Dokument: {out}")
    if op.gdoc_id:
        console.print(f"Bestehendes Google Doc: {services.gdoc_link(op.gdoc_id)}")


def _refresh_roles(
    settings: Settings, cfg: discord_sync.DiscordConfig
) -> discord_sync.DiscordConfig:
    """Read the Discord roles named like our tribe tags (stamm + wing) and remember them."""
    client = DiscordClient(settings.discord_bot_token or "")
    try:
        cfg, match = discord_sync.refresh_roles(
            client, cfg, services.tribe_tags(settings.world_dir)
        )
    finally:
        client.close()
    discord_sync.save_config(cfg, settings.world_dir)
    for key, value in discord_sync.role_report(match).items():
        console.print(f"Rollen {key}: {value}")
    return cfg


def _warn_not_final(op: Operation) -> None:
    if op.status != Status.APPROVED:
        console.print(
            f"[yellow]Status {op.status.value}: Die öffentliche Ankündigung ist für den finalen "
            "Plan gedacht - erst `ap op status … approved`.[/]"
        )


def _warn_doc_for_review(store: WorldStore, op: Operation, plan: Plan, tz: str) -> None:
    state = services.gdoc_state(store, op, plan, tz)
    if not state.ready:
        console.print(
            f"[yellow]Google Doc {state.status}, geteilt={state.geteilt}: Das Review sollte den "
            "Link zum aktuellen Doc enthalten - erst `ap op doc` (siehe /google-doc).[/]"
        )


@op_app.command("discord")
def op_discord(
    path: OpPath,
    art: Annotated[
        str,
        typer.Option(
            help="review (SF), spieler (Ankündigung), thread (jeder seine Befehle im privaten "
            "Thread) oder dm (jeder seine Befehle als Direktnachricht)"
        ),
    ] = "review",
    senden: Annotated[bool, typer.Option(help="per Bot senden bzw. bearbeiten")] = False,
    nur: Annotated[
        list[str] | None, typer.Option(help="nur an diese Spieler (bei dm, mehrfach möglich)")
    ] = None,
    kopieren: Annotated[bool, typer.Option(help="zusätzlich in die Zwischenablage")] = False,
    ja: Annotated[bool, typer.Option("--ja", "-y", help="ohne Rückfrage senden")] = False,
    world: WorldOpt = None,
) -> None:
    """Discord-Nachricht erzeugen und optional per Bot senden.

    Ohne --senden wird der Text nur angezeigt und gespeichert. Mit --senden zeigt das Tool,
    wer was bekommt, fragt nach und sendet. Schon gesendete Nachrichten werden bearbeitet,
    nicht doppelt gesendet.
    """
    if art not in ("review", "spieler", "dm", "thread"):
        raise typer.BadParameter("--art review, spieler, thread oder dm")
    kind: discord_sync.Art = art  # type: ignore[assignment]
    settings = _settings(world)
    store = WorldStore.open(settings)
    op = services.load_operation(path)
    plan = services.load_plan(path)
    if senden:
        _discord_send(settings, store, op, plan, kind, path, nur=nur, yes=ja)
        return
    if art in ("dm", "thread"):
        texts = discord_sync.dm_texts(store, op, plan, tz=settings.timezone, only=nur)
        parts = [p for text in texts.values() for p in split_discord(text)]
    elif art == "review":
        _warn_doc_for_review(store, op, plan, settings.timezone)
        text = discord_review(op, plan, services.target_infos(store, op), settings.timezone)
        parts = split_discord(text)
    else:
        _warn_not_final(op)
        cfg = discord_sync.load_config(settings.world_dir)
        tags = services.tribe_tags(settings.world_dir)
        ping = discord_sync.role_ping(cfg) or " ".join(f"@{t}" for t in tags)
        enemies = enemy_tribes(services.target_infos(store, op))
        parts = split_discord(
            discord_players(
                op,
                plan,
                settings.timezone,
                enemies=enemies,
                ping=ping,
                unassigned=discord_sync.unassigned_players(plan, cfg),
            )
        )
    out = path.parent / f"discord_{art}.md"
    out.write_text("\n\n----- nächste Nachricht -----\n\n".join(parts) + "\n", encoding="utf-8")
    for i, part in enumerate(parts, 1):
        if len(parts) > 1:
            console.rule(f"Nachricht {i}/{len(parts)} ({len(part)} Zeichen)")
        # plain print: no rich markup/wrapping, so it can be copied 1:1
        print(part)
    console.print(f"[dim]Gespeichert in {out}[/]")
    if kopieren:
        _to_clipboard(parts[0], out)
        if len(parts) > 1:
            console.print(
                "Nachricht 1 ist in der Zwischenablage - die weiteren stehen in der Datei."
            )


def _discord_send(
    settings: Settings,
    store: WorldStore,
    op: Operation,
    plan: Plan,
    art: discord_sync.Art,
    path: Path,
    *,
    nur: list[str] | None,
    yes: bool,
) -> None:
    if art == "review":
        _warn_doc_for_review(store, op, plan, settings.timezone)
    cfg = discord_sync.load_config(settings.world_dir)
    if art == "spieler":
        if op.status != Status.APPROVED:
            _warn_not_final(op)
            raise typer.Exit(1)
        cfg = _refresh_roles(settings, cfg)
    prepared = discord_sync.prepare(store, op, plan, cfg, art, tz=settings.timezone, only=nur)
    for m in prepared.missing:
        console.print(f"[yellow]- {m}[/]")
    if not prepared.messages:
        console.print("Nichts zu senden.")
        raise typer.Exit(1)
    table = Table("An", "Teile", "Aktion")
    for msg in prepared.messages:
        to = {"thread": f"Thread {msg.key}", "dm": f"DM {msg.key}"}.get(msg.kind, f"#{msg.key}")
        table.add_row(to, str(len(msg.parts)), discord_sync.planned_action(op, msg))
    console.print(table)
    todo = [m for m in prepared.messages if discord_sync.planned_action(op, m) != "unverändert"]
    if not todo:
        console.print("Alles schon aktuell gesendet.")
        return
    if not yes and not typer.confirm(f"{len(todo)} Nachricht(en) jetzt über Discord senden?"):
        raise typer.Exit
    client = DiscordClient(settings.discord_bot_token)
    try:
        for msg in todo:
            try:
                op, action = discord_sync.deliver(client, op, msg)
            except DiscordError as err:
                console.print(f"[red]{msg.key}: {err}[/]")
                continue
            services.save_operation(op, path)
            console.print(f"[green]{msg.key}: {action}[/]")
    finally:
        client.close()
        if art == "thread":
            discord_sync.save_config(discord_sync.remember_threads(cfg, op), settings.world_dir)


@op_app.command("fortschritt")
def op_progress(path: OpPath, world: WorldOpt = None) -> None:
    """Wer hat in DS Ultimate schon „verschickt“ abgehakt? (braucht AP_DSU_API_KEY)"""
    settings = _settings(world)
    if not settings.dsu_api_key:
        raise typer.BadParameter("Kein DS-Ultimate-API-Key: AP_DSU_API_KEY in .env eintragen.")
    store = WorldStore.open(settings)
    op, plan = services.load_operation(path), services.load_plan(path)
    api = DsuApiClient(settings.dsu_api_key)
    try:
        progress, notes = services.dsu_progress(api, op, plan, datetime.now(UTC))
    finally:
        api.close()
    for n in notes:
        console.print(f"[yellow]- {n}[/]")
    zone = ZoneInfo(settings.timezone)
    coords = services.plan_coords(store, plan)
    table = Table("Spieler", "abgehakt", "überfällig", "nächster offener Befehl")
    for p in sorted(progress, key=lambda p: (-len(p.overdue), p.player.lower())):
        nxt = p.upcoming[0] if p.upcoming else None
        table.add_row(
            p.player,
            f"{p.sent}/{p.total}",
            f"[red]{len(p.overdue)}[/]" if p.overdue else "0",
            f"{nxt.send.astimezone(zone):%H:%M:%S} {coords.get(nxt.source_id)} → "
            f"{coords.get(nxt.target_id)}"
            if nxt
            else "-",
        )
    console.print(table)


@op_app.command("check")
def op_check(
    path: OpPath,
    dsu: Annotated[
        bool, typer.Option(help="auch DS-Ultimate-Pläne mit der Planung abgleichen")
    ] = False,
    world: WorldOpt = None,
) -> None:
    """Automatischer Review: doppelte Zuweisung, Reihenfolge-Regel, freie Truppen, Zeiten."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    report = services.check_operation(store, settings, path, with_dsu=dsu)
    text = report.markdown(services.load_operation(path).name)
    (path.parent / "check.md").write_text(text, encoding="utf-8")
    console.print(Markdown(text))
    console.print(f"[dim]Gespeichert in {path.parent / 'check.md'}[/]")
    if report.errors:
        raise typer.Exit(1)


@op_app.command("links")
def op_links(path: OpPath) -> None:
    """Gespeicherte Ansehen-Links ausgeben (pro Ziel und pro Spieler)."""
    op = services.load_operation(path)
    _print_links(op, "target")
    _print_links(op, "player")


@op_app.command("link")
def op_link(path: OpPath, key: str, link: str, world: WorldOpt = None) -> None:
    """DS-Ultimate-Link von Hand prüfen und speichern. KEY = Ziel (x|y) oder Spielername."""
    settings = _settings(world)
    store = WorldStore.open(settings)
    op = services.load_operation(path)
    plan = services.load_plan(path)
    kind: PlanKind = "target" if "|" in key else "player"
    group = next((g for g in services.dsu_groups(store, op, plan, kind) if g.key == key), None)
    if group is None:
        raise typer.BadParameter(f"{key} kommt im Plan nicht vor.")
    dsu = DsuClient()
    try:
        info = dsu.inspect(link)
    except (DsuLinkError, httpx.HTTPError) as err:
        raise typer.BadParameter(str(err)) from err
    finally:
        dsu.close()
    problems = services.check_dsu_plan(op, group, info)
    for p in problems:
        console.print(f"[red]- {p}[/]")
    if problems:
        raise typer.Exit(1)
    op = services.add_dsu_link(op, group, info)
    services.save_operation(op, path)
    console.print(f"Link für {key} gespeichert.")


@discord_app.command("einrichten")
def discord_setup(
    server: Annotated[str | None, typer.Option(help="Server-ID (Rechtsklick auf Server)")] = None,
    review: Annotated[str | None, typer.Option(help="Kanal-ID für das SF-Review")] = None,
    ankuendigung: Annotated[
        str | None, typer.Option(help="Kanal-ID für die Ankündigung an die Spieler")
    ] = None,
    befehle: Annotated[
        str | None, typer.Option(help="Kanal-ID für die privaten Threads pro Spieler")
    ] = None,
    world: WorldOpt = None,
) -> None:
    """Server und Kanäle für den Bot speichern (data/<welt>/discord.yaml).

    IDs bekommst du in Discord mit Entwicklermodus (Einstellungen → Erweitert) und
    Rechtsklick → „ID kopieren“. Der Bot-Token gehört in .env: AP_DISCORD_BOT_TOKEN=…
    """
    settings = _settings(world)
    cfg = discord_sync.load_config(settings.world_dir)
    kanaele = dict(cfg.kanaele)
    if review:
        kanaele["review"] = review
    if ankuendigung:
        kanaele["ankuendigung"] = ankuendigung
    if befehle:
        kanaele["befehle"] = befehle
    cfg = cfg.model_copy(update={"guild_id": server or cfg.guild_id, "kanaele": kanaele})
    out = discord_sync.save_config(cfg, settings.world_dir)
    console.print(f"Gespeichert in {out}")
    console.print(f"Server: {cfg.guild_id or '-'} · Kanäle: {cfg.kanaele or '-'}")
    if not settings.discord_bot_token:
        console.print("[yellow]Noch kein Bot-Token: AP_DISCORD_BOT_TOKEN in .env eintragen.[/]")


@discord_app.command("spieler")
def discord_players_cmd(
    alle: Annotated[bool, typer.Option(help="auch schon zugeordnete Spieler neu fragen")] = False,
    world: WorldOpt = None,
) -> None:
    """DS-Spieler den Discord-Mitgliedern zuordnen (private Threads bzw. Direktnachrichten).

    Lädt die Mitglieder des Servers, schlägt pro Stammesmitglied den passendsten Namen vor
    und fragt nach. Enter = Vorschlag übernehmen, n = überspringen, oder Nummern aus der
    Liste bzw. Discord-User-IDs eingeben - mehrere mit Komma, wenn mehrere Leute den Account
    spielen (z.B. ``3, 17``).
    """
    settings = _settings(world)
    store = WorldStore.open(settings)
    cfg = discord_sync.load_config(settings.world_dir)
    if not cfg.guild_id:
        raise typer.BadParameter("Erst `ap discord einrichten --server <ID>`")
    profile = services.load_profile(settings.world_dir)
    tribes = profile.own_tribes if profile else []
    names = discord_sync.own_players(store, tribes)
    client = DiscordClient(settings.discord_bot_token)
    try:
        members = client.members(cfg.guild_id)
    except DiscordError as err:
        console.print(f"[red]{err}[/]")
        console.print("Tipp: Im Entwicklerportal beim Bot „Server Members Intent“ einschalten.")
        raise typer.Exit(1) from err
    finally:
        client.close()
    members.sort(key=lambda m: m.label.lower())
    by_id = {m.id: m for m in members}
    for i, m in enumerate(members, 1):
        console.print(f"[dim]{i:3}[/] {m.label}")
    mapping = dict(cfg.spieler)
    for name in names:
        current = mapping.get(name)
        if current and not alle:
            continue
        if current:
            hint = ", ".join(by_id[i].label if i in by_id else i for i in current)
            guess_ids = current
        else:
            guess = discord_sync.suggest_member(name, members)
            hint = guess.label if guess else "kein Vorschlag"
            guess_ids = [guess.id] if guess else []
        answer = typer.prompt(f"{name} → {hint}", default="", show_default=False).strip()
        if answer.lower() == "n" or (not answer and not guess_ids):
            continue
        if not answer:
            mapping[name] = guess_ids
        else:
            parts = user_ids(answer)
            if not all(part.isdigit() for part in parts):
                console.print("[yellow]Nicht verstanden - übersprungen.[/]")
                continue
            mapping[name] = user_ids(
                [members[int(x) - 1].id if int(x) <= len(members) else x for x in parts]
            )
        cfg = cfg.model_copy(update={"spieler": mapping})
        discord_sync.save_config(cfg, settings.world_dir)
    console.print(f"{len(mapping)} von {len(names)} Spielern zugeordnet.")


def _field(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(p) for p in loc) or "(Datei)"


def main() -> None:
    """Entry point `ap`: readable errors instead of Python tracebacks."""
    try:
        app()
    except ValidationError as err:
        console.print("[red]Die Datei ist ungültig:[/]")
        for e in err.errors():
            console.print(f"  - [bold]{_field(e['loc'])}[/]: {e['msg']}")
        console.print("[dim]Format: docs/operation.md bzw. docs/profil.md[/]")
        raise SystemExit(1) from None
    except (LookupError, ValueError, FileNotFoundError, RuntimeError, httpx.HTTPError) as err:
        console.print(f"[red]Fehler:[/] {err}")
        raise SystemExit(1) from None
