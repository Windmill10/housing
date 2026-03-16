from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RentalPost:
    post_id: str
    author: str
    text: str
    timestamp: str
    url: str
    prices: list[int] = field(default_factory=list)
    people_count: Optional[int] = None
    raw_html: str = ""

    @property
    def best_price(self) -> Optional[int]:
        """Return the most likely monthly rent from extracted prices."""
        plausible = [p for p in self.prices if 1000 <= p <= 50000]
        return min(plausible) if plausible else None

    def matches(self, min_price: int, max_price: int, num_people: list[int],
                keywords: list[str], exclude_keywords: list[str]) -> bool:
        price = self.best_price
        if price is not None and not (min_price <= price <= max_price):
            return False
        if price is None and min_price > 0:
            return False
        if num_people and self.people_count is not None:
            if self.people_count not in num_people:
                return False
        text_lower = self.text.lower()
        if keywords and not any(kw.lower() in text_lower for kw in keywords):
            return False
        if exclude_keywords and any(kw.lower() in text_lower for kw in exclude_keywords):
            return False
        return True

    def summary(self) -> str:
        price_str = f"${self.best_price:,}/月" if self.best_price else "價格未知"
        people_str = f"{self.people_count}人" if self.people_count else "人數未知"
        preview = self.text[:120].replace("\n", " ")
        if len(self.text) > 120:
            preview += "..."
        return f"[{price_str}] [{people_str}] {preview}"


# Matches numbers 4+ digits, with or without comma separators
_NUM = r"(\d{1,3}(?:[,，]\d{3})+|\d{4,6})"

PRICE_PATTERNS = [
    # "$5,000/月" or "5000元/月" or "5000/月"
    re.compile(rf"[\$＄]?\s*{_NUM}\s*(?:元|塊)?[/／]月", re.IGNORECASE),
    # "月租 5000" or "租金 5000"
    re.compile(rf"(?:月租|租金|房租)\s*[：:＄$]?\s*{_NUM}", re.IGNORECASE),
    # "5000元" standalone
    re.compile(rf"{_NUM}\s*(?:元|塊|NT|NTD)\s*(?:[/／]月)?", re.IGNORECASE),
    # "5000/month"
    re.compile(r"(\d{4,5})\s*[/／]\s*(?:month|mon|mo)", re.IGNORECASE),
    # Plain 4-5 digit numbers near rent keywords
    re.compile(r"(?:租|rent|價|price)\D{0,10}(\d{4,5})", re.IGNORECASE),
]

PEOPLE_PATTERNS = [
    # "人數：1" "人數】：1人"
    re.compile(r"人數[】\]）)]*\s*[：:]\s*(\d)\s*人?", re.IGNORECASE),
    # "徵1人" "找2位" "限3人"
    re.compile(r"(?:徵|找|限|需|要|收)\s*(\d)\s*(?:人|位|名|個)", re.IGNORECASE),
    # "適合2人" "1人 男" — digit + 人 not followed by 住/住/口 (avoid noise)
    re.compile(r"(?<!\d)(\d)\s*人\s*(?:房|套|雅|男|女|住|入住)?", re.IGNORECASE),
    # "單人" "雙人"
    re.compile(r"(單|雙|三|四)\s*人", re.IGNORECASE),
    # "1 person" "for 2 people"
    re.compile(r"(?:for\s+)?(\d)\s*(?:person|people|ppl)", re.IGNORECASE),
]

CHINESE_NUM = {"單": 1, "雙": 2, "三": 3, "四": 4}


def _parse_number(s: str) -> int:
    return int(s.replace(",", "").replace("，", ""))


def extract_prices(text: str) -> list[int]:
    prices: list[int] = []
    for pattern in PRICE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                prices.append(_parse_number(match.group(1)))
            except (ValueError, IndexError):
                continue
    return sorted(set(prices))


def extract_people_count(text: str) -> Optional[int]:
    for pattern in PEOPLE_PATTERNS:
        m = pattern.search(text)
        if m:
            val = m.group(1)
            if val in CHINESE_NUM:
                return CHINESE_NUM[val]
            try:
                return int(val)
            except ValueError:
                continue
    return None


def parse_post(post_id: str, author: str, text: str, timestamp: str, url: str,
               raw_html: str = "") -> RentalPost:
    return RentalPost(
        post_id=post_id,
        author=author,
        text=text,
        timestamp=timestamp,
        url=url,
        prices=extract_prices(text),
        people_count=extract_people_count(text),
        raw_html=raw_html,
    )
