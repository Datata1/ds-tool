"""Human-readable outputs: SF review (per target) and grouping helpers."""

import re
from collections import defaultdict
from zoneinfo import ZoneInfo

from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand
from ap_planner.models.world import Unit

_TYPE_LABEL = {
    CommandType.ATTACK: "Off",
    CommandType.CONQUEST: "AG",
    CommandType.FAKE: "Fake",
    CommandType.FAKE_SUPPORT: "Fake-Unterst.",
    CommandType.SUPPORT: "Unterst.",
    CommandType.STAND_SUPPORT: "Unterst.",
    CommandType.FAST_SUPPORT: "Unterst.",
    CommandType.WALLBREAKER: "Wallbrecher",
}


def kind_label(cmd: PlannedCommand) -> str:
    if cmd.type == CommandType.FAKE and (cmd.units.get(Unit.SNOB) or cmd.slowest_unit == Unit.SNOB):
        return "Fake-AG"
    return _TYPE_LABEL.get(cmd.type, "?")


UNIT_DE = {
    "spear": "Speer", "sword": "Schwert", "axe": "Axt", "spy": "Späher", "light": "LKav",
    "heavy": "SKav", "ram": "Ramme", "catapult": "Kata", "snob": "AG", "archer": "Bogen",
    "marcher": "BB", "knight": "Pala",
}  # fmt: skip


# Offensive population per unit (for the off-equivalent column).
OFF_POP = {"axe": 1, "light": 4, "marcher": 5, "ram": 5, "catapult": 8}


