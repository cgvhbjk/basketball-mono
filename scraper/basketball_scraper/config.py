from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supabase_url: str
    supabase_service_key: str

    circuit: Literal["eybl", "eycl", "3ssb", "adidas_gold", "uaa", "uaa_rise", "puma"] = "eybl"
    season: int = 2026
    age_division: Literal["15U", "16U", "17U"] = "17U"
    use_playwright: bool = False

    @field_validator("season")
    @classmethod
    def season_in_range(cls, v: int) -> int:
        if not (2020 <= v <= 2032):
            raise ValueError(f"season {v} is outside expected range 2020–2032")
        return v


settings = Settings()
