"""Discord settings per world (``data/<world>/discord.yaml``). The bot token is in .env."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Channel aliases used by the tool.
CHANNELS = ("review", "ankuendigung", "befehle")


class DiscordConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guild_id: str | None = None
    # alias -> channel id, e.g. {"review": "123…", "ankuendigung": "456…", "befehle": "789…"}
    # "befehle": channel that holds one private thread per player.
    kanaele: dict[str, str] = Field(default_factory=dict)
    # DS player name -> Discord user ids. A DS account is often played by several people:
    # all of them are added to the private thread (or get a direct message each).
    spieler: dict[str, list[str]] = Field(default_factory=dict)
    # DS player name -> id of their private thread (reused for every operation)
    threads: dict[str, str] = Field(default_factory=dict)
    # Stammes-Tag (eigener Stamm + Wing) -> id of the Discord role with that name. Read from
    # the server, never hard-coded; these roles are pinged in the public announcement.
    rollen: dict[str, str] = Field(default_factory=dict)

    @field_validator("spieler", mode="before")
    @classmethod
    def _one_or_many(cls, value: object) -> object:
        """Older files store one id per player; also accept "id1, id2"."""
        if not isinstance(value, dict):
            return value
        return {name: user_ids(ids) for name, ids in value.items()}


def user_ids(value: str | int | list[str] | list[int] | None) -> list[str]:
    """Discord user ids from one id, a comma/space separated string or a list (no duplicates)."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        for part in str(item).replace(",", " ").split():
            if part not in out:
                out.append(part)
    return out
