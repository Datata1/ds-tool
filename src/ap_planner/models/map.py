"""Map entities parsed from ``/map/*.txt.gz``."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_serializer, model_validator


class Coord(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int
    y: int

    @model_validator(mode="before")
    @classmethod
    def _from_text(cls, v: object) -> object:
        """Accept "500|500" as well as {"x": 500, "y": 500}."""
        if isinstance(v, str):
            x_str, y_str = v.strip().strip("()").split("|")
            return {"x": int(x_str), "y": int(y_str)}
        return v

    @model_serializer(mode="plain")
    def _to_text(self) -> str:
        return f"{self.x}|{self.y}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse ``"500|500"`` (also tolerates surrounding text / parentheses)."""
        cleaned = text.strip().strip("()")
        x_str, y_str = cleaned.split("|")
        return cls(x=int(x_str), y=int(y_str))

    @property
    def continent(self) -> str:
        return f"K{self.y // 100}{self.x // 100}"

    def __str__(self) -> str:
        return f"{self.x}|{self.y}"


class Village(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    x: int
    y: int
    player_id: int  # 0 = barbarian
    points: int
    bonus: int

    @property
    def coord(self) -> Coord:
        return Coord(x=self.x, y=self.y)


class Player(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    ally_id: int  # 0 = no tribe
    villages: int
    points: int
    rank: int


class Ally(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    tag: str
    members: int
    villages: int
    points: int
    all_points: int
    rank: int
