#!/usr/bin/env python3
"""
Optimized scraper:
1. Open Chrome ONCE to get cookies
2. Use requests for everything else (no browser tabs)
"""

import asyncio
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from playwright.async_api import async_playwright

# Your Chrome profile path
CHROME_PROFILE = Path("C:/Users/Propietario/Desktop/pang/1_poit/chrome_profile")
CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"

OUTPUT_DIR = Path(__file__).parent / "output"
BASE_URL = "https://poit.bolagsverket.se"


def start_chrome(minimized: bool = True):
    """Start Chrome with your profile, optionally minimized."""
    cmd = [
        CHROME_PATH,
        f"--user-data-dir={CHROME_PROFILE}",
        "--remote-debugging-port=9222",
    ]

    if minimized:
        # Start minimized and positioned off-screen so you can't accidentally click
        cmd.extend(
            [
                "--window-position=2000,2000",  # Off-screen
                "--window-size=800,600",
            ]
        )

    cmd.append(f"{BASE_URL}/poit-app/")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    return proc


async def get_cookies_from_chrome() -> dict:
    """Connect to Chrome and extract cookies."""
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Make sure we're on the right site
        if "poit.bolagsverket.se" not in page.url:
            await page.goto(f"{BASE_URL}/poit-app/", wait_until="domcontentloaded")
            await asyncio.sleep(2)

        # Check for CAPTCHA
        text = await page.inner_text("body")
        if "human visitor" in text or "CAPTCHA" in text.upper():
            print("\n    ⚠ CAPTCHA detected! Solve it in Chrome and press Enter...")
            input()
            await asyncio.sleep(2)

        # Get all cookies
        cookies = await context.cookies()

        # Convert to dict for requests
        cookie_dict = {}
        for c in cookies:
            if "bolagsverket" in c.get("domain", ""):
                cookie_dict[c["name"]] = c["value"]

        return cookie_dict


def create_session(cookies: dict) -> requests.Session:
    """Create requests session with cookies."""
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"{BASE_URL}/poit-app/",
            "Origin": BASE_URL,
        }
    )
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".bolagsverket.se")
    return session


def fetch_kungorelser_list(session: requests.Session, api_date: str) -> list:
    """Fetch kungörelser list via API."""
    params = {
        "sokord": "",
        "kungorelseid": "",
        "kungorelseObjektPersonOrgnummer": "",
        "kungorelseObjektNamn": "",
        "tidsperiod": "ANNAN_PERIOD",
        "tidsperiodFrom": api_date,
        "tidsperiodTom": api_date,
        "amnesomradeId": "2",
        "kungorelsetypId": "4",
        "underRubrikId": "6",
    }

    url = f"{BASE_URL}/poit/rest/SokKungorelse"
    r = session.get(url, params=params, timeout=30)

    if r.status_code == 200:
        try:
            return r.json()
        except:
            pass
    return []


def scrape_kungorelse(
    session: requests.Session, kung_id: str, output_folder: Path
) -> dict:
    """
    Scrape a single kungörelse using the browser page (need JS).
    We'll use Playwright for this part.
    """
    normalized_id = kung_id.replace("/", "-")
    result = {"id": kung_id, "success": False, "error": None}

    # The page requires JS, so we need to actually visit it
    # This is handled in the async part
    return result


