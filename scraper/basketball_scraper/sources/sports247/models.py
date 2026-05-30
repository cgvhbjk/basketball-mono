"""
Normalized output models for the 247Sports profile extractor.

These extend the project-wide `models.Player` shape (which the scraper writes
to Supabase) with public-recruiting fields we capture but don't yet promote
into the DB: position_rank, composite_rating, offers/visits counts,
commitment status. Those live in the JSONL audit trail until a follow-up
migration adds columns.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


StarsSource = Literal["icons", "composite_threshold", "unknown"]


class Hometown(BaseModel):
    city: Optional[str] = None
    state: Optional[str] = None  # USPS two-letter code


class ProfileExtract(BaseModel):
    """A single parsed 247Sports recruiting profile.

    All fields except `source_url`, `player_id`, `name`, `stars_source`, and
    `extracted_at` are nullable because public pages routinely omit values
    (em-dashes for unranked players, missing weight, etc.).
    """
    source_url: str
    player_id: str
    name: str

    national_rank: Optional[int] = None
    state_rank: Optional[int] = None
    position_rank: Optional[int] = None

    class_year: Optional[int] = None
    hometown: Optional[Hometown] = None
    high_school: Optional[str] = None
    position: Optional[str] = None

    stars: Optional[int] = None
    stars_source: StarsSource = "unknown"
    composite_rating: Optional[float] = None

    height_inches: Optional[int] = None
    height_raw: Optional[str] = None
    weight_lbs: Optional[int] = None

    offers_count: Optional[int] = None
    visits_count: Optional[int] = None
    commitment_team: Optional[str] = None
    commitment_status: Optional[str] = None

    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
