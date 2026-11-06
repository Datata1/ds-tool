"""Command-line interface: ``uv run ap --help``."""

import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from ap_planner import services
from ap_planner.config import Settings
from ap_planner.dsu import DsuClient, DsuLinkError
from ap_planner.export.announce import discord_players, discord_review, split_discord
from ap_planner.export.review import safe_filename
from ap_planner.ingest.store import WorldStore
from ap_planner.models.map import Coord
from ap_planner.models.operation import DsuMode, Operation, PlanKind, Status
from ap_planner.models.profile import Profile
from ap_planner.models.world import Unit

app = typer.Typer(
    no_args_is_help=True, help="KI-gestützter Angriffsplaner für Die Stämme (kein Botting)."
)
troops_app = typer.Typer(no_args_is_help=True, help="Truppen importieren und anzeigen.")
app.add_typer(troops_app, name="troops")
op_app = typer.Typer(no_args_is_help=True, help="Operationen planen, prüfen, exportieren.")
app.add_typer(op_app, name="op")
console = Console()

WorldOpt = Annotated[str | None, typer.Option("--world", "-w", help="e.g. de260")]


def _settings(world: str | None) -> Settings:
    settings = Settings(world=world) if world else Settings()
    if not settings.world:
        raise typer.BadParameter(
            "Keine Welt gesetzt. Einmal `uv run ap init` ausführen oder --world de260 angeben."
        )
    return settings


ENV_FILE = Path(".env")


def _write_env(values: dict[str, str]) -> None:
    """Set keys in .env, keep all other lines."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in values]
    keep += [f"{k}={v}" for k, v in values.items()]
    ENV_FILE.write_text("\n".join(keep) + "\n", encoding="utf-8")


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
    _write_env({"AP_WORLD": world, "AP_SERVER": server})
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
    stored = services.import_overview_text(store, text)
    unknown = [v for v in stored if v.village_id is None]
    owners: dict[str, int] = {}
    for v in stored:
        name = services.owner_name(store, v.village_id)
        owners[name] = owners.get(name, 0) + 1
    console.print(f"[green]{len(stored)} villages imported.[/]")
    for name, count in sorted(owners.items()):
        console.print(f"  {name}: {count}")
    for v in unknown:
        console.print(f"[yellow]  not on map (run `ap sync`?): {v.name} ({v.coord})[/]")


@troops_app.command("show")
def troops_show(world: WorldOpt = None) -> None:
    """Importierte Truppen anzeigen."""
    store = WorldStore.open(_settings(world))
    cfg = store.world_config()
    units = [u for u in cfg.units if u.value != "militia"]
    table = Table("player", "coord", "name", *(u.value for u in units), "out", "in", "captured")
    for vt, _source, captured in store.troops():
        table.add_row(
            services.owner_name(store, vt.village_id),
            str(vt.coord),
            vt.name,
            *(str(vt.units.get(u, 0)) for u in units),
            str(vt.outgoing),
            f"[red]{vt.incoming}[/]" if vt.incoming else "0",
            captured[:16],
        )
    console.print(table)


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
    path.write_text(OP_TEMPLATE.format(world=settings.world, name=name, arrival=ankunft))
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
    world: WorldOpt = None,
) -> None:
    """DS-Ultimate-Pläne anlegen: pro Ziel (für die SF) oder pro Spieler.

    Öffnet für jeden Plan einen neuen DS-Ultimate-Planer im Browser, legt den
    Workbench-Text in die Zwischenablage und fragt nach dem Ansehen-Link.
    """
    if fuer not in ("ziele", "spieler"):
        raise typer.BadParameter("--fuer ziele oder --fuer spieler")
    settings = _settings(world)
    store = WorldStore.open(settings)
    op = services.load_operation(path)
    plan = services.load_plan(path)
    kind: PlanKind = "target" if fuer == "ziele" else "player"
    groups = services.dsu_groups(store, op, plan, kind)
    dsu = DsuClient()
    if kind == "target":
        op = _register_kept_plans(dsu, op, path)
    todo = [g for g in groups if alle or op.dsu_link(g.kind, g.key) is None]
    console.print(f"{len(todo)} von {len(groups)} Plänen anzulegen ({fuer}).")
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
    dsu.close()
    _print_links(op, kind)


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


@op_app.command("discord")
def op_discord(
    path: OpPath,
    art: Annotated[str, typer.Option(help="review (SF, pro Ziel) oder spieler")] = "review",
    kopieren: Annotated[bool, typer.Option(help="zusätzlich in die Zwischenablage")] = False,
    world: WorldOpt = None,
) -> None:
    """Discord-Nachricht erzeugen: SF-Review pro Zieldorf oder Ankündigung pro Spieler."""
    if art not in ("review", "spieler"):
        raise typer.BadParameter("--art review oder --art spieler")
    settings = _settings(world)
    store = WorldStore.open(settings)
    op = services.load_operation(path)
    plan = services.load_plan(path)
    if art == "review":
        text = discord_review(op, plan, services.target_infos(store, op), settings.timezone)
    else:
        text = discord_players(op, plan, settings.timezone)
    parts = split_discord(text)
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
