"""Minimal Discord bot client (REST only, no gateway, no extra library).

Posts to channels, sends direct messages, edits and deletes our own messages and lists
server members (for the DS name -> Discord user mapping). Every send is triggered by the
user after a preview; nothing here runs on its own.
"""

import base64
import binascii
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ap_planner import __version__

API = "https://discord.com/api/v10"
USER_AGENT = f"DiscordBot (https://github.com/ap-planner, {__version__})"
# Never ping @everyone/@here or roles by accident; user mentions are allowed.
NO_MASS_MENTIONS = {"parse": ["users"]}


def allowed_mentions(roles: tuple[str, ...] = ()) -> dict[str, Any]:
    """Users always; roles only the ones named explicitly (never @everyone/@here)."""
    return {**NO_MASS_MENTIONS, "roles": list(roles)} if roles else NO_MASS_MENTIONS


_ERRORS = {
    401: "Discord: Bot-Token ist falsch (Einstellungen der Erweiterung bzw. .env prüfen).",
    403: "Discord: Dem Bot fehlen Rechte (Kanal sehen, Nachrichten senden, private Threads "
    "erstellen - ggf. mit neuem Einladungslink neu einladen) oder der Spieler erlaubt keine "
    "Direktnachrichten von Server-Mitgliedern.",
    404: "Discord: Kanal, Nachricht oder Benutzer nicht gefunden (ID prüfen).",
}
MAX_RETRIES = 5


