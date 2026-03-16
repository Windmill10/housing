"""Generate an HTML report from crawled housing results."""
from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from html import escape
from pathlib import Path


def extract_location(text: str) -> str:
    for line in text.split("\n"):
        line = line.strip()
        if any(k in line for k in ["地點", "地址", "地區", "位置", "【地"]):
            loc = re.sub(r"^[【\[]*[^】\]：:]*[】\]：:]\s*", "", line).strip()
            if loc:
                return loc
    addr_re = re.compile(r"新竹[市縣]?\S{0,3}[區鎮鄉]?\S{2,20}(?:路|街|巷|弄|號|段)\S{0,15}")
    m = addr_re.search(text)
    if m:
        return m.group(0)
    for line in text.split("\n"):
        stripped = line.strip()
        kw = re.compile(r"(光復|建功|金山|寶山|食品|關新|東區|北區|清大|交大|高鐵|公道五|竹北)")
        if kw.search(stripped) and 5 < len(stripped) < 60:
            cleaned = re.sub(r"^[【\[]*[^】\]：:]*[】\]：:]\s*", "", stripped).strip()
            if cleaned:
                return cleaned
    return ""


def extract_layout(text: str) -> str:
    for line in text.split("\n"):
        line = line.strip()
        if any(k in line for k in ["格局", "房型"]):
            lay = re.sub(r"^[【\[]*[^】\]：:]*[】\]：:]\s*", "", line).strip()
            if lay:
                return lay
    for pattern in [r"(\d房\d?廳?\d?衛?)", r"(獨立套房)", r"(雅房)", r"(整層住家)", r"(大套房)"]:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""


def extract_type_tag(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ["求租", "#求租", "找房", "徵房"]):
        return "求租"
    if any(k in lower for k in ["出租", "自租", "房東", "屋主"]):
        return "出租"
    return ""


def extract_details(text: str) -> list[str]:
    """Pull key info lines from the post."""
    keywords = ["坪數", "樓層", "押金", "水電", "設備", "入住", "租期",
                 "台水", "台電", "可租補", "可報稅", "電梯", "車位",
                 "寵物", "禁菸", "冷氣", "洗衣", "網路", "天然氣",
                 "備註", "聯絡", "電話", "LINE", "限女", "限男",
                 "謝絕", "地下室", "頂樓加蓋"]
    details = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        if any(k in stripped for k in keywords):
            details.append(stripped)
    return details[:6]


def price_color(price: int | None) -> str:
    if price is None:
        return "#888"
    if price <= 6000:
        return "#4caf50"
    if price <= 10000:
        return "#ff9800"
    return "#f44336"


def _dedup_posts(posts: list[dict]) -> list[dict]:
    """Remove duplicate posts based on normalised text content."""
    import hashlib, re
    seen: set[str] = set()
    unique: list[dict] = []
    for p in posts:
        lines = [l.strip() for l in p["text"].strip().split("\n") if l.strip()]
        if len(lines) > 1:
            lines = lines[1:]
        body = re.sub(r"\s+", "", "".join(lines))
        body = re.sub(r"(…\s*)?See\s*more$", "", body)
        # Use shorter prefix so truncated and full versions match
        fp = hashlib.md5(body[:200].encode()).hexdigest()[:20]
        if fp not in seen:
            seen.add(fp)
            unique.append(p)
    return unique


