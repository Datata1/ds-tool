"""Download public world data with a polite on-disk cache.

Only public, unauthenticated endpoints are used. This module never touches
game pages that require a login.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ap_planner import __version__
from ap_planner.config import Settings

USER_AGENT = f"ap-planner/{__version__} (private attack-planning tool)"

CONFIG_FILES: dict[str, str] = {
    "config.xml": "/interface.php?func=get_config",
    "units.xml": "/interface.php?func=get_unit_info",
}
MAP_FILES: dict[str, str] = {
    "village.txt.gz": "/map/village.txt.gz",
    "player.txt.gz": "/map/player.txt.gz",
    "ally.txt.gz": "/map/ally.txt.gz",
}


@dataclass(frozen=True)
class FetchResult:
    name: str
    path: Path
    downloaded: bool


class WorldClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(
            base_url=settings.world_url,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def _fetch(self, name: str, url: str, max_age: int, *, force: bool) -> FetchResult:
        path = self.settings.raw_dir / name
        if not force and path.exists() and time.time() - path.stat().st_mtime < max_age:
            return FetchResult(name, path, downloaded=False)
        response = self._client.get(url)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(response.content)
        tmp.replace(path)
        return FetchResult(name, path, downloaded=True)

    def fetch_all(self, *, force: bool = False) -> list[FetchResult]:
        results = [
            self._fetch(n, u, self.settings.config_cache_seconds, force=force)
            for n, u in CONFIG_FILES.items()
        ]
        results += [
            self._fetch(n, u, self.settings.map_cache_seconds, force=force)
            for n, u in MAP_FILES.items()
        ]
        return results