def safe_filename(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "spieler"


def _units(cmd: PlannedCommand) -> str:
    return ", ".join(f"{n} {UNIT_DE.get(u.value, u.value)}" for u, n in cmd.units.items() if n)


def is_wing(cmd: PlannedCommand) -> bool:
    return cmd.origin.startswith(("dsu:", "moved:", "manual:"))


def who(cmd: PlannedCommand) -> str:
    if cmd.origin == "kept:manual":
        return "Main (manuell)"
    if cmd.origin.startswith("kept:"):
        return "Main (alt)"
    if cmd.origin.startswith("moved:"):
        return "Wing (umgeleitet)"
    if cmd.origin.startswith("manual:"):
        return "Wing (manuell)"
    if cmd.origin.startswith("dsu:"):
        return "Wing"
    return "Main"


def player_commands(plan: Plan) -> list[PlannedCommand]:
    """Everything our players have to send: new commands + kept own commands."""
    return [*plan.commands, *(c for c in plan.existing if c.origin.startswith("kept:"))]


def group_by_player(plan: Plan) -> dict[str, list[PlannedCommand]]:
    groups: dict[str, list[PlannedCommand]] = defaultdict(list)
    for c in sorted(player_commands(plan), key=lambda c: c.send):
        groups[c.note.split(" -> ")[0]].append(c)
    return dict(sorted(groups.items(), key=lambda kv: kv[0].lower()))


def group_by_target(plan: Plan) -> dict[int, list[PlannedCommand]]:
    """Commands per target village id, each list ordered by arrival then send time."""
    groups: dict[int, list[PlannedCommand]] = defaultdict(list)
    for c in plan.commands:
        groups[c.target_id].append(c)
    for c in plan.existing:
        groups[c.target_id].append(c)
    # Same second: landing order = send order (no ms on the world).
    return {k: sorted(v, key=lambda c: (c.arrival, c.send)) for k, v in groups.items()}


def own_commands_by_target(plan: Plan) -> dict[int, list[PlannedCommand]]:
    """Only our commands per target (for export - wing commands are already in DSU)."""
    groups: dict[int, list[PlannedCommand]] = defaultdict(list)
    for c in plan.commands:
        groups[c.target_id].append(c)
    return {k: sorted(v, key=lambda c: (c.arrival, c.send)) for k, v in groups.items()}


def target_filename(coord: str, owner: str) -> str:
    return safe_filename(f"{coord.replace('|', '-')}_{owner}")


def review_markdown(
    op: Operation, plan: Plan, coords: dict[int, str], tz: str = "Europe/Berlin"
) -> str:
    """Overview for the SF review (Markdown, also readable as plain text)."""
    zone = ZoneInfo(tz)
    lines = [
        f"# OP {op.name} ({op.world})",
        f"Status: **{op.status.value}** · Ankunft: {op.arrival:%d.%m.%Y %H:%M:%S} · "
        f"Losschicken: {op.send_window.start:%H:%M}-{op.send_window.end:%H:%M}",
        f"Befehle gesamt: {len(plan.commands)}",
        "",
        "## Ziele",
        "Zahlen = Main (neu + behalten); Wing-Angriffe separat.",
        "",
        "| Ziel | Besitzer | Ankunft | Offs | AGs | Fake-AGs | Fakes | Unterst. | Wing | Notiz |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    per_target: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    off_pop: dict[int, int] = defaultdict(int)
    owners: dict[int, str] = {}
    wing_count: dict[int, int] = defaultdict(int)
    for c in plan.existing:
        owners[c.target_id] = c.note.split(" -> ")[1]
        if is_wing(c):
            wing_count[c.target_id] += 1
    for c in player_commands(plan):
        per_target[c.target_id][kind_label(c)] += 1
        owners[c.target_id] = c.note.split(" -> ")[1]
        if c.type == CommandType.ATTACK:
            off_pop[c.target_id] += sum(n * OFF_POP.get(u.value, 0) for u, n in c.units.items())
    for t in op.targets:
        tid = next((k for k, v in coords.items() if v == str(t.coord)), None)
        got = per_target.get(tid, {}) if tid is not None else {}
        strength = off_pop.get(tid, 0) / op.off_settings.min_pop if tid is not None else 0
        arrival = t.arrival or op.arrival
        landed = [
            c.arrival.astimezone(zone)
            for c in [*plan.commands, *plan.existing]
            if c.target_id == tid and c.type not in (CommandType.FAKE, CommandType.FAKE_SUPPORT)
        ] or [
            c.arrival.astimezone(zone)
            for c in [*plan.commands, *plan.existing]
            if c.target_id == tid
        ]
        if t.plans_nothing_new and landed:
            arrival = min(landed)
        offs = (
            f"{strength:.1f}/{t.offs} Fusion ({got.get('Off', 0)} Befehle)"
            if t.fusion
            else f"{got.get('Off', 0)}/{t.offs}"
        )
        lines.append(
            f"| {t.coord} | {owners.get(tid, '-') if tid else '-'} | {arrival:%H:%M:%S} "
            f"| {offs} "
            f"| {got.get('AG', 0)}/{t.nobles} | {got.get('Fake-AG', 0)}/{t.fake_nobles} "
            f"| {got.get('Fake', 0)}/{t.fakes} | {got.get('Unterst.', 0)} "
            f"| {wing_count.get(tid, 0) if tid is not None else 0} | {t.note} |"
        )
    if plan.warnings:
        lines += ["", "## Hinweise", *(f"- {w}" for w in plan.warnings)]
    lines += ["", "## Befehle pro Ziel"]
    by_target = group_by_target(plan)
    for t in op.targets:
        tid = next((k for k, v in coords.items() if v == str(t.coord)), None)
        cmds = by_target.get(tid, []) if tid is not None else []
        owner = owners.get(tid, "-") if tid is not None else "-"
        lines += ["", f"### {t.coord} {owner}" + (f" - {t.note}" if t.note else "")]
        if not cmds:
            lines.append("_keine Befehle geplant_")
            continue
        lines += [
            "| Ankunft | Typ | Wer | Spieler | von | Losschicken | Laufzeit | Truppen |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {c.arrival.astimezone(zone):%H:%M:%S} | {kind_label(c)} "
            f"| {who(c)} "
            f"| {c.note.split(' -> ')[0]} | {coords.get(c.source_id, str(c.source_id))} "
            f"| {c.send.astimezone(zone):%d.%m. %H:%M:%S} | {c.travel} | {_units(c)} |"
            for c in cmds
        ]
    lines += [
        "",
        "## Spieler-Übersicht",
        "| Spieler | Befehle | erster Befehl |",
        "|---|---|---|",
    ]
    lines += [
        f"| {player} | {len(cmds)} | {cmds[0].send.astimezone(zone):%d.%m. %H:%M:%S} |"
        for player, cmds in group_by_player(plan).items()
    ]
    for kind, title in (("target", "DS-Ultimate-Pläne pro Ziel"), ("player", "Spieler-Pläne")):
        links = [x for x in op.dsu_links if x.kind == kind]
        if links:
            lines += ["", f"## {title}", *(f"- {x.key}: {x.show_link}" for x in links)]
    return "\n".join(lines) + "\n"
