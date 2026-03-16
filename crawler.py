from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from rich.console import Console

from config import AppConfig
from parser import RentalPost, parse_post

console = Console()


class FacebookGroupCrawler:
    def __init__(self, config: AppConfig):
        self.config = config
        self.posts: list[RentalPost] = []
        self._seen_ids: set[str] = set()

    def run(self) -> list[RentalPost]:
        session_dir = Path(self.config.crawler.session_dir)
        session_dir.mkdir(exist_ok=True)

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(session_dir),
                headless=self.config.crawler.headless,
                viewport={"width": 1280, "height": 900},
                locale="zh-TW",
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()

            if not self._check_fb_logged_in(page):
                self._login(page)

            for i, url in enumerate(self.config.crawler.group_urls):
                if len(self.config.crawler.group_urls) > 1:
                    console.print(f"\n[bold cyan]━━━ Group {i+1}/{len(self.config.crawler.group_urls)} ━━━[/]")
                self._crawl_group(page, url)

            context.close()

        return self.posts

    def _check_fb_logged_in(self, page: Page) -> bool:
        """Navigate to FB and check if we have an active session."""
        console.print("[cyan]Checking login status...[/]")
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        return self._is_on_fb_feed(page)

    def _is_on_fb_feed(self, page: Page) -> bool:
        """Navigate to FB home and check if we're logged in by looking for feed elements."""
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        try:
            for sel in ['[role="feed"]', '[aria-label="Facebook"]',
                        '[aria-label="帳號"]', '[aria-label="Account"]',
                        '[aria-label="首頁"]', '[aria-label="Home"]',
                        'input[aria-label="Search Facebook"]',
                        'input[aria-label="搜尋 Facebook"]',
                        '[data-pagelet="Stories"]']:
                if page.locator(sel).count() > 0:
                    return True
        except Exception:
            pass
        return False

    def _login(self, page: Page) -> None:
        creds = self.config.credentials
        console.print(f"[yellow]Logging in as {creds.email}...[/]")

        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        page.fill('input[name="email"]', creds.email)
        page.fill('input[name="pass"]', creds.password)

        page.press('input[name="pass"]', "Enter")
        time.sleep(8)

        console.print("[bold yellow]>>> Please complete any prompts (2FA, etc.) in the browser window <<<[/]")
        console.print("[yellow]Waiting up to 180 seconds...[/]")
        for i in range(90):
            time.sleep(2)
            if self._is_on_fb_feed(page):
                break
            if i % 5 == 0:
                console.print(f"[dim]  Still waiting... ({i*2}s)[/]")
        else:
            page.screenshot(path="login_timeout.png")
            raise RuntimeError("Timed out waiting for login. Screenshot saved to login_timeout.png")

        console.print("[green]Login successful! Session saved for future runs.[/]")

    def _crawl_group(self, page: Page, url: str = "") -> None:
        url = url or self.config.crawler.group_urls[0]
        console.print(f"[cyan]Navigating to group: {url}[/]")

        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)

        console.print(f"[dim]Current URL: {page.url}[/]")

        # Dismiss popups
        for selector in ['[aria-label="關閉"]', '[aria-label="Close"]',
                         '[aria-label="Not Now"]', '[aria-label="稍後再說"]']:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    time.sleep(1)
            except Exception:
                pass

        # Wait for feed content
        try:
            page.locator('[role="feed"]').wait_for(timeout=10000)
            console.print("[green]Feed container found.[/]")
        except Exception:
            console.print("[yellow]Feed container not found, trying to scroll anyway...[/]")

        max_scrolls = self.config.crawler.max_scrolls
        pause = self.config.crawler.scroll_pause

        console.print(f"[cyan]Scrolling to load posts (max {max_scrolls} scrolls)...[/]")

        no_new_count = 0
        for i in range(max_scrolls):
            self._expand_posts(page)

            prev_count = len(self.posts)
            self._extract_posts(page)
            new_count = len(self.posts) - prev_count

            console.print(f"  Scroll {i+1}/{max_scrolls} — {new_count} new posts (total: {len(self.posts)})")

            if new_count == 0:
                no_new_count += 1
                if no_new_count >= 20:
                    console.print("[yellow]No new posts after 20 scrolls. Stopping.[/]")
                    break
            else:
                no_new_count = 0

            # Scroll aggressively to trigger lazy loading
            page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
            time.sleep(pause)
            # Extra nudge every few scrolls
            if i % 3 == 2:
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(1)

        console.print(f"[green]Crawling complete. Total posts: {len(self.posts)}[/]")

    def _expand_posts(self, page: Page) -> None:
        """Click all 'See more' links to reveal full post text."""
        for label in ["See more", "顯示更多", "查看更多"]:
            try:
                # FB uses both div[role="button"] and plain text links for "See more"
                buttons = page.get_by_text(label, exact=True).all()
                for btn in buttons:
                    try:
                        if btn.is_visible(timeout=300):
                            btn.scroll_into_view_if_needed(timeout=1000)
                            btn.click(timeout=2000, no_wait_after=True, force=True)
                            time.sleep(0.5)
                    except Exception:
                        continue
            except Exception:
                continue

    def _extract_posts(self, page: Page) -> None:
        # Get top-level post containers from the feed, not nested comment articles
        feed = page.locator('[role="feed"]')
        if feed.count() == 0:
            return

        # Each post in the feed is a direct child div of the feed
        post_wrappers = feed.locator("> div").all()

        for wrapper in post_wrappers:
            try:
                # A real post has enough content (comments are short)
                text = wrapper.inner_text(timeout=3000)
                if not text or len(text.strip()) < 50:
                    continue

                # Skip if this looks like a comment-only block (very short, ends with Like/Reply)
                lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                if len(lines) < 5:
                    continue

                content_key = self._content_fingerprint(text)
                if content_key in self._seen_ids:
                    continue
                self._seen_ids.add(content_key)

                post_id = hashlib.md5(text[:300].encode()).hexdigest()[:16]

                author = self._extract_author(wrapper)
                timestamp = self._extract_timestamp(wrapper)
                post_url = self._extract_post_url(wrapper)

                # Strip comment noise from the end — post text usually comes before
                # "Like", "Comment", "Share" action buttons
                clean_text = self._clean_post_text(text)

                post = parse_post(
                    post_id=post_id,
                    author=author,
                    text=clean_text,
                    timestamp=timestamp,
                    url=post_url,
                )
                self.posts.append(post)

            except Exception:
                continue

    @staticmethod
    def _content_fingerprint(raw: str) -> str:
        """Normalize text for cross-group deduplication.

        Strips the author line, collapses whitespace, removes "See more"
        truncation markers, and hashes the core body so the same post
        shared in multiple groups (or truncated variants) is detected.
        """
        import re
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        if len(lines) > 1:
            lines = lines[1:]
        body = re.sub(r"\s+", "", "".join(lines))
        body = re.sub(r"(…\s*)?See\s*more$", "", body)
        return hashlib.md5(body[:200].encode()).hexdigest()[:20]

    def _clean_post_text(self, raw: str) -> str:
        """Remove navigation/comment noise, keep only the post content."""
        lines = raw.strip().split("\n")
        clean_lines = []
        junk = {"Facebook", "Like", "Comment", "Share", "Reply",
                "讚", "留言", "分享", "回覆", "所有留言", "All comments",
                "Most relevant", "最相關", "All reactions:"}

        # Skip leading junk lines and single-character lines (scrambled nav text)
        content_started = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in junk:
                if content_started:
                    break
                continue
            # Skip single-character lines (scrambled FB metadata)
            if len(stripped) <= 2 and not any(c > '\u4e00' for c in stripped):
                continue
            # Skip "·" separator
            if stripped == "·":
                content_started = True
                continue
            # Skip reaction/comment counts at the end
            if stripped.endswith("comment") or stripped.endswith("comments"):
                continue
            content_started = True
            clean_lines.append(stripped)
        return "\n".join(clean_lines).strip()

    def _extract_author(self, article) -> str:
        try:
            for selector in ["h2 a strong span", "h3 a strong span",
                             "strong > span > a", "h2 span a"]:
                el = article.locator(selector).first
                if el.count() > 0:
                    return el.inner_text(timeout=1000)
        except Exception:
            pass
        return "Unknown"

    def _extract_timestamp(self, article) -> str:
        try:
            for selector in ['a[role="link"] span[id]', "abbr", '[data-utime]']:
                el = article.locator(selector).first
                if el.count() > 0:
                    return el.get_attribute("title") or el.inner_text(timeout=1000)
        except Exception:
            pass
        return ""

    def _extract_post_url(self, article) -> str:
        try:
            links = article.locator('a[href*="/groups/"]').all()
            for link in links:
                href = link.get_attribute("href") or ""
                if "/posts/" in href or "/permalink/" in href:
                    if href.startswith("/"):
                        return "https://www.facebook.com" + href.split("?")[0]
                    return href.split("?")[0]
        except Exception:
            pass
        return self.config.crawler.group_url


def save_results(posts: list[RentalPost], path: str = "results.json") -> None:
    data = []
    for p in posts:
        data.append({
            "post_id": p.post_id,
            "author": p.author,
            "text": p.text,
            "timestamp": p.timestamp,
            "url": p.url,
            "prices": p.prices,
            "best_price": p.best_price,
            "people_count": p.people_count,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    console.print(f"[green]Results saved to {path}[/]")
