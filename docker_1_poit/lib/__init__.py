"""
Docker-ready scraper library for Bolagsverket kungörelser.

Modules:
    - api: API calls to Bolagsverket
    - scraper: Playwright-based browser automation
"""

from .api import create_session, fetch_kungorelser_list
from .scraper import (
    IS_DOCKER,
    get_browser_and_context,
    get_cookies_from_browser,
    get_cookies_from_chrome,
    scrape_single_page,
    scrape_kungorelse_pages,
)

__all__ = [
    "IS_DOCKER",
    "create_session",
    "fetch_kungorelser_list",
    "get_browser_and_context",
    "get_cookies_from_browser",
    "get_cookies_from_chrome",
    "scrape_single_page",
    "scrape_kungorelse_pages",
]