def generate_html(posts: list[dict], filters: dict) -> str:
    posts = _dedup_posts(posts)

    only_rental = filters.get("only_rental", False)
    max_walk = filters.get("max_walk_minutes", 0)
    people_filter = filters.get("people", [])

    # Pre-filter posts
    filtered = []
    for p in posts:
        tag = extract_type_tag(p["text"])
        if only_rental and tag == "求租":
            continue
        if max_walk > 0:
            dist = p.get("distance", {})
            walk_m = dist.get("walk_meters", 0)
            if walk_m > 0 and walk_m / 80 > max_walk:
                continue
        if people_filter:
            pc = p.get("people_count")
            if pc is not None and pc not in people_filter:
                continue
        filtered.append(p)
    posts = filtered

    people_str = ", ".join(str(n) for n in people_filter) or "any"
    filter_desc_parts = []
    if only_rental:
        filter_desc_parts.append("出租 only")
    if max_walk:
        filter_desc_parts.append(f"walk ≤ {max_walk} min")
    if people_filter:
        filter_desc_parts.append(f"people: {people_str}")
    filter_desc = " | ".join(filter_desc_parts) if filter_desc_parts else "none"

    cards_html = []
    for i, p in enumerate(posts, 1):
        tag = extract_type_tag(p["text"])
        location = escape(extract_location(p["text"]))
        layout = escape(extract_layout(p["text"]))
        details = extract_details(p["text"])
        author = escape(p.get("author", "?"))
        url = p.get("url", "")
        price = p.get("best_price")
        people = p.get("people_count")
        color = price_color(price)

        price_str = f"${price:,}/月" if price else "價格未標"
        people_str_card = f"{people}人" if people else "—"
        tag_class = "tag-rent" if tag == "出租" else "tag-seek" if tag == "求租" else "tag-none"
        tag_label = tag or "其他"

        details_html = ""
        if details:
            items = "".join(f"<li>{escape(d)}</li>" for d in details)
            details_html = f'<ul class="details">{items}</ul>'

        # Distance info
        dist = p.get("distance", {})
        walk_dur = dist.get("walk_duration", "")
        bike_dur = dist.get("bike_duration", "")
        walk_m = dist.get("walk_meters", 0)
        bike_m = dist.get("bike_meters", 0)
        distance_html = ""
        if walk_dur or bike_dur:
            parts = []
            if walk_dur:
                parts.append(f'<span class="dist-walk">🚶 {walk_dur}</span>')
            if bike_dur:
                parts.append(f'<span class="dist-bike">🚲 {bike_dur}</span>')
            distance_html = f'<div class="distance">{"  ".join(parts)}</div>'

        card = f"""
        <div class="card" data-price="{price or 0}" data-people="{people or 0}" data-type="{tag}"
             data-walk="{walk_m}" data-bike="{bike_m}">
            <div class="card-header">
                <span class="idx">#{i}</span>
                <span class="{tag_class}">{tag_label}</span>
                <span class="price" style="color:{color}">{price_str}</span>
                <span class="people">👤 {people_str_card}</span>
                {distance_html}
            </div>
            <div class="card-body">
                <div class="meta">
                    <span class="author">✎ {author}</span>
                    {f'<span class="layout">🏠 {layout}</span>' if layout else ''}
                </div>
                {f'<div class="location">📍 {location}</div>' if location else ''}
                {details_html}
            </div>
            {f'<a class="card-link" href="{url}" target="_blank">View on Facebook →</a>' if url else ''}
        </div>"""
        cards_html.append(card)

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NTHU Housing Results</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, "Noto Sans TC", "Helvetica Neue", sans-serif;
        background: #0f1117;
        color: #e0e0e0;
        padding: 24px;
        max-width: 900px;
        margin: 0 auto;
    }}
    h1 {{
        font-size: 1.6rem;
        font-weight: 700;
        margin-bottom: 6px;
        color: #fff;
    }}
    .subtitle {{
        color: #888;
        font-size: 0.85rem;
        margin-bottom: 20px;
    }}
    .filters {{
        display: flex;
        gap: 10px;
        margin-bottom: 20px;
        flex-wrap: wrap;
    }}
    .filter-btn {{
        padding: 6px 14px;
        border-radius: 20px;
        border: 1px solid #333;
        background: #1a1d27;
        color: #ccc;
        cursor: pointer;
        font-size: 0.8rem;
        transition: all 0.15s;
    }}
    .filter-btn:hover, .filter-btn.active {{
        background: #2563eb;
        border-color: #2563eb;
        color: #fff;
    }}
    .search {{
        width: 100%;
        padding: 10px 16px;
        border-radius: 10px;
        border: 1px solid #333;
        background: #1a1d27;
        color: #e0e0e0;
        font-size: 0.9rem;
        margin-bottom: 16px;
        outline: none;
    }}
    .search:focus {{ border-color: #2563eb; }}
    .search::placeholder {{ color: #555; }}
    .count {{ color: #888; font-size: 0.8rem; margin-bottom: 12px; }}
    .card {{
        background: #1a1d27;
        border: 1px solid #262a36;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
        transition: border-color 0.15s;
    }}
    .card:hover {{ border-color: #2563eb; }}
    .card-header {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
        flex-wrap: wrap;
    }}
    .idx {{ color: #555; font-size: 0.75rem; font-weight: 600; }}
    .tag-rent {{
        background: #166534;
        color: #4ade80;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.7rem;
        font-weight: 600;
    }}
    .tag-seek {{
        background: #1e3a5f;
        color: #60a5fa;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.7rem;
        font-weight: 600;
    }}
    .tag-none {{
        background: #333;
        color: #888;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.7rem;
    }}
    .price {{
        font-size: 1.15rem;
        font-weight: 700;
    }}
    .people {{
        color: #aaa;
        font-size: 0.85rem;
    }}
    .card-body {{ padding-left: 2px; }}
    .meta {{
        display: flex;
        gap: 16px;
        color: #aaa;
        font-size: 0.8rem;
        margin-bottom: 6px;
        flex-wrap: wrap;
    }}
    .location {{
        color: #93c5fd;
        font-size: 0.85rem;
        margin-bottom: 6px;
    }}
    .details {{
        list-style: none;
        padding: 0;
        margin-top: 8px;
    }}
    .details li {{
        color: #888;
        font-size: 0.78rem;
        padding: 1px 0;
        border-left: 2px solid #333;
        padding-left: 10px;
        margin-bottom: 2px;
    }}
    .card-link {{
        display: inline-block;
        margin-top: 10px;
        color: #60a5fa;
        text-decoration: none;
        font-size: 0.8rem;
    }}
    .card-link:hover {{ text-decoration: underline; }}
    .distance {{
        display: flex;
        gap: 12px;
        font-size: 0.8rem;
        margin-left: auto;
    }}
    .dist-walk {{ color: #a5d6a7; }}
    .dist-bike {{ color: #90caf9; }}
    .hidden {{ display: none; }}
    .sort-bar {{
        display: flex;
        gap: 8px;
        align-items: center;
        margin-bottom: 16px;
        font-size: 0.8rem;
        color: #888;
    }}
</style>
</head>
<body>
    <h1>🏠 NTHU Housing — 清大租屋版</h1>
    <p class="subtitle">{len(posts)} listings | Filters: {filter_desc}</p>

    <input class="search" type="text" placeholder="Search by keyword... (e.g. 套房, 金山, 清大, 可租補)" id="search">

    <div class="filters">
        <button class="filter-btn active" onclick="filterType('all')">All</button>
        <button class="filter-btn" onclick="filterType('出租')">出租 For Rent</button>
        <button class="filter-btn" onclick="filterType('求租')">求租 Looking</button>
    </div>
    <div class="sort-bar">
        Sort:
        <button class="filter-btn active" onclick="sortCards('default')">Default</button>
        <button class="filter-btn" onclick="sortCards('price-asc')">Price ↑</button>
        <button class="filter-btn" onclick="sortCards('price-desc')">Price ↓</button>
        <button class="filter-btn" onclick="sortCards('walk')">🚶 Walk</button>
        <button class="filter-btn" onclick="sortCards('bike')">🚲 Bike</button>
    </div>
    <div class="count" id="count"></div>

    <div id="cards">
        {"".join(cards_html)}
    </div>

<script>
const cards = document.querySelectorAll('.card');
const searchInput = document.getElementById('search');
const countEl = document.getElementById('count');
let activeType = 'all';

function updateCount() {{
    const visible = document.querySelectorAll('.card:not(.hidden)').length;
    countEl.textContent = visible + ' / ' + cards.length + ' shown';
}}

function applyFilters() {{
    const q = searchInput.value.toLowerCase();
    cards.forEach(card => {{
        const text = card.textContent.toLowerCase();
        const type = card.dataset.type;
        const matchType = activeType === 'all' || type === activeType;
        const matchSearch = !q || text.includes(q);
        card.classList.toggle('hidden', !(matchType && matchSearch));
    }});
    updateCount();
}}

function filterType(type) {{
    activeType = type;
    document.querySelectorAll('.filters .filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    applyFilters();
}}

function sortCards(mode) {{
    const container = document.getElementById('cards');
    const arr = Array.from(cards);
    document.querySelectorAll('.sort-bar .filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    arr.sort((a, b) => {{
        if (mode === 'price-asc') return (parseInt(a.dataset.price)||999999) - (parseInt(b.dataset.price)||999999);
        if (mode === 'price-desc') return (parseInt(b.dataset.price)||0) - (parseInt(a.dataset.price)||0);
        if (mode === 'walk') return (parseInt(a.dataset.walk)||999999) - (parseInt(b.dataset.walk)||999999);
        if (mode === 'bike') return (parseInt(a.dataset.bike)||999999) - (parseInt(b.dataset.bike)||999999);
        return 0;
    }});
    arr.forEach(c => container.appendChild(c));
}}

searchInput.addEventListener('input', applyFilters);
updateCount();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from crawled results")
    parser.add_argument("-f", "--file", default="results.json", help="Results JSON file")
    parser.add_argument("-o", "--output", default="report.html", help="Output HTML file")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open in browser")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        posts = json.load(f)

    html = generate_html(posts, {})
    out = Path(args.output)
    out.write_text(html, encoding="utf-8")
    print(f"Report generated: {out.resolve()} ({len(posts)} listings)")

    if not args.no_open:
        webbrowser.open(f"file://{out.resolve()}")


if __name__ == "__main__":
    main()
