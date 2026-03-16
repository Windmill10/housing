"""Calculate walking/biking distance from rental locations to a destination using Google Maps."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import googlemaps
from rich.console import Console
from rich.progress import Progress

console = Console()

DESTINATION_DEFAULT = "國立清華大學台達館, 新竹市東區光復路二段101號"

KNOWN_LANDMARKS: dict[str, str] = {
    "孟竹國宅": "新竹市東區建功一路49巷",
    "忠貞新村": "新竹市東區建功一路忠貞新村",
    "建功國小": "新竹市東區建功一路61號",
    "清大夜市": "新竹市東區建功路清大夜市",
    "科管院": "新竹市東區光復路二段101號清華大學台積館",
    "台積館": "新竹市東區光復路二段101號清華大學台積館",
    "台達館": "新竹市東區光復路二段101號清華大學台達館",
    "小吃部": "新竹市東區光復路二段101號清華大學小吃部",
    "水木餐廳": "新竹市東區光復路二段101號清華大學水木餐廳",
    "風雲樓": "新竹市東區光復路二段101號清華大學風雲樓",
    "南大校區": "新竹市東區南大路521號",
}


@dataclass
class DistanceInfo:
    origin: str
    walk_duration: str
    walk_meters: int
    bike_duration: str
    bike_meters: int

    def walk_minutes(self) -> int:
        return self.walk_meters // 80 if self.walk_meters else 0  # ~80m/min walking

    def bike_minutes(self) -> int:
        return self.bike_meters // 250 if self.bike_meters else 0  # ~250m/min biking


def extract_address(text: str) -> Optional[str]:
    """Try to pull a usable address from post text."""
    # First, check address/location lines
    for line in text.split("\n"):
        stripped = line.strip()
        if any(k in stripped for k in ["地點", "地址", "位置", "【地"]):
            addr = re.sub(r"^[【\[]*[^】\]：:]*[】\]：:]\s*", "", stripped).strip()
            if addr:
                # Check landmarks in the address line first
                for landmark, real_addr in KNOWN_LANDMARKS.items():
                    if landmark in addr:
                        return real_addr
                if len(addr) > 4:
                    cleaned = _clean_address(addr)
                    if len(cleaned.replace("新竹市", "").strip()) >= 3:
                        return cleaned

    # Resolve known landmarks mentioned anywhere in the text (before regex)
    for landmark, real_addr in KNOWN_LANDMARKS.items():
        if landmark in text:
            return real_addr

    addr_re = re.compile(r"新竹[市縣]?\S{0,3}[區鎮鄉]?\S{2,20}(?:路|街|巷|弄|號|段)\S{0,15}")
    m = addr_re.search(text)
    if m:
        return _clean_address(m.group(0))

    street_re = re.compile(r"(光復路|建功路|建功一路|金山街|寶山路|食品路|關新路|東進路|高翠路|南大路|民享街|忠孝路)\S{0,20}")
    m = street_re.search(text)
    if m:
        return "新竹市" + _clean_address(m.group(0))

    return None


def _clean_address(addr: str) -> str:
    addr = re.sub(r"[Xx×]\s*號", "號", addr)

    stripped = re.sub(r"[（(].*?[）)]", "", addr).strip("，。,. 、")

    if len(stripped) >= 4:
        addr = stripped
    else:
        # The meaningful content is inside parentheses; check landmarks first
        for landmark, real_addr in KNOWN_LANDMARKS.items():
            if landmark in addr:
                return real_addr
        # Otherwise use the content inside the first set of parens
        m = re.search(r"[（(](.+?)[）)]", addr)
        if m:
            addr = m.group(1)

    # Truncate at noise delimiters that follow the real address
    for delim in [" * ", "＊", "，走路", "，騎車", " 走路", " 騎車", "（距"]:
        idx = addr.find(delim)
        if idx > 3:
            addr = addr[:idx]

    addr = addr.strip("，。,. 、* ")
    if "新竹" not in addr:
        addr = "新竹市" + addr
    return addr


def calculate_distances(
    posts: list[dict],
    api_key: str,
    destination: str = DESTINATION_DEFAULT,
) -> list[dict]:
    """Add walk/bike distance info to each post. Returns updated posts list."""
    gmaps = googlemaps.Client(key=api_key)

    # Collect unique addresses
    addr_map: dict[int, str] = {}
    for i, p in enumerate(posts):
        addr = extract_address(p.get("text", ""))
        if addr:
            addr_map[i] = addr

    console.print(f"[cyan]Found addresses in {len(addr_map)}/{len(posts)} posts[/]")

    if not addr_map:
        console.print("[yellow]No addresses found to calculate distances.[/]")
        return posts

    # Batch in groups of 25 (API limit per request)
    indices = list(addr_map.keys())
    addresses = list(addr_map.values())

    walk_results: dict[int, DistanceInfo] = {}

    with Progress(console=console) as progress:
        task = progress.add_task("Calculating distances...", total=len(addresses))

        batch_size = 20
        for batch_start in range(0, len(addresses), batch_size):
            batch_addrs = addresses[batch_start:batch_start + batch_size]
            batch_indices = indices[batch_start:batch_start + batch_size]

            try:
                walk_resp = gmaps.distance_matrix(
                    origins=batch_addrs,
                    destinations=[destination],
                    mode="walking",
                    language="zh-TW",
                )
            except Exception as e:
                console.print(f"[red]Walking API error: {e}[/]")
                walk_resp = None

            try:
                bike_resp = gmaps.distance_matrix(
                    origins=batch_addrs,
                    destinations=[destination],
                    mode="bicycling",
                    language="zh-TW",
                )
            except Exception as e:
                console.print(f"[red]Bicycling API error: {e}[/]")
                bike_resp = None

            for j, idx in enumerate(batch_indices):
                walk_dur = ""
                walk_m = 0
                bike_dur = ""
                bike_m = 0

                if walk_resp and walk_resp["rows"][j]["elements"][0]["status"] == "OK":
                    el = walk_resp["rows"][j]["elements"][0]
                    walk_dur = el["duration"]["text"]
                    walk_m = el["distance"]["value"]

                if bike_resp and bike_resp["rows"][j]["elements"][0]["status"] == "OK":
                    el = bike_resp["rows"][j]["elements"][0]
                    bike_dur = el["duration"]["text"]
                    bike_m = el["distance"]["value"]

                walk_results[idx] = DistanceInfo(
                    origin=batch_addrs[j - batch_start] if j >= batch_start else addr_map[idx],
                    walk_duration=walk_dur,
                    walk_meters=walk_m,
                    bike_duration=bike_dur,
                    bike_meters=bike_m,
                )

                progress.advance(task)

            time.sleep(0.2)

    # Merge distance info into posts
    success = 0
    for idx, info in walk_results.items():
        if info.walk_meters > 0 or info.bike_meters > 0:
            success += 1
        posts[idx]["distance"] = {
            "origin_address": info.origin,
            "walk_duration": info.walk_duration,
            "walk_meters": info.walk_meters,
            "bike_duration": info.bike_duration,
            "bike_meters": info.bike_meters,
        }

    console.print(f"[green]Distance calculated for {success} listings[/]")
    return posts


def enrich_results(results_path: str, api_key: str, destination: str = DESTINATION_DEFAULT) -> None:
    """Load results.json, add distances, and save back."""
    path = Path(results_path)
    with open(path, encoding="utf-8") as f:
        posts = json.load(f)

    posts = calculate_distances(posts, api_key, destination)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)

    console.print(f"[green]Updated {path} with distance data[/]")