class DiscordError(RuntimeError):
    """Discord refused a request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# View Channels, Send Messages, Read Message History, Create Private Threads,
# Send Messages in Threads
BOT_PERMISSIONS = 1024 + 2048 + 65536 + (1 << 36) + (1 << 38)
TEXT_CHANNEL = 0
PRIVATE_THREAD = 12
# Longest auto-archive time (7 days); the bot reopens archived threads before writing.
THREAD_ARCHIVE_MINUTES = 10080


def application_id(token: str) -> str | None:
    """The bot's application id: the first part of the token is it, base64 encoded."""
    first = token.strip().split(".", 1)[0]
    try:
        value = base64.b64decode(first + "=" * (-len(first) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return value if value.isdigit() else None


def pick_by_name(items: list[dict[str, str]], ref: str) -> dict[str, str] | None:
    """Server/channel by id or name (exact, else a unique partial match; '#' is ignored)."""
    ref = ref.strip().lstrip("#").casefold()
    for it in items:
        if ref in (it["id"], it["name"].casefold()):
            return it
    hits = [it for it in items if ref in it["name"].casefold()]
    return hits[0] if len(hits) == 1 else None


def invite_url(app_id: str) -> str:
    """Link that adds the bot to a server with exactly the rights it needs."""
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={app_id}&scope=bot&permissions={BOT_PERMISSIONS}"
    )


@dataclass(frozen=True)
class Member:
    id: str
    username: str
    global_name: str | None
    nick: str | None

    @property
    def names(self) -> list[str]:
        return [n for n in (self.nick, self.global_name, self.username) if n]

    @property
    def label(self) -> str:
        shown = self.nick or self.global_name or self.username
        return shown if shown == self.username else f"{shown} (@{self.username})"


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    mentionable: bool  # else only a bot with "Mention all roles" can ping it


class DiscordClient:
    def __init__(
        self,
        token: str,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token:
            msg = (
                "Kein Bot-Token: in Claude Desktop unter Einstellungen → Erweiterungen → "
                "AP-Planner eintragen (oder AP_DISCORD_BOT_TOKEN in .env)."
            )
            raise DiscordError(msg)
        self._client = client or httpx.Client(base_url=API, timeout=20.0)
        self._headers = {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:  # noqa: ANN401
        for _ in range(MAX_RETRIES):
            r = self._client.request(method, path, headers=self._headers, **kwargs)
            if r.status_code == 429:  # rate limit: wait as told, then retry
                self._sleep(float(r.json().get("retry_after", 1.0)) + 0.1)
                continue
            if r.status_code >= 400:
                detail = ""
                with contextlib.suppress(ValueError):
                    detail = r.json().get("message", "")
                msg = _ERRORS.get(r.status_code, f"Discord-Fehler {r.status_code}")
                raise DiscordError(f"{msg} ({detail})" if detail else msg, r.status_code)
            return r.json() if r.content else None
        msg = "Discord: zu viele Anfragen, bitte später nochmal."
        raise DiscordError(msg)

    def send(self, channel_id: str, content: str, roles: tuple[str, ...] = ()) -> str:
        """Post a message, returns its id. ``roles``: role ids that may be pinged."""
        data = self._request(
            "POST",
            f"/channels/{channel_id}/messages",
            json={"content": content, "allowed_mentions": allowed_mentions(roles)},
        )
        return str(data["id"])

    def edit(
        self, channel_id: str, message_id: str, content: str, roles: tuple[str, ...] = ()
    ) -> None:
        self._request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            json={"content": content, "allowed_mentions": allowed_mentions(roles)},
        )

    def delete(self, channel_id: str, message_id: str) -> None:
        self._request("DELETE", f"/channels/{channel_id}/messages/{message_id}")

    def dm_channel(self, user_id: str) -> str:
        """Open (or reuse) the direct message channel with a user."""
        data = self._request("POST", "/users/@me/channels", json={"recipient_id": user_id})
        return str(data["id"])

    def me(self) -> dict[str, Any]:
        """The bot user (also checks that the token works)."""
        return self._request("GET", "/users/@me")

    def guilds(self) -> list[dict[str, str]]:
        """Servers the bot was invited to: [{id, name}]."""
        return [
            {"id": str(g["id"]), "name": g["name"]}
            for g in self._request("GET", "/users/@me/guilds")
        ]

    def text_channels(self, guild_id: str) -> list[dict[str, str]]:
        """Text channels of a server: [{id, name}] in Discord's order."""
        chans = sorted(
            (c for c in self._request("GET", f"/guilds/{guild_id}/channels")
             if c.get("type") == TEXT_CHANNEL),
            key=lambda c: c.get("position", 0),
        )  # fmt: skip
        return [{"id": str(c["id"]), "name": c["name"]} for c in chans]

    def roles(self, guild_id: str) -> list[Role]:
        """Roles of a server (without @everyone)."""
        return [
            Role(str(r["id"]), r["name"], bool(r.get("mentionable")))
            for r in self._request("GET", f"/guilds/{guild_id}/roles")
            if str(r["id"]) != guild_id  # @everyone has the id of the server
        ]

    def create_private_thread(self, channel_id: str, name: str) -> str:
        """New private thread in a text channel (only invited members and admins see it)."""
        data = self._request(
            "POST",
            f"/channels/{channel_id}/threads",
            json={
                "name": name[:100],
                "type": PRIVATE_THREAD,
                "invitable": False,
                "auto_archive_duration": THREAD_ARCHIVE_MINUTES,
            },
        )
        return str(data["id"])

    def add_thread_member(self, thread_id: str, user_id: str) -> None:
        self._request("PUT", f"/channels/{thread_id}/thread-members/{user_id}")

    def unarchive(self, thread_id: str) -> None:
        """Reopen a thread Discord archived after a week (writing needs it open)."""
        self._request("PATCH", f"/channels/{thread_id}", json={"archived": False})

    def members(self, guild_id: str) -> list[Member]:
        """All server members (needs the 'Server Members Intent' in the developer portal)."""
        out: list[Member] = []
        after = "0"
        while True:
            page = self._request(
                "GET", f"/guilds/{guild_id}/members", params={"limit": 1000, "after": after}
            )
            for m in page:
                user = m["user"]
                if user.get("bot"):
                    continue
                out.append(
                    Member(
                        str(user["id"]), user["username"], user.get("global_name"), m.get("nick")
                    )
                )
            if len(page) < 1000:
                return out
            after = str(page[-1]["user"]["id"])
