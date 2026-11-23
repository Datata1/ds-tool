"""Discord messages (Markdown) for the SF review and the player announcement."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ap_planner.export.review import (
    is_wing,
    kind_label,
    player_commands,
    unit_text,
)
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
    if op.gdoc_id and op.gdoc_geteilt:
        # shared as "anyone with the link can view" -> the reader link works for everyone
        doc = f"https://docs.google.com/document/d/{op.gdoc_id}/view"
        out.append(f"📄 **Plan-Dokument** (immer der aktuelle Stand): {_link(doc)}")
    if real_blocks:
        out += ["", "⚔️ **Echte Angriffe (Adeln)**", "\n\n".join(real_blocks)]
    if fake_blocks:
        out += ["", "🎭 **Fakes**", "\n".join(fake_blocks)]
    out += ["", _rules(op), "Nach Freigabe bekommt jeder Spieler seinen eigenen Plan."]
    return "\n".join(out) + "\n"


def _window(first: datetime, last: datetime) -> str:
    """'**12.11. 09:00**' or '**12.11. 08:59** bis **12.11. 09:03**' (minutes only)."""
    if first.replace(second=0) == last.replace(second=0):
        return f"**{first:%d.%m. %H:%M}**"
    return f"**{first:%d.%m. %H:%M}** bis **{last:%d.%m. %H:%M}**"


def enemy_tribes(targets: list[TargetInfo]) -> list[str]:
    """Tribe tags of the target owners (no barbarians/tribeless), in target order."""
    return list(dict.fromkeys(t.tribe for t in targets if t.tribe and t.tribe != "-"))


def discord_players(
    op: Operation,
    plan: Plan,
    tz: str,
    *,
    enemies: list[str] | None = None,
    ping: str = "",
    unassigned: list[str] | None = None,
) -> str:
    """Public player announcement: only general info, never targets, links or real vs fake.

    Everyone in the channel reads it (and may leak it), so it must not reveal which targets
    are real and which are fakes. Each player gets their own commands privately (thread/DM).
    It also asks everyone to send extra fakes on the enemy tribe(s) in the landing window:
    the more fakes, the harder it is for the defenders to find the real attacks.
    ``ping``: role mentions (stamm + wing) put in front. ``unassigned``: DS accounts with
    commands but no Discord user - they cannot get their commands and should contact the SF.
    """
    zone = ZoneInfo(tz)
    cmds = player_commands(plan)
    lines = [
        f"{ping}\n**OP {op.name}** ⚔️" if ping else f"**OP {op.name}** ⚔️",
        "Die Befehle sind verteilt: Jeder bekommt **seine** Befehle mit Plan-Link vom Bot "
        "(privater Thread bzw. Direktnachricht).",
    ]
    if cmds:
        first: datetime = min(c.send for c in cmds).astimezone(zone)
        last: datetime = max(c.send for c in cmds).astimezone(zone)
        lines.append(f"Abgeschickt wird zwischen {_window(first, last)}.")
        land_first: datetime = min(c.arrival for c in cmds).astimezone(zone)
        land_last: datetime = max(c.arrival for c in cmds).astimezone(zone)
        target = f" auf **{', '.join(enemies)}**" if enemies else ""
        lines += [
            "",
            "🎭 **Mehr Fakes = mehr Erfolg!** Auch wer keine Befehle bekommen hat: schickt "
            f"gern zusätzliche Fakes{target} mit Ankunft {_window(land_first, land_last)}. "
            "Je mehr Dörfer angegriffen werden, desto schwerer findet der Gegner die echten "
            "Angriffe. Fakelimit beachten, eigene Verteidigung nicht leer machen.",
        ]
    lines += [
        "",
        "Nicht wundern: Es schicken auch andere Spieler los, teils auf dieselben Dörfer, "
        "und es wird gefaket. Was echt ist und was Fake, wird bewusst nicht verraten – "
        "bitte auch nicht nachfragen oder darüber spekulieren.",
        "",
        "Bitte **pünktlich** und in der Reihenfolge eures Plans losschicken und in DS Ultimate "
        "abhaken. Probleme sofort melden.",
    ]
    if unassigned:
        lines += [
            "",
            "📢 **Bitte bei der SF melden:** Diese Accounts haben Befehle, sind aber noch "
            f"keinem Discord-Nutzer zugeordnet und bekommen ihre Befehle deshalb nicht: "
            f"{', '.join(f'**{name}**' for name in unassigned)}. Wer einen davon spielt, "
            "meldet sich bitte bei der SF.",
        ]
    lines += [
        "",
        _rules(op),
    ]
    return "\n".join(lines) + "\n"


def discord_player_dm(
    op: Operation, player: str, cmds: list[PlannedCommand], coords: dict[int, str], tz: str
) -> str:
    """Direct message for one player: plan link plus own commands, sorted by send time."""
    zone = ZoneInfo(tz)
    own = op.dsu_link("player", player)
    if own is not None:
        plan_line = f"Dein Plan: {_link(own.show_link)}"
    else:  # no player plan: link the plans of the target villages instead
        target_coords = dict.fromkeys(coords.get(c.target_id, "") for c in cmds)
        links = [x for t in target_coords if (x := op.dsu_link("target", t)) is not None]
        plan_line = (
            "Plan: " + " · ".join(f"`{x.key}` {_link(x.show_link)}" for x in links)
            if links
            else f"Dein Plan: {_link(None)}"
        )
    lines = [f"**OP {op.name}** – deine Befehle, {player} ⚔️", plan_line, ""]
    for c in sorted(cmds, key=lambda c: c.send):
        send = c.send.astimezone(zone)
        arrival = c.arrival.astimezone(zone)
        when = (
            "läuft schon"
            if c.origin.endswith("manual:running")
            else f"**{send:%d.%m. %H:%M:%S}** losschicken"
        )
        src = coords.get(c.source_id, str(c.source_id))
        dst = coords.get(c.target_id, str(c.target_id))
        lines.append(
            f"• {when} · `{src}` → `{dst}` · {kind_label(c)} · Ankunft {arrival:%H:%M:%S}"
            f" · {unit_text(c)}"
        )
    lines += ["", _rules(op), "Bitte sekundengenau schicken. Probleme sofort im Discord melden."]
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
