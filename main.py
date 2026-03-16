from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from config import AppConfig, CrawlerConfig, Credentials, FilterConfig, MapsConfig
from crawler import FacebookGroupCrawler, save_results

console = Console()

DEFAULT_GROUPS = [
    "https://www.facebook.com/groups/NTHUallpass",
]


def main():
    parser = argparse.ArgumentParser(description="NTHU Housing Group Crawler")
    parser.add_argument("-c", "--config", help="Path to config.yaml file")
    parser.add_argument("--email", help="Facebook email")
    parser.add_argument("--password", help="Facebook password")
    parser.add_argument("--groups", nargs="+", default=None,
                        help="Facebook group URLs to crawl")
    parser.add_argument("--min-price", type=int, default=None)
    parser.add_argument("--max-price", type=int, default=None)
    parser.add_argument("--people", type=int, nargs="+", default=None,
                        help="Filter by people count (e.g. --people 2 4 5)")
    parser.add_argument("--only-rental", action="store_true",
                        help="Only show 出租 posts, exclude 求租")
    parser.add_argument("--max-walk", type=int, default=0,
                        help="Max walking minutes to destination (0=no limit)")
    parser.add_argument("--scrolls", type=int, default=200, help="Max scrolls per group")
    parser.add_argument("--window", action="store_true",
                        help="Show browser window (default: headless)")
    parser.add_argument("--output", default="results.json")
    parser.add_argument("--maps-key", default=None, help="Google Maps API key")
    parser.add_argument("--destination", default=None)
    parser.add_argument("--no-distance", action="store_true")
    args = parser.parse_args()

    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            console.print(f"[red]Config file not found: {config_path}[/]")
            sys.exit(1)
        config = AppConfig.from_yaml(config_path)
    elif args.email and args.password:
        config = AppConfig(
            credentials=Credentials(email=args.email, password=args.password),
            filters=FilterConfig(
                min_price=args.min_price or 0,
                max_price=args.max_price or 999999,
                num_people=args.people or [],
                only_rental=args.only_rental,
                max_walk_minutes=args.max_walk,
            ),
            crawler=CrawlerConfig(
                group_urls=args.groups or DEFAULT_GROUPS,
                max_scrolls=args.scrolls,
                headless=not args.window,
            ),
            maps=MapsConfig(
                api_key=args.maps_key or "",
                destination=args.destination or MapsConfig().destination,
            ),
        )
    else:
        console.print("[yellow]Usage:[/]")
        console.print('  uv run main.py --email EMAIL --password PASS [options]')
        console.print()
        console.print("[dim]  --groups URL1 URL2       Crawl multiple FB groups")
        console.print("  --people 2 4 5           Filter by people count")
        console.print("  --only-rental            Exclude 求租 posts")
        console.print("  --max-walk 60            Max walking minutes from destination")
        console.print("  --maps-key KEY           Google Maps API key")
        console.print("  --scrolls 80             More scrolls per group")
        console.print("  --window                 Show browser (default: headless)[/]")
        sys.exit(1)

    console.print(Panel("[bold]NTHU Housing Group Crawler[/]", style="cyan"))
    groups = config.crawler.group_urls
    console.print(f"[dim]Groups: {len(groups)} | Scrolls: {config.crawler.max_scrolls}/group[/]")
    for g in groups:
        console.print(f"[dim]  • {g}[/]")

    crawler = FacebookGroupCrawler(config)
    posts = crawler.run()

    save_results(posts, args.output)
    console.print(f"[green]Crawled {len(posts)} posts → {args.output}[/]")

    # Distance calculation
    api_key = config.maps.api_key
    if api_key and not args.no_distance:
        from distance import enrich_results
        console.print(f"\n[cyan]Calculating distances to: {config.maps.destination}[/]")
        enrich_results(args.output, api_key, config.maps.destination)

    # Generate HTML report with filters applied
    from view import generate_html
    with open(args.output, encoding="utf-8") as f:
        final_posts = json.load(f)

    view_filters = {
        "only_rental": config.filters.only_rental,
        "max_walk_minutes": config.filters.max_walk_minutes,
        "people": config.filters.num_people,
    }
    html = generate_html(final_posts, view_filters)
    report_path = Path("report.html")
    report_path.write_text(html, encoding="utf-8")
    console.print(f"[green]Report: {report_path.resolve()}[/]")


if __name__ == "__main__":
    main()
