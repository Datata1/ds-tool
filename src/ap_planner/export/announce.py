"""Discord messages (Markdown) for the SF review and the player announcement."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ap_planner.export.review import group_by_player, is_wing, kind_label, player_commands
from ap_planner.models.operation import Operation
from ap_planner.models.plan import CommandType, Plan, PlannedCommand

UNIT_SHORT = {"spear": "Speer", "sword": "Schwert", "spy": "Späher", "heavy": "SKav"}


@dataclass(frozen=True)
class TargetInfo:
    coord: str
    village_id: int
    village_name: str
    owner: str
    tribe: str


def _link(url: str | None) -> str:
    # <...> stops Discord from embedding a preview for every link
    return f"<{url}>" if url else "_(Link folgt)_"


def _players(cmds: list[PlannedCommand]) -> str:
    counts = Counter(c.note.split(" -> ")[0] for c in cmds)
    return ", ".join(f"{p} ×{n}" if n > 1 else p for p, n in counts.items())


def _summary(cmds: list[PlannedCommand]) -> str:
    """'1 Off (SeWarri) + 4 AGs (Graf ×2, Suea) + 3 Fakes' etc."""
    parts: list[str] = []
    by_kind: dict[str, list[PlannedCommand]] = {}
    for c in sorted(cmds, key=lambda c: (c.arrival, c.send)):
        by_kind.setdefault(kind_label(c), []).append(c)
    named = {"Off": ("Off", "Offs"), "AG": ("AG", "AGs")}
    for kind, (one, many) in named.items():
        if kind in by_kind:
            n = len(by_kind[kind])
            parts.append(f"{n} {one if n == 1 else many} ({_players(by_kind[kind])})")
    if "Unterst." in by_kind:
        n = len(by_kind["Unterst."])
        parts.append(f"Flexdeff nach dem letzten AG ({n}× {_players(by_kind['Unterst.'])})")
    for kind, (one, many) in {
        "Fake": ("Fake", "Fakes"),
        "Fake-AG": ("Fake-AG", "Fake-AGs"),
        "Fake-Unterst.": ("Fake-Unterstützung", "Fake-Unterstützungen"),
        "Wallbrecher": ("Wallbrecher", "Wallbrecher"),
    }.items():
        if kind in by_kind:
            n = len(by_kind[kind])
            parts.append(f"{n} {one if n == 1 else many}")
    return " + ".join(parts) or "-"


def _arrivals(cmds: list[PlannedCommand], zone: ZoneInfo) -> str:
    real = [c for c in cmds if c.type not in (CommandType.FAKE, CommandType.FAKE_SUPPORT)]
    seconds = sorted({c.arrival.astimezone(zone).replace(microsecond=0) for c in real or cmds})
    if len(seconds) > 3:
        return f"{seconds[0]:%H:%M:%S} – {seconds[-1]:%H:%M:%S}"
    return " / ".join(f"{s:%H:%M:%S}" for s in seconds)


def _rules(op: Operation) -> str:
    rules = ["Offs werden immer VOR den AGs losgeschickt (gleiche Sekunde = Abschick-Reihenfolge)."]
    if any(t.support for t in op.targets):
        rules.append("Flexdeff landet erst nach dem letzten AG.")
    if op.home_guard:
        guard = ", ".join(
            f"{n} {UNIT_SHORT.get(u.value, u.value)}" for u, n in op.home_guard.items()
        )
        rules.append(f"Fakeschutz: {guard} bleiben überall daheim.")
    return "ℹ️ Regeln: " + " ".join(rules)


def discord_review(op: Operation, plan: Plan, targets: list[TargetInfo], tz: str) -> str:
    """SF review message: one block per target plan, real attacks first, then fakes."""
    zone = ZoneInfo(tz)
    mine = player_commands(plan)
    wing = [c for c in plan.existing if is_wing(c)]
    real_blocks: list[str] = []
    fake_blocks: list[str] = []
    for t in targets:
        main_t = [c for c in mine if c.target_id == t.village_id]
        wing_t = [c for c in wing if c.target_id == t.village_id]
        all_t = main_t + wing_t
        if not all_t:
            continue
        link = op.dsu_link("target", t.coord)
        head = (
            f"**{t.village_name}** – {t.owner} ({t.tribe}) `{t.coord}` – "
            f"Ankunft **{_arrivals(all_t, zone)}**"
        )
        is_real = any(c.type == CommandType.CONQUEST for c in all_t)
        if is_real:
            lines = [head]
            if main_t:
                lines.append(f"> Main: {_summary(main_t)}")
            if wing_t:
                lines.append(f"> Wing: {_summary(wing_t)}")
            lines.append(f"> {_link(link.show_link if link else None)}")
            real_blocks.append("\n".join(lines))
        else:
            who = "" if not wing_t else f" (Wing: {_summary(wing_t)})"
            fake_blocks.append(
                f"{head} – {_summary(main_t)}{who}\n> {_link(link.show_link if link else None)}"
            )
    out = [
        f"**OP {op.name} | Review-Pläne pro Zieldorf**",
        "Bitte prüfen & Feedback hier im Thread. Links = Ansehen-Links (DS-Ultimate).",
    ]
    if real_blocks:
        out += ["", "⚔️ **Echte Angriffe (Adeln)**", "\n\n".join(real_blocks)]
    if fake_blocks:
        out += ["", "🎭 **Fakes**", "\n".join(fake_blocks)]
    out += ["", _rules(op), "Nach Freigabe bekommt jeder Spieler seinen eigenen Plan."]
    return "\n".join(out) + "\n"


def discord_players(op: Operation, plan: Plan, tz: str) -> str:
    """Player announcement: per player number of commands, first send time and plan link."""
    zone = ZoneInfo(tz)
    lines = [
        f"**OP {op.name} – eure Angriffspläne** ⚔️",
        "Jeder hat seinen eigenen DS-Ultimate-Plan mit genau seinen Befehlen. "
        "Bitte **pünktlich** losschicken und in der Reihenfolge des Plans!",
        "",
    ]
    for player, cmds in group_by_player(plan).items():
        first: datetime = min(c.send for c in cmds).astimezone(zone)
        link = op.dsu_link("player", player)
        kinds = Counter(kind_label(c) for c in cmds)
        what = ", ".join(f"{n}× {k}" for k, n in kinds.items())
        noun = "Befehl" if len(cmds) == 1 else "Befehle"
        lines.append(
            f"**{player}** – {len(cmds)} {noun} ({what}), erster um "
            f"**{first:%d.%m. %H:%M:%S}**\n> {_link(link.show_link if link else None)}"
        )
    lines += ["", _rules(op)]
    return "\n".join(lines) + "\n"


def split_discord(text: str, limit: int = 2000) -> list[str]:
    """Split a message into Discord-sized parts at blank lines (blocks stay together)."""
    parts: list[str] = []
    current = ""
    for block in text.strip().split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        rest = block
        while len(rest) > limit:  # a single huge block: cut at line breaks
            cut = rest.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(rest[:cut])
            rest = rest[cut:].lstrip("\n")
        current = rest
    if current:
        parts.append(current)
    return parts
