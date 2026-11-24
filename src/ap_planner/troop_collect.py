"""Collect troop tables from the tribe: who is done, who is still missing.

The player copies each member's troop page in the game (Ctrl+A, Ctrl+C) himself. We only
read the clipboard (or pasted text), parse the table and assign the villages to players via
the public map data. Nothing here opens game pages (no botting).
"""

import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ap_planner.ingest.store import WorldStore
from ap_planner.ingest.troops.overview_text import ROW_RE
from ap_planner.ingest.troops.script_json import looks_like_script_json
from ap_planner.models.troops import VillageTroops
from ap_planner.services import import_overview_text, owner_name


@dataclass(frozen=True)
class PlayerStatus:
    name: str
    villages: int  # villages on the map
    fresh: int  # villages with troop data captured since the cut-off
    oldest: datetime | None  # oldest troop data of this player (None = never imported)
    with_data: int = 0  # villages with troop data of any age

    @property
    def done(self) -> bool:
        return self.villages > 0 and self.fresh >= self.villages


@dataclass(frozen=True)
class CollectStatus:
    players: list[PlayerStatus]

    @property
    def done(self) -> list[PlayerStatus]:
        return [p for p in self.players if p.done]

    @property
    def missing(self) -> list[PlayerStatus]:
        return [p for p in self.players if not p.done]


@dataclass(frozen=True)
class PasteResult:
    rows: list[VillageTroops]
    by_owner: dict[str, int] = field(default_factory=dict)
    unknown: list[VillageTroops] = field(default_factory=list)  # not on the map


def tribe_members(store: WorldStore, tribes: list[str]) -> list[tuple[str, int]]:
    """(name, player id) of all members of the given tribe tags."""
    out: dict[int, str] = {}
    for tag in tribes:
        ally = store.ally_by_tag(tag)
        if ally is not None:
            out.update({p.id: p.name for p in store.members_of_ally(ally.id)})
    return sorted(((n, i) for i, n in out.items()), key=lambda t: t[0].lower())


def status(store: WorldStore, tribes: list[str], since: datetime) -> CollectStatus:
    """Per member: how many villages have troop data newer than ``since``."""
    captured: dict[int, datetime] = {}
    for vt, _src, at in store.troops():
        if vt.village_id is not None:
            captured[vt.village_id] = datetime.fromisoformat(at)
    players: list[PlayerStatus] = []
    for name, pid in tribe_members(store, tribes):
        ids = [v.id for v in store.villages_of_player(pid)]
        times = [captured[i] for i in ids if i in captured]
        players.append(
            PlayerStatus(
                name=name,
                villages=len(ids),
                fresh=sum(t >= since for t in times),
                oldest=min(times) if len(times) == len(ids) and times else None,
                with_data=len(times),
            )
        )
    return CollectStatus(players)


def owner_counts(store: WorldStore, rows: list[VillageTroops]) -> PasteResult:
    by_owner: dict[str, int] = {}
    for v in rows:
        if v.village_id is None:
            continue
        name = owner_name(store, v.village_id)
        by_owner[name] = by_owner.get(name, 0) + 1
    return PasteResult(rows, by_owner, [v for v in rows if v.village_id is None])


def import_paste(store: WorldStore, text: str) -> PasteResult:
    """Parse and store one pasted troop table. Raises ValueError if it is none."""
    return owner_counts(store, import_overview_text(store, text))


def looks_like_troops(text: str) -> bool:
    """Cheap check before parsing: at least one 'Name (x|y) Kxx' row with numbers, or the
    export of our in-game script."""
    if looks_like_script_json(text):
        return True
    return any(
        (m := ROW_RE.match(line.strip())) and any(c.isdigit() for c in m["rest"])
        for line in text.splitlines()
    )


# Windows: PowerShell prints UTF-8 only when told so (village names have umlauts).
_WIN_PASTE = [
    "powershell", "-NoProfile", "-NonInteractive", "-Command",
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Clipboard -Raw",
]  # fmt: skip