async def scrape_single_page(context, kung_id: str, output_folder: Path) -> dict:
    """Scrape a single kungörelse page."""
    normalized_id = kung_id.replace("/", "-")
    url = f"{BASE_URL}/poit-app/kungorelse/{normalized_id}"
    result = {"id": kung_id, "success": False}
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for JS to render (configurable)
        wait_time = random.uniform(
            CONFIG.get("wait_min", 8), CONFIG.get("wait_max", 12)
        )
        await asyncio.sleep(wait_time)

        # Check if we're on enskild page (intermediate redirect page)
        if "/enskild/" in page.url:
            # Wait for auto-redirect
            await asyncio.sleep(
                random.uniform(CONFIG.get("wait_min", 8), CONFIG.get("wait_max", 12))
            )

            # If STILL on enskild, try clicking the link manually
            if "/enskild/" in page.url:
                link = await page.query_selector(
                    f'a[href*="/kungorelse/{normalized_id}"]'
                )
                if link:
                    await link.click()
                    await asyncio.sleep(
                        random.uniform(
                            CONFIG.get("wait_min", 8), CONFIG.get("wait_max", 12)
                        )
                    )

        # ONLY scrape if we're on the actual /kungorelse/ page
        if "/kungorelse/" in page.url and "/enskild/" not in page.url:
            text_content = await page.inner_text("body")
            html_content = await page.content()
            has_content = "Kungörelsetext" in text_content or "Org nr:" in text_content

            if has_content:
                kung_folder = output_folder / normalized_id
                kung_folder.mkdir(parents=True, exist_ok=True)
                with open(kung_folder / "content.txt", "w", encoding="utf-8") as f:
                    f.write(
                        f"URL: {page.url}\nTimestamp: {datetime.now().isoformat()}\n"
                    )
                    f.write("=" * 60 + "\n\n" + text_content)
                with open(kung_folder / "page.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
                result["success"] = True
                result["chars"] = len(text_content)
            else:
                result["error"] = "No kungörelse content"
        else:
            result["error"] = f"Stuck on {page.url.split('/')[-2]}"

    except Exception as e:
        result["error"] = str(e)[:50]
    finally:
        await page.close()
    return result


async def scrape_pages_with_browser(
    context, kung_ids: list, output_folder: Path, parallel: int = 3
) -> list:
    """Scrape pages using parallel tabs with staggered starts."""
    results = []
    total = len(kung_ids)

    for i in range(0, total, parallel):
        batch = kung_ids[i : i + parallel]
        batch_num = i // parallel + 1
        print(f"\n    Batch {batch_num}: {len(batch)} pages...")

        # Staggered start tasks
        async def scrape_delayed(kid, delay):
            await asyncio.sleep(delay)
            return await scrape_single_page(context, kid, output_folder)

        tasks = [scrape_delayed(kid, j * 1.0) for j, kid in enumerate(batch)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for kid, r in zip(batch, batch_results):
            if isinstance(r, Exception):
                print(f"      ✗ {kid}: Error")
                results.append({"id": kid, "success": False, "error": str(r)})
            else:
                status = "✓" if r["success"] else "✗"
                info = (
                    f"{r.get('chars', 0)} chars"
                    if r["success"]
                    else r.get("error", "?")
                )
                print(f"      {status} {kid}: {info}")
                results.append(r)

        if i + parallel < total:
            wait = random.uniform(
                CONFIG.get("between_min", 3), CONFIG.get("between_max", 6)
            )
            print(f"    Waiting {wait:.1f}s...")
            await asyncio.sleep(wait)

    return results


def load_config() -> dict:
    """Load config from config.txt in same folder."""
    config_file = Path(__file__).parent / "config.txt"
    config = {
        "count": 20,
        "date": "",
        "parallel": 1,
        "visible": False,
        "wait_min": 8,
        "wait_max": 12,
        "between_min": 3,
        "between_max": 6,
    }

    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key in config:
                        if key == "visible":
                            config[key] = value.lower() == "true"
                        elif key == "date":
                            config[key] = value
                        else:
                            try:
                                config[key] = int(value) if value else config[key]
                            except ValueError:
                                pass
    return config


# Global config (loaded once)
CONFIG = {}


async def main():
    global CONFIG
    CONFIG = load_config()

    # Date handling
    if CONFIG["date"]:
        date_str = CONFIG["date"].replace("-", "")
        api_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        api_date = datetime.now().strftime("%Y-%m-%d")

    output_folder = OUTPUT_DIR / date_str
    output_folder.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("BOLAGSVERKET SCRAPER")
    print("=" * 60)
    print(f"Date: {api_date}")
    print(f"Count: {CONFIG['count']}")
    print(f"Parallel: {CONFIG['parallel']}")
    print(f"Wait: {CONFIG['wait_min']}-{CONFIG['wait_max']}s")
    print(f"Mode: {'visible' if CONFIG['visible'] else 'minimized (sandboxed)'}")
    print("=" * 60)

    # Step 1: Start Chrome (minimized by default so you can work)
    mode = "visible" if CONFIG["visible"] else "minimized (off-screen)"
    print(f"\n[1] Starting Chrome ({mode})...")
    chrome_proc = start_chrome(minimized=not CONFIG["visible"])

    try:
        # Step 2: Get cookies
        print("\n[2] Getting cookies from Chrome...")
        cookies = await get_cookies_from_chrome()
        print(f"    ✓ Got {len(cookies)} cookies")

        # Step 3: Create session and fetch list
        print("\n[3] Fetching kungörelser via API (using requests)...")
        session = create_session(cookies)
        kungorelser = fetch_kungorelser_list(session, api_date)

        if not kungorelser:
            print("    ✗ No kungörelser found (API may need browser session)")
            print("    Trying via browser...")

            # Fallback: use browser for API too
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                context = browser.contexts[0]
                page = context.pages[0]

                api_result = await page.evaluate(
                    """
                    async (dateStr) => {
                        const params = new URLSearchParams({
                            sokord: '', kungorelseid: '',
                            kungorelseObjektPersonOrgnummer: '',
                            kungorelseObjektNamn: '',
                            tidsperiod: 'ANNAN_PERIOD',
                            tidsperiodFrom: dateStr, tidsperiodTom: dateStr,
                            amnesomradeId: '2', kungorelsetypId: '4', underRubrikId: '6'
                        });
                        const r = await fetch('https://poit.bolagsverket.se/poit/rest/SokKungorelse?' + params);
                        return await r.json();
                    }
                """,
                    api_date,
                )
                kungorelser = api_result if isinstance(api_result, list) else []

        print(f"    ✓ Got {len(kungorelser)} kungörelser")

        if not kungorelser:
            return 1

        # Save list
        list_file = output_folder / f"kungorelser_{date_str}.json"
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(kungorelser, f, ensure_ascii=False, indent=2)

        # Step 4: Scrape individual pages (need browser for JS)
        print(f"\n[4] Scraping {CONFIG['count']} pages...")
        start_time = time.time()

        to_scrape = [
            k.get("kungorelseid")
            for k in kungorelser[: CONFIG["count"]]
            if k.get("kungorelseid")
        ]

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]

            results = await scrape_pages_with_browser(
                context, to_scrape, output_folder, CONFIG["parallel"]
            )

        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r.get("success"))

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total kungörelser: {len(kungorelser)}")
        print(f"Scraped: {len(to_scrape)}")
        print(f"Success: {success_count}")
        print(f"Failed: {len(to_scrape) - success_count}")
        print(
            f"Time: {elapsed:.1f}s ({elapsed / max(1, len(to_scrape)):.1f}s per page)"
        )
        print(f"Output: {output_folder}")
        print("=" * 60)
        print("\nChrome is still open. Close manually when done.")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
