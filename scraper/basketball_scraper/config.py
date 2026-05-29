"""
Scraper settings — loaded from .env via pydantic-settings.

The men's pipeline is boys-only; do not add a gender field here.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Literal


# Keep this list in sync with `circuits` in main.py's REGISTRY.
CIRCUIT_KEYS = (
    "eybl",
    "eycl",
    "3ssb",
    "adidas_gold",
    "uaa",
    "uaa_rise",
    "hoop_group",
    "made_hoops",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supabase_url: str
    supabase_service_key: str

    circuit: Literal[
        "eybl", "eycl", "3ssb", "adidas_gold", "uaa", "uaa_rise",
        "hoop_group", "made_hoops",
    ] = "eybl"
    season: int = 2026
    age_division: Literal["15U", "16U", "17U"] = "17U"
    use_playwright: bool = False

    # Raw HTTP/JSON payloads are content-addressed and written under
    # SCRAPER_SNAPSHOT_DIR (defaults to ./snapshots) when enabled.
    enable_snapshots: bool = True

    @field_validator("season")
    @classmethod
    def season_in_range(cls, v: int) -> int:
        if not (2020 <= v <= 2032):
            raise ValueError(f"season {v} is outside expected range 2020–2032")
        return v


_settings: Settings | None = None


def __getattr__(name: str):
    # Lazy `settings` so importing CIRCUIT_KEYS (e.g. from cli.py at argparse-
    # build time) doesn't instantiate Settings and pin values from .env BEFORE
    # the CLI has had a chance to overlay env vars from its flags.
    if name == "settings":
        global _settings
        if _settings is None:
            _settings = Settings()
        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
