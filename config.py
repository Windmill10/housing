from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class Credentials(BaseModel):
    email: str = ""
    password: str = ""


class FilterConfig(BaseModel):
    min_price: int = Field(0, description="Minimum monthly rent (NTD)")
    max_price: int = Field(999999, description="Maximum monthly rent (NTD)")
    num_people: list[int] = Field(default_factory=list, description="Accepted tenant counts (empty = any)")
    keywords: list[str] = Field(default_factory=list, description="Must-contain keywords")
    exclude_keywords: list[str] = Field(default_factory=list, description="Exclude posts with these words")
    only_rental: bool = Field(False, description="Only show 出租 posts, hide 求租")
    max_walk_minutes: int = Field(0, description="Max walking minutes to destination (0 = no limit)")


class CrawlerConfig(BaseModel):
    group_urls: list[str] = Field(
        default_factory=lambda: ["https://www.facebook.com/groups/NTHUallpass"],
        description="Facebook group URLs to crawl",
    )
    max_scrolls: int = Field(200, description="How many times to scroll down per group")
    scroll_pause: float = Field(2.0, description="Seconds to wait between scrolls")
    headless: bool = Field(True, description="Run browser in headless mode")
    save_session: bool = Field(True, description="Save login session for reuse")
    session_dir: str = "session_data"


class MapsConfig(BaseModel):
    api_key: str = Field("", description="Google Maps API key")
    destination: str = Field(
        "國立清華大學台達館, 新竹市東區光復路二段101號",
        description="Destination address for distance calculation",
    )


class AppConfig(BaseModel):
    credentials: Credentials = Field(default_factory=Credentials)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    maps: MapsConfig = Field(default_factory=MapsConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AppConfig:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: str | Path) -> None:
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, allow_unicode=True)
