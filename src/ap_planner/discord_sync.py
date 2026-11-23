"""Use cases for Discord: build the messages of an operation and deliver them.

A message that was sent before is edited instead of posted again (ids are stored in the
operation). Unchanged messages are skipped.
"""

import difflib
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml

from ap_planner.discord_bot import DiscordClient, DiscordError, Member, Role
from ap_planner.export.announce import (
    discord_player_dm,
    discord_players,
    discord_review,
    enemy_tribes,
    split_discord,
)
from ap_planner.export.review import group_by_player, kind_label
from ap_planner.ingest.store import WorldStore
from ap_planner.models.discord import DiscordConfig
from ap_planner.models.operation import MessageKind, Operation, SentMessage
from ap_planner.models.plan import Plan, PlannedCommand
from ap_planner.services import PlayerProgress, target_infos

Art = Literal["review", "spieler", "dm", "thread"]
# Below 2000 so the @mention in front of the first part still fits.
THREAD_LIMIT = 1950
# Which channel alias each channel message goes to. The public announcement goes into the
# channel that holds the private threads (everyone has it open), else "ankuendigung".
CHANNEL_OF: dict[str, tuple[str, ...]] = {
    "review": ("review",),
    "spieler": ("befehle", "ankuendigung"),
}


def _tag_key(name: str) -> str:
    """'[RAK]', '@RAK', 'rak ' -> 'rak' (so a role matches its tribe tag, RAKK stays RAKK)."""
    return re.sub(r"[\W_]+", "", name).casefold()


@dataclass(frozen=True)
class RoleMatch:
    found: dict[str, str]  # tribe tag -> role id
    missing: list[str]  # tribe tags without a role of that name
    not_mentionable: list[str]  # role names the bot may not be able to ping


def match_roles(roles: list[Role], tags: list[str]) -> RoleMatch:
    """Discord roles named like our tribe tags (own tribe + wing)."""
    by_key: dict[str, Role] = {}
    for r in roles:
        by_key.setdefault(_tag_key(r.name), r)
    found: dict[str, str] = {}
    missing: list[str] = []
    quiet: list[str] = []
    for tag in dict.fromkeys(tags):
        role = by_key.get(_tag_key(tag))
        if role is None:
            missing.append(tag)
            continue
        found[tag] = role.id
        if not role.mentionable:
            quiet.append(role.name)
    return RoleMatch(found, missing, quiet)


def refresh_roles(
    client: DiscordClient, cfg: DiscordConfig, tags: list[str]
) -> tuple[DiscordConfig, RoleMatch]:
    """Read the server's roles and remember those named like our tribe tags."""
    if cfg.guild_id is None:
        return cfg, RoleMatch({}, list(tags), [])
    match = match_roles(client.roles(cfg.guild_id), tags)
    return cfg.model_copy(update={"rollen": match.found}), match


def role_report(match: RoleMatch) -> dict[str, object]:
    """Plain-language summary for the player (which tags get pinged, what is missing)."""
    out: dict[str, object] = {"erwaehnt": [f"@{t}" for t in match.found]}
    if match.missing:
        out["keine_rolle"] = (
            f"Keine Discord-Rolle für {', '.join(match.missing)} gefunden - diese Stämme "
            "werden nicht erwähnt (Rolle muss wie der Stammes-Tag heißen)."
        )
    if match.not_mentionable:
        out["nicht_erwaehnbar"] = (
            f"Rolle(n) {', '.join(match.not_mentionable)}: In Discord unter Servereinstellungen "
            "→ Rollen → Rolle → „Erlaube jedem, diese Rolle zu @erwähnen“ einschalten, sonst "
            "bekommt die Erwähnung niemand mit."
        )
    return out


def unassigned_players(plan: Plan, cfg: DiscordConfig) -> list[str]:
    """DS accounts with commands in this plan but no Discord user (cannot get their commands)."""
    return [p for p in group_by_player(plan) if not cfg.spieler.get(p)]