def clipboard_command(platform: str = sys.platform) -> list[str] | None:
    """Command that prints the clipboard text, None if no tool is available."""
    if platform == "win32":
        return _WIN_PASTE
    if platform == "darwin":
        return ["pbpaste"]
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        return ["wl-paste", "--no-newline"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"]
    return None


def read_clipboard() -> str | None:
    """Current clipboard text (Windows/macOS/X11/Wayland), None if not possible."""
    cmd = clipboard_command()
    if cmd is None:
        return None
    env = {**os.environ, "LANG": "en_US.UTF-8"} if sys.platform == "darwin" else None
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=10,
            check=False,
            env=env,
            # no console window popping up when started from Claude Desktop on Windows
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return ""
    return r.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")


def age_text(captured: datetime, now: datetime | None = None) -> str:
    """Short German age like '35 min', '5 h', '2 T'."""
    delta = (now or datetime.now(UTC)) - captured
    if delta < timedelta(hours=1):
        return f"{max(0, int(delta.total_seconds() // 60))} min"
    if delta < timedelta(days=2):
        return f"{int(delta.total_seconds() // 3600)} h"
    return f"{delta.days} T"


@dataclass
class CollectProgress:
    """What a running background collection has done so far."""

    started: datetime
    until: datetime
    running: bool = True
    pages: int = 0  # imported copies
    villages: int = 0
    by_owner: dict[str, int] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)  # coords not on the map
    errors: list[str] = field(default_factory=list)
    stop_reason: str = ""


class ClipboardCollector:
    """Background collection: every new troop page in the clipboard is imported at once.

    The player copies one troop page after the other (Ctrl+A, Ctrl+C) without waiting for
    Claude. Stops on ``stop()``, after ``minutes`` or when all members of ``tribes`` have fresh
    data. The text that is in the clipboard at the start is ignored (could be old). Uses its
    own database connection (SQLite connections belong to one thread).
    """

    def __init__(
        self,
        open_store: Callable[[], WorldStore],
        *,
        tribes: list[str],
        log_path: Path,
        read: Callable[[], str | None] = read_clipboard,
        interval: float = 0.8,
    ) -> None:
        self._open_store = open_store
        self._tribes = tribes
        self._log_path = log_path
        self._read = read
        self._interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._initial = ""
        self.progress: CollectProgress | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, minutes: float) -> CollectProgress:
        initial = self._read()
        if initial is None:
            msg = "Kein Zugriff auf die Zwischenablage."
            raise RuntimeError(msg)
        self._initial = initial  # copied before the start: ignored, could be old
        now = datetime.now(UTC)
        self.progress = CollectProgress(started=now, until=now + timedelta(minutes=minutes))
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="troop-collector", daemon=True)
        self._thread.start()
        return self.progress

    def stop(self, reason: str = "beendet") -> CollectProgress | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        with self._lock:
            if self.progress is not None and self.progress.running:
                self.progress.running = False
                self.progress.stop_reason = reason
        return self.progress

    def snapshot(self) -> CollectProgress | None:
        with self._lock:
            p = self.progress
            if p is None:
                return None
            # copies: the collector thread keeps changing the original
            return replace(
                p, by_owner=dict(p.by_owner), unknown=list(p.unknown), errors=list(p.errors)
            )

    def _finish(self, reason: str) -> None:
        with self._lock:
            assert self.progress is not None
            self.progress.running = False
            self.progress.stop_reason = reason

    def _run(self) -> None:
        assert self.progress is not None
        store = self._open_store()
        last = self._initial
        while not self._stop.wait(self._interval):
            if datetime.now(UTC) >= self.progress.until:
                self._finish("Zeit abgelaufen")
                return
            text = self._read()
            if not text or text == last:
                continue
            last = text
            if not looks_like_troops(text):
                continue
            try:
                result = import_paste(store, text)
            except ValueError as err:
                with self._lock:
                    self.progress.errors.append(str(err))
                continue
            self._log(text)
            with self._lock:
                p = self.progress
                p.pages += 1
                p.villages += len(result.rows)
                for name, n in result.by_owner.items():
                    p.by_owner[name] = p.by_owner.get(name, 0) + n
                p.unknown += [str(v.coord) for v in result.unknown]
            if self._tribes and not status(store, self._tribes, self.progress.started).missing:
                self._finish("alle Spieler da")
                return

    def _log(self, text: str) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n\n")
        except OSError:
            pass  # the copy is only a backup
