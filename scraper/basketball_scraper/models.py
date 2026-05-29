"""
Pydantic models for scraped basketball data.

These are the scraper's internal representations — not 1:1 with DB columns.
The men's pipeline is boys-only; do NOT add girls-specific fields here.
"""
import re
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, field_validator, model_validator


AgeDivision = Literal["15U", "16U", "17U"]


# ----------------------------------------------------------------
# Core entities
# ----------------------------------------------------------------

class Team(BaseModel):
    source_id: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None
    age_division: AgeDivision
    season: int
    wins: Optional[int] = None
    losses: Optional[int] = None


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
    date_of_birth: Optional[date] = None
    nationality: Optional[str] = None

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
        try:
            year = int(str(v).strip())
        except (ValueError, TypeError):
            return None
        if not (2024 <= year <= 2032):
            return None
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
    ft_pct: Optional[float] = None
    fga: Optional[float] = None
    oreb: Optional[float] = None
    dreb: Optional[float] = None
    tpg: Optional[float] = None
    fta: Optional[float] = None
    mpg: Optional[float] = None
    fpg: Optional[float] = None
    three_pm_pg: Optional[float] = None
    three_pa_pg: Optional[float] = None
    fgm_pg: Optional[float] = None
    ftm_pg: Optional[float] = None
    plus_minus: Optional[float] = None
    events_played: Optional[int] = None

    @field_validator("fg_pct", "three_pt_pct", "ft_pct", mode="before")
    @classmethod
    def normalize_pct(cls, v: object) -> Optional[float]:
        """Accept either 0–1 or 0–100 format; store as 0–1."""
        if v is None:
            return None
        val = float(str(v).replace("%", "").strip())
        return val / 100 if val > 1 else val


# ----------------------------------------------------------------
# Event / game / box-score entities (new normalized schema)
# Adapters that expose schedule data populate these in addition to the
# season-aggregate stats above.
# ----------------------------------------------------------------

class Event(BaseModel):
    source_id: str
    circuit: str
    name: str
    location: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class Game(BaseModel):
    source_id: str
    source_event_id: Optional[str] = None
    source_home_team_id: Optional[str] = None
    source_away_team_id: Optional[str] = None
    home_team_name: Optional[str] = None
    away_team_name: Optional[str] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    played_at: Optional[datetime] = None
    status: Optional[str] = None


class BoxScore(BaseModel):
    source_game_id: str
    source_player_id: str
    source_team_id: str
    minutes: Optional[float] = None
    points: Optional[int] = None
    rebounds: Optional[int] = None
    offensive_rebounds: Optional[int] = None
    defensive_rebounds: Optional[int] = None
    assists: Optional[int] = None
    steals: Optional[int] = None
    blocks: Optional[int] = None
    turnovers: Optional[int] = None
    fouls: Optional[int] = None
    fgm: Optional[int] = None
    fga: Optional[int] = None
    three_pm: Optional[int] = None
    three_pa: Optional[int] = None
    ftm: Optional[int] = None
    fta: Optional[int] = None


def _parse_height(raw: str) -> Optional[int]:
    """Convert '6-3', '6'3"', '6 3', '75' to total inches."""
    raw = raw.strip()
    if re.fullmatch(r"\d{2}", raw):
        return int(raw)
    m = re.match(r"(\d+)['\-\s](\d+)", raw)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None
