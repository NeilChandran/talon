"""Shared Playwright helpers for explore scrapers."""
import asyncio
import random
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, TypeVar

from services.linkedin_service import load_session

T = TypeVar("T")

_pw_pool = ThreadPoolExecutor(max_workers=1)

USER_AGENTS = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ),
]


def pick_user_agent() -> str:
    return random.choice(USER_AGENTS)


def linkedin_cookies_for_playwright() -> Optional[List[Dict[str, Any]]]:
    sess = load_session()
    if not sess or not sess.get("li_at"):
        return None
    js = (sess.get("jsessionid") or "ajax:0").strip().strip('"')
    cookies = [
        {"name": "li_at", "value": sess["li_at"], "domain": ".linkedin.com", "path": "/"},
        {"name": "JSESSIONID", "value": js, "domain": ".linkedin.com", "path": "/"},
    ]
    for key in ("bcookie", "bscookie", "lang", "liap"):
        if sess.get(key):
            cookies.append(
                {
                    "name": key,
                    "value": str(sess[key]).strip().strip('"'),
                    "domain": ".linkedin.com",
                    "path": "/",
                }
            )
    return cookies


def new_stealth_context(playwright, *, use_linkedin_cookies: bool = False):
    """Launch headless Chromium with rotated UA and optional LinkedIn cookies."""
    browser = playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=pick_user_agent(),
        locale="en-US",
        viewport={"width": 1400, "height": 900},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    if use_linkedin_cookies:
        cookies = linkedin_cookies_for_playwright()
        if cookies:
            context.add_cookies(cookies)
    return browser, context


async def run_playwright(fn: Callable[[], T]) -> T:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_pw_pool, fn)