def role_ping(cfg: DiscordConfig) -> str:
    return " ".join(f"<@&{rid}>" for rid in dict.fromkeys(cfg.rollen.values()))


def config_path(world_dir: Path) -> Path:
    return world_dir / "discord.yaml"


def load_config(world_dir: Path) -> DiscordConfig:
    path = config_path(world_dir)
    if not path.exists():
        return DiscordConfig()
    return DiscordConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def save_config(cfg: DiscordConfig, world_dir: Path) -> Path:
    path = config_path(world_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(cfg.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path


def own_players(store: WorldStore, tribes: list[str]) -> list[str]:
    """Names of all members of our tribes (public map data)."""
    names: list[str] = []
    for tag in tribes:
        ally = store.ally_by_tag(tag)
        if ally is not None:
            names += [p.name for p in store.members_of_ally(ally.id)]
    return sorted(set(names), key=str.lower)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def suggest_member(name: str, members: list[Member], cutoff: float = 0.6) -> Member | None:
    """Best Discord member for a DS player name (nickname, display name or username)."""
    target = _norm(name)
    best: tuple[float, Member] | None = None
    for m in members:
        for n in m.names:
            score = difflib.SequenceMatcher(None, target, _norm(n)).ratio()
            if best is None or score > best[0]:
                best = (score, m)
    return best[1] if best and best[0] >= cutoff else None


@dataclass(frozen=True)
class Outgoing:
    kind: MessageKind
    key: str  # channel alias or player name
    channel_id: str | None  # channel messages; for threads: the player's existing thread
    user_ids: tuple[str, ...]  # threads: everyone who plays the account; DMs: one recipient
    parts: list[str]
    parent_id: str | None = None  # threads: channel that holds the private threads
    role_ids: tuple[str, ...] = ()  # roles this message may ping (public announcement)

    @property
    def player(self) -> str:
        """DS player name (DM keys for a second/third person are ``Name@<id>``)."""
        return self.key.split("@", 1)[0] if self.kind == "dm" else self.key

    @property
    def content_hash(self) -> str:
        return hashlib.sha256("\n\0".join(self.parts).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Prepared:
    messages: list[Outgoing]
    missing: list[str]  # human readable: what is not configured


def prepare(
    store: WorldStore,
    op: Operation,
    plan: Plan,
    cfg: DiscordConfig,
    art: Art,
    *,
    tz: str,
    only: list[str] | None = None,
) -> Prepared:
    if art in CHANNEL_OF:
        aliases = CHANNEL_OF[art]
        alias = next((a for a in aliases if cfg.kanaele.get(a)), aliases[0])
        channel = cfg.kanaele.get(alias)
        if channel is None:
            names = " oder ".join(f"'{a}'" for a in aliases)
            return Prepared([], [f"Kanal {names} fehlt (ap discord einrichten)"])
        infos = target_infos(store, op)
        roles: tuple[str, ...] = ()
        if art == "review":
            text = discord_review(op, plan, infos, tz)
        else:
            roles = tuple(dict.fromkeys(cfg.rollen.values()))
            text = discord_players(
                op,
                plan,
                tz,
                enemies=enemy_tribes(infos),
                ping=role_ping(cfg),
                unassigned=unassigned_players(plan, cfg),
            )
        msgs = [Outgoing(art, alias, channel, (), split_discord(text), role_ids=roles)]
        return Prepared(msgs, [])
    msgs: list[Outgoing] = []
    missing: list[str] = []
    parent = cfg.kanaele.get("befehle")
    if art == "thread" and parent is None:
        return Prepared([], ["Kanal 'befehle' für die privaten Threads fehlt (discord_setup)"])
    for player, text in dm_texts(store, op, plan, tz=tz, only=only).items():
        users = cfg.spieler.get(player)
        if not users:
            missing.append(f"{player}: keine Discord-Zuordnung (ap discord spieler)")
            continue
        if art == "thread":
            parts = split_discord(text, THREAD_LIMIT - 24 * (len(users) - 1))
            # ping: everyone who plays the account sees the new thread at once
            parts[0] = f"{mentions(users)} {parts[0]}"
            thread = cfg.threads.get(player)
            msgs.append(Outgoing("thread", player, thread, tuple(users), parts, parent_id=parent))
        else:
            msgs += dm_messages(player, users, split_discord(text))
    return Prepared(msgs, missing)


def mentions(users: list[str] | tuple[str, ...]) -> str:
    return " ".join(f"<@{u}>" for u in users)


def dm_messages(player: str, users: list[str], parts: list[str]) -> list[Outgoing]:
    """One direct message per person. The first keeps the plain player name as key, so
    messages sent before several people were assigned are still edited, not sent twice."""
    return [
        Outgoing("dm", player if i == 0 else f"{player}@{u}", None, (u,), parts)
        for i, u in enumerate(users)
    ]


def dm_texts(
    store: WorldStore, op: Operation, plan: Plan, *, tz: str, only: list[str] | None = None
) -> dict[str, str]:
    """Direct message text per player (all players with commands, or only the given ones)."""
    by_player = group_by_player(plan)
    coords: dict[int, str] = {}
    for cmds in by_player.values():
        for c in cmds:
            for vid in (c.source_id, c.target_id):
                v = store.village(vid)
                if v is not None:
                    coords[vid] = str(v.coord)
    return {
        player: discord_player_dm(op, player, cmds, coords, tz)
        for player, cmds in by_player.items()
        if not only or player in only
    }


def planned_action(op: Operation, msg: Outgoing) -> str:
    saved = op.sent_message(msg.kind, msg.key)
    if saved is None:
        return "senden"
    if saved.content_hash == msg.content_hash:
        return "unverändert"
    return "bearbeiten + Hinweis" if msg.kind in ("thread", "dm") else "bearbeiten"


def update_notice(op: Operation, msg: Outgoing) -> str:
    """Edits do not notify anyone: a new short message (pinging the player in the thread)
    tells them the plan changed and an open DS-Ultimate page needs a reload."""
    ping = f"{mentions(msg.user_ids)} " if msg.kind == "thread" else ""
    return (
        f"{ping}🔄 **Dein Plan für OP {op.name} wurde aktualisiert.** "
        "Bitte die Befehle oben nochmal ansehen und den DS-Ultimate-Plan neu laden (F5), "
        "falls du ihn schon offen hast."
    )


def thread_name(player: str) -> str:
    return f"Befehle {player}"


def ensure_thread(
    client: DiscordClient,
    parent_id: str,
    thread_id: str | None,
    player: str,
    user_ids: tuple[str, ...],
) -> str:
    """The player's private thread: reopened if archived, new if missing; everyone who plays
    the account is a member."""
    if thread_id:
        try:
            client.unarchive(thread_id)
            for user_id in user_ids:
                client.add_thread_member(thread_id, user_id)
        except DiscordError as err:
            if err.status != 404:
                raise
        else:
            return thread_id
    new_id = client.create_private_thread(parent_id, thread_name(player))
    for user_id in user_ids:
        client.add_thread_member(new_id, user_id)
    return new_id


def open_channel(client: DiscordClient, msg: Outgoing) -> str:
    """Where a new message goes: channel, private thread or direct message."""
    if msg.kind == "thread":
        if msg.parent_id is None or not msg.user_ids:
            raise ValueError(msg)
        return ensure_thread(client, msg.parent_id, msg.channel_id, msg.key, msg.user_ids)
    if msg.channel_id is not None:
        return msg.channel_id
    if len(msg.user_ids) == 1:
        return client.dm_channel(msg.user_ids[0])
    raise ValueError(msg)


def deliver(client: DiscordClient, op: Operation, msg: Outgoing) -> tuple[Operation, str]:
    """Send a message, or edit the one sent before. Returns the new operation and the action."""
    saved = op.sent_message(msg.kind, msg.key)
    if saved is not None and saved.content_hash == msg.content_hash:
        return op, "unverändert"
    if saved is not None and msg.kind == "thread":
        try:  # archived threads cannot be edited
            client.unarchive(saved.channel_id)
        except DiscordError as err:
            if err.status != 404:
                raise
            saved = None  # thread was deleted: start a new one
    if saved is not None:
        channel = saved.channel_id
        ids: list[str] = []
        for i, part in enumerate(msg.parts):
            if i < len(saved.message_ids):
                client.edit(channel, saved.message_ids[i], part, msg.role_ids)
                ids.append(saved.message_ids[i])
            else:
                ids.append(client.send(channel, part, msg.role_ids))
        for extra in saved.message_ids[len(msg.parts) :]:
            client.delete(channel, extra)
        action = "bearbeitet"
        if msg.kind in ("thread", "dm"):
            client.send(channel, update_notice(op, msg))  # not tracked: a new ping each time
            action = "bearbeitet + Hinweis"
    else:
        channel = open_channel(client, msg)
        ids = [client.send(channel, part, msg.role_ids) for part in msg.parts]
        action = "gesendet"
    sent = SentMessage(
        kind=msg.kind,
        key=msg.key,
        channel_id=channel,
        message_ids=ids,
        content_hash=msg.content_hash,
    )
    others = [m for m in op.discord_messages if not (m.kind == msg.kind and m.key == msg.key)]
    return op.model_copy(update={"discord_messages": [*others, sent]}), action


def remember_threads(cfg: DiscordConfig, op: Operation) -> DiscordConfig:
    """Store the players' thread ids, so the next operation posts into the same thread."""
    threads = dict(cfg.threads)
    threads |= {m.key: m.channel_id for m in op.discord_messages if m.kind == "thread"}
    return cfg.model_copy(update={"threads": threads})


def reminder_due(p: PlayerProgress, now: datetime, minutes: float) -> bool:
    """Remind this player? Something overdue, or the next send within ``minutes``."""
    soon = now + timedelta(minutes=minutes)
    return bool(p.overdue) or any(c.send <= soon for c in p.upcoming)


def reminder_text(
    op: Operation,
    p: PlayerProgress,
    *,
    coords: dict[int, str],
    tz: str,
    now: datetime,
    minutes: float,
) -> str:
    """Short reminder: overdue commands and the ones due within ``minutes``."""
    zone = ZoneInfo(tz)
    soon = now + timedelta(minutes=minutes)

    def line(c: PlannedCommand) -> str:
        src = coords.get(c.source_id, str(c.source_id))
        dst = coords.get(c.target_id, str(c.target_id))
        return f"• **{c.send.astimezone(zone):%H:%M:%S}** `{src}` → `{dst}` · {kind_label(c)}"

    lines = [f"⏰ **Erinnerung OP {op.name}** · {p.sent}/{p.total} in DS Ultimate abgehakt"]
    if p.overdue:
        lines += ["", "**Zeit schon vorbei, nicht abgehakt** (schon geschickt? dann abhaken):"]
        lines += [line(c) for c in p.overdue[:10]]
    due = [c for c in p.upcoming if c.send <= soon]
    if due:
        lines += ["", f"**In den nächsten {minutes:g} Minuten:**"]
        lines += [line(c) for c in due[:10]]
    link = op.dsu_link("player", p.player)
    if link is not None:
        lines += ["", f"Dein Plan: <{link.show_link}>"]
    return "\n".join(lines)


def to_player(cfg: DiscordConfig, player: str, parts: list[str]) -> list[Outgoing]:
    """A one-off message to a player: into their private thread if set up, else as DM to
    everyone who plays the account. Empty if the player has no Discord assignment."""
    users = cfg.spieler.get(player)
    if not users:
        return []
    parent = cfg.kanaele.get("befehle")
    if parent is not None:
        thread = cfg.threads.get(player)
        return [Outgoing("thread", player, thread, tuple(users), parts, parent_id=parent)]
    return dm_messages(player, users, parts)


def post(client: DiscordClient, msg: Outgoing) -> str:
    """Send a one-off message (not tracked for editing). Returns the channel/thread id."""
    channel = open_channel(client, msg)
    for part in msg.parts:
        client.send(channel, part)
    return channel
