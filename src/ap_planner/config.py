"""Runtime settings, loaded from environment variables (prefix ``AP_``) or ``.env``."""

import os
from functools import cached_property
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def app_home() -> Path:
    """Folder with ``.env`` and ``data/`` (the player's working folder).

    1. ``AP_HOME`` (set by the Claude Desktop extension, e.g. ``~/Documents/ap-planner``)
    2. the current folder, if it already looks like one (Claude Code / CLI in the project)
    3. ``~/ap-planner`` (Claude Desktop with a hand-written config starts in ``/``)
    """
    env = os.environ.get("AP_HOME", "").strip()
    if env.startswith("${"):  # unfilled option of the Claude plugin/extension
        env = ""
    if env:
        home = Path(env).expanduser()
    elif Path(".env").exists() or Path("data").is_dir():
        return Path.cwd()
    else:
        home = Path.home() / "ap-planner"
    home.mkdir(parents=True, exist_ok=True)
    return home.resolve()


class Settings(BaseSettings):
    # env_ignore_empty: an empty extension field (AP_DISCORD_BOT_TOKEN="") must not hide .env
    model_config = SettingsConfigDict(
        env_prefix="AP_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    server: str = "die-staemme.de"
    world: str = ""  # set via `ap init` (.env: AP_WORLD=de260)
    data_dir: Path = Path("data")
    timezone: str = "Europe/Berlin"
    # InnoGames asks to download map data at most once per hour.
    map_cache_seconds: int = 3600
    config_cache_seconds: int = 24 * 3600
    # Discord bot token (.env: AP_DISCORD_BOT_TOKEN=...). Never commit it.
    discord_bot_token: str = ""
    # DS Ultimate attack planner API key (.env: AP_DSU_API_KEY=...). Personal, never share it.
    # Without it, plans are created through the normal web page.
    dsu_api_key: str = ""
    # Google login for the desktop app (default: the client built into the release).
    google_client_id: str = ""
    google_client_secret: str = ""

    @field_validator("discord_bot_token", "dsu_api_key", mode="before")
    @classmethod
    def _unfilled_option(cls, value: object) -> object:
        """Claude may pass an empty plugin option as the literal "${user_config.x}"."""
        return "" if isinstance(value, str) and value.startswith("${") else value

    @cached_property
    def world_url(self) -> str:
        return f"https://{self.world}.{self.server}"

    @property
    def world_dir(self) -> Path:
        return self.data_dir / self.world

    @property
    def db_path(self) -> Path:
        return self.world_dir / "world.sqlite"

    @property
    def raw_dir(self) -> Path:
        return self.world_dir / "raw"
