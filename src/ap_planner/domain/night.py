"""Night bonus window checks (in the server's local time zone)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from ap_planner.models.world import NightBonus


def in_night_bonus(night: NightBonus, when: datetime, tz: str = "Europe/Berlin") -> bool:
    if not night.active:
        return False
    hour = when.astimezone(ZoneInfo(tz)).hour
    if night.start_hour <= night.end_hour:
        return night.start_hour <= hour < night.end_hour
    return hour >= night.start_hour or hour < night.end_hour
