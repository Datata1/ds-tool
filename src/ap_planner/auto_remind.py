"""Automatic Discord reminders while the desktop app (its local server) is running.

A background thread calls one ``check`` function every few minutes. Nothing runs when the
app is closed: reminders already sent stay in Discord, new ones need the app to be open.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class CheckResult:
    """What one check did: messages sent (player names) and whether there is work left."""

    sent: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    finished: bool = False  # nothing left to remind (all sends are long over)


@dataclass
class ReminderState:
    started: datetime
    interval_min: float
    minutes: float
    running: bool = True
    last_check: datetime | None = None
    next_check: datetime | None = None
    log: list[str] = field(default_factory=list)  # newest first
    stop_reason: str = ""


class AutoReminder:
    """Runs ``check`` every ``interval_min`` minutes until stopped or finished."""

    def __init__(
        self,
        check: Callable[[], CheckResult],
        *,
        interval_min: float,
        minutes: float,
        tz_label: Callable[[datetime], str],
    ) -> None:
        self._check = check
        self._label = tz_label
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.state = ReminderState(datetime.now(UTC), interval_min, minutes)
        self._thread = threading.Thread(target=self._run, daemon=True, name="auto-remind")

    def start(self) -> None:
        self._thread.start()

    def stop(self, reason: str = "beendet") -> None:
        with self._lock:
            if self.state.running:
                self.state.running = False
                self.state.stop_reason = reason
                self.state.next_check = None
        self._stop.set()

    @property
    def running(self) -> bool:
        return self.state.running

    def _note(self, text: str) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self.state.log.insert(0, f"{self._label(now)} {text}")
            del self.state.log[30:]

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self._check()
            except Exception as err:  # keep running, show the problem
                result = CheckResult(errors=[str(err)])
            now = datetime.now(UTC)
            with self._lock:
                self.state.last_check = now
                self.state.next_check = now + timedelta(minutes=self.state.interval_min)
            if result.sent:
                self._note("erinnert: " + ", ".join(result.sent))
            for err in result.errors:
                self._note(f"Fehler: {err}")
            if result.finished:
                self.stop("alle Abschickzeiten sind vorbei")
                self._note("fertig - alle Abschickzeiten sind vorbei")
                return
            self._stop.wait(self.state.interval_min * 60)
