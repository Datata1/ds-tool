"""Runtime settings, loaded from environment variables (prefix ``AP_``) or ``.env``."""

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AP_", env_file=".env", extra="ignore")

    server: str = "die-staemme.de"
    world: str = ""  # set via `ap init` (.env: AP_WORLD=de260)
    data_dir: Path = Path("data")
    timezone: str = "Europe/Berlin"
    # InnoGames asks to download map data at most once per hour.
    map_cache_seconds: int = 3600
    config_cache_seconds: int = 24 * 3600

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
