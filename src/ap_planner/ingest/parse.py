"""Pure parsers for the public world data files (no I/O besides bytes in)."""

import csv
import gzip
import io
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from urllib.parse import unquote_plus

from ap_planner.models.map import Ally, Player, Village
from ap_planner.models.world import NightBonus, Unit, UnitInfo, WorldConfig


def _text(root: ET.Element, path: str, default: str = "0") -> str:
    node = root.find(path)
    if node is None or node.text is None or node.text.strip() == "":
        return default
    return node.text.strip()


def parse_unit_info(xml_bytes: bytes) -> dict[Unit, UnitInfo]:
    root = ET.fromstring(xml_bytes)
    units: dict[Unit, UnitInfo] = {}
    for node in root:
        try:
            unit = Unit(node.tag)
        except ValueError:
            continue
        units[unit] = UnitInfo(
            unit=unit,
            pop=int(_text(node, "pop")),
            speed=float(_text(node, "speed")),
            attack=int(_text(node, "attack")),
            defense=int(_text(node, "defense")),
            defense_cavalry=int(_text(node, "defense_cavalry")),
            defense_archer=int(_text(node, "defense_archer")),
            carry=int(_text(node, "carry")),
            build_time=float(_text(node, "build_time")),
        )
    return units


def parse_world_config(world: str, config_xml: bytes, unit_xml: bytes) -> WorldConfig:
    root = ET.fromstring(config_xml)
    return WorldConfig(
        world=world,
        speed=float(_text(root, "speed", "1")),
        unit_speed=float(_text(root, "unit_speed", "1")),
        moral=int(_text(root, "moral")),
        millis_arrival=_text(root, "commands/millis_arrival") == "1",
        attack_gap_ms=int(_text(root, "commands/attack_gap")),
        knight=_text(root, "game/knight") != "0",
        archer=_text(root, "game/archer") != "0",
        church=_text(root, "game/church") != "0",
        watchtower=_text(root, "game/watchtower") != "0",
        fake_limit_pct=float(_text(root, "game/fake_limit")),
        snob_max_dist=int(_text(root, "snob/max_dist", "0")),
        night=NightBonus(
            active=_text(root, "night/active") == "1",
            start_hour=int(_text(root, "night/start_hour")),
            end_hour=int(_text(root, "night/end_hour")),
            def_factor=float(_text(root, "night/def_factor", "2")),
        ),
        newbie_ratio=float(_text(root, "newbie/ratio")),
        newbie_ratio_days=int(_text(root, "newbie/ratio_days")),
        units=parse_unit_info(unit_xml),
    )


def _rows(gz_bytes: bytes) -> Iterator[list[str]]:
    text = gzip.decompress(gz_bytes).decode("utf-8")
    yield from csv.reader(io.StringIO(text))


def parse_villages(gz_bytes: bytes) -> list[Village]:
    return [
        Village(
            id=int(r[0]),
            name=unquote_plus(r[1]),
            x=int(r[2]),
            y=int(r[3]),
            player_id=int(r[4]),
            points=int(r[5]),
            bonus=int(r[6]),
        )
        for r in _rows(gz_bytes)
        if r
    ]


def parse_players(gz_bytes: bytes) -> list[Player]:
    return [
        Player(
            id=int(r[0]),
            name=unquote_plus(r[1]),
            ally_id=int(r[2]),
            villages=int(r[3]),
            points=int(r[4]),
            rank=int(r[5]),
        )
        for r in _rows(gz_bytes)
        if r
    ]


def parse_allies(gz_bytes: bytes) -> list[Ally]:
    return [
        Ally(
            id=int(r[0]),
            name=unquote_plus(r[1]),
            tag=unquote_plus(r[2]),
            members=int(r[3]),
            villages=int(r[4]),
            points=int(r[5]),
            all_points=int(r[6]),
            rank=int(r[7]),
        )
        for r in _rows(gz_bytes)
        if r
    ]
