"""SQLite persistence for one world (``data/<world>/world.sqlite``)."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ap_planner.config import Settings
from ap_planner.ingest import parse
from ap_planner.models.map import Ally, Coord, Player, Village
from ap_planner.models.troops import TroopSnapshot, VillageTroops
from ap_planner.models.world import WorldConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS villages (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL,
    player_id INTEGER NOT NULL, points INTEGER NOT NULL, bonus INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_villages_xy ON villages(x, y);
CREATE INDEX IF NOT EXISTS idx_villages_player ON villages(player_id);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, ally_id INTEGER NOT NULL,
    villages INTEGER NOT NULL, points INTEGER NOT NULL, rank INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS allies (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, tag TEXT NOT NULL, members INTEGER NOT NULL,
    villages INTEGER NOT NULL, points INTEGER NOT NULL, all_points INTEGER NOT NULL,
    rank INTEGER NOT NULL
);
-- Latest known troops per village (one row per village, replaced on import).
CREATE TABLE IF NOT EXISTS troops (
    x INTEGER NOT NULL, y INTEGER NOT NULL, village_id INTEGER, name TEXT NOT NULL,
    units TEXT NOT NULL, outgoing INTEGER NOT NULL, incoming INTEGER NOT NULL,
    extra TEXT NOT NULL, source TEXT NOT NULL, captured_at TEXT NOT NULL,
    PRIMARY KEY (x, y)
);
"""


class WorldStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    @classmethod
    def open(cls, settings: Settings) -> "WorldStore":
        return cls(settings.db_path)

    def close(self) -> None:
        self.conn.close()

    # --- writes -------------------------------------------------------------
    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def replace_map(
        self, villages: Iterable[Village], players: Iterable[Player], allies: Iterable[Ally]
    ) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM villages")
            self.conn.execute("DELETE FROM players")
            self.conn.execute("DELETE FROM allies")
            self.conn.executemany(
                "INSERT INTO villages VALUES (:id,:name,:x,:y,:player_id,:points,:bonus)",
                (v.model_dump() for v in villages),
            )
            self.conn.executemany(
                "INSERT INTO players VALUES (:id,:name,:ally_id,:villages,:points,:rank)",
                (p.model_dump() for p in players),
            )
            self.conn.executemany(
                "INSERT INTO allies VALUES "
                "(:id,:name,:tag,:members,:villages,:points,:all_points,:rank)",
                (a.model_dump() for a in allies),
            )
            self._set_meta("map_synced_at", datetime.now(UTC).isoformat())

    def save_world_config(self, config: WorldConfig) -> None:
        with self.conn:
            self._set_meta("world_config", config.model_dump_json())

    def load_raw(self, raw_dir: Path, world: str) -> None:
        """(Re)build the database from the raw files downloaded by ``WorldClient``."""
        self.save_world_config(
            parse.parse_world_config(
                world, (raw_dir / "config.xml").read_bytes(), (raw_dir / "units.xml").read_bytes()
            )
        )
        self.replace_map(
            parse.parse_villages((raw_dir / "village.txt.gz").read_bytes()),
            parse.parse_players((raw_dir / "player.txt.gz").read_bytes()),
            parse.parse_allies((raw_dir / "ally.txt.gz").read_bytes()),
        )

    def save_troops(self, snapshot: TroopSnapshot) -> list[VillageTroops]:
        """Store a snapshot, resolving village ids from the map. Returns stored rows."""
        stored: list[VillageTroops] = []
        with self.conn:
            for vt in snapshot.villages:
                village = self.village_at(vt.coord)
                row = vt.model_copy(update={"village_id": village.id if village else None})
                self.conn.execute(
                    "INSERT OR REPLACE INTO troops VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        row.coord.x,
                        row.coord.y,
                        row.village_id,
                        row.name,
                        json.dumps({u.value: n for u, n in row.units.items()}),
                        row.outgoing,
                        row.incoming,
                        json.dumps(row.extra),
                        snapshot.source,
                        snapshot.captured_at.isoformat(),
                    ),
                )
                stored.append(row)
        return stored

    # --- reads --------------------------------------------------------------
    def meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def world_config(self) -> WorldConfig:
        raw = self.meta("world_config")
        if raw is None:
            msg = "World config missing - run `ap sync` first."
            raise LookupError(msg)
        return WorldConfig.model_validate_json(raw)

    def village(self, village_id: int) -> Village | None:
        row = self.conn.execute("SELECT * FROM villages WHERE id = ?", (village_id,)).fetchone()
        return None if row is None else Village(**dict(row))

    def village_at(self, coord: Coord) -> Village | None:
        row = self.conn.execute(
            "SELECT * FROM villages WHERE x = ? AND y = ?", (coord.x, coord.y)
        ).fetchone()
        return None if row is None else Village(**dict(row))

    def villages_of_player(self, player_id: int) -> list[Village]:
        rows = self.conn.execute("SELECT * FROM villages WHERE player_id = ?", (player_id,))
        return [Village(**dict(r)) for r in rows]

    def villages_of_ally(self, ally_id: int) -> list[Village]:
        rows = self.conn.execute(
            "SELECT v.* FROM villages v JOIN players p ON p.id = v.player_id WHERE p.ally_id = ?",
            (ally_id,),
        )
        return [Village(**dict(r)) for r in rows]

    def villages_in_radius(self, center: Coord, radius: float) -> list[Village]:
        r = int(radius) + 1
        rows = self.conn.execute(
            "SELECT * FROM villages WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ?",
            (center.x - r, center.x + r, center.y - r, center.y + r),
        )
        out = [Village(**dict(row)) for row in rows]
        return [v for v in out if (v.x - center.x) ** 2 + (v.y - center.y) ** 2 <= radius * radius]

    def player_by_name(self, name: str) -> Player | None:
        row = self.conn.execute(
            "SELECT * FROM players WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        return None if row is None else Player(**dict(row))

    def player(self, player_id: int) -> Player | None:
        row = self.conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        return None if row is None else Player(**dict(row))

    def ally_by_tag(self, tag: str) -> Ally | None:
        row = self.conn.execute(
            "SELECT * FROM allies WHERE tag = ? COLLATE NOCASE OR name = ? COLLATE NOCASE",
            (tag, tag),
        ).fetchone()
        return None if row is None else Ally(**dict(row))

    def members_of_ally(self, ally_id: int) -> list[Player]:
        rows = self.conn.execute(
            "SELECT * FROM players WHERE ally_id = ? ORDER BY points DESC", (ally_id,)
        )
        return [Player(**dict(r)) for r in rows]

    def troops(self) -> list[tuple[VillageTroops, str, str]]:
        """All stored troops as (troops, source, captured_at)."""
        rows = self.conn.execute("SELECT * FROM troops ORDER BY y, x")
        return [
            (
                VillageTroops(
                    coord=Coord(x=r["x"], y=r["y"]),
                    name=r["name"],
                    village_id=r["village_id"],
                    units=json.loads(r["units"]),
                    outgoing=r["outgoing"],
                    incoming=r["incoming"],
                    extra=json.loads(r["extra"]),
                ),
                str(r["source"]),
                str(r["captured_at"]),
            )
            for r in rows
        ]
