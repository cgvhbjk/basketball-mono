"""
Pydantic models for scraped basketball data.
These are the scraper's internal representations — not 1:1 with DB columns.
"""
import re
from typing import Literal, Optional
from pydantic import BaseModel, field_validator, model_validator


AgeDivision = Literal["15U", "16U", "17U"]


class CircuitRef(BaseModel):
    name: str
    org: str
    gender: Literal["boys", "girls"]


class Team(BaseModel):
    source_id: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None
    age_division: AgeDivision
    season: int


class RosterEntry(BaseModel):
    source_team_id: str
    source_player_id: str
    jersey_number: Optional[str] = None
    position: Optional[str] = None


class Player(BaseModel):
    source_id: str
    first_name: str
    last_name: str
    height_raw: Optional[str] = None
    height_inches: Optional[int] = None
    weight_lbs: Optional[int] = None
    grad_year: Optional[int] = None
    hometown: Optional[str] = None
    high_school: Optional[str] = None
    position: Optional[str] = None
    star_rating: Optional[int] = None
    national_rank: Optional[int] = None
    state_rank: Optional[int] = None

    @model_validator(mode="after")
    def normalize_height(self) -> "Player":
        if self.height_raw and self.height_inches is None:
            self.height_inches = _parse_height(self.height_raw)
        return self

    @field_validator("grad_year", mode="before")
    @classmethod
    def coerce_grad_year(cls, v: object) -> Optional[int]:
        if v is None:
            return None
        year = int(str(v).strip())
        if not (2024 <= year <= 2032):
            raise ValueError(f"grad_year {year} outside expected range 2024–2032")
        return year


class SeasonStats(BaseModel):
    source_player_id: str
    source_team_id: str
    season: int
    age_division: Optional[AgeDivision] = None
    games_played: Optional[int] = None
    ppg: Optional[float] = None
    rpg: Optional[float] = None
    apg: Optional[float] = None
    spg: Optional[float] = None
    bpg: Optional[float] = None
    fg_pct: Optional[float] = None
    three_pt_pct: Optional[float] = None

    @field_validator("fg_pct", "three_pt_pct", mode="before")
    @classmethod
    def normalize_pct(cls, v: object) -> Optional[float]:
        """Accept either 0–1 or 0–100 format; store as 0–1."""
        if v is None:
            return None
        val = float(str(v).replace("%", "").strip())
        return val / 100 if val > 1 else val


def _parse_height(raw: str) -> Optional[int]:
    """Convert '6-3', '6'3"', '6 3', '75' to total inches."""
    raw = raw.strip()
    # already pure inches
    if re.fullmatch(r"\d{2}", raw):
        return int(raw)
    m = re.match(r"(\d+)['\-\s](\d+)", raw)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None
