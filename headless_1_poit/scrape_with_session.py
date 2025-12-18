#!/usr/bin/env python3
"""
Scrape kungörelser using your Chrome session.

This script:
1. Connects to Chrome running with remote debugging
2. Uses YOUR session (cookies, etc.) to bypass CAPTCHA
3. Fetches kungörelse details via the API

Usage:
1. Close Chrome completely
2. Start Chrome with:
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
3. Navigate to https://poit.bolagsverket.se/poit-app/ and pass CAPTCHA if needed
4. Run this script: python scrape_with_session.py
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Paths
TESTNING_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = TESTNING_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# API
BASE_URL = "https://poit.bolagsverket.se"
API_BASE = f"{BASE_URL}/poit/rest"


def get_chrome_cookies() -> dict:
    """Get cookies from Chrome running with remote debugging."""
    try:
        # Get list of tabs
        r = requests.get("http://127.0.0.1:9222/json", timeout=5)
        tabs = r.json()

        if not tabs:
            return None

        # Find a PoIT tab or use first tab
        target_tab = None
        for tab in tabs:
            if "poit.bolagsverket.se" in tab.get("url", ""):
                target_tab = tab
                break

        if not target_tab:
            target_tab = tabs[0]

        # Connect via CDP to get cookies
        ws_url = target_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            print("[WARN] No WebSocket URL found")
            return None

        # Use CDP HTTP endpoint instead
        # Get all cookies for the domain
        import websocket

        ws = websocket.create_connection(ws_url)

        # Send CDP command to get cookies
        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))

        result = json.loads(ws.recv())
        ws.close()

        cookies = result.get("result", {}).get("cookies", [])

        # Filter for bolagsverket
        bv_cookies = {}
        for c in cookies:
            if "bolagsverket" in c.get("domain", ""):
                bv_cookies[c["name"]] = c["value"]

        return bv_cookies

    except requests.exceptions.ConnectionError:
        print(
            "[ERROR] Cannot connect to Chrome. Is it running with --remote-debugging-port=9222?"
        )
        return None
    except ImportError:
        print(
            "[ERROR] websocket-client not installed. Run: pip install websocket-client"
        )
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def fetch_kungorelser_list(session: requests.Session, date_str: str) -> list:
    """Fetch kungörelser list from API."""
    if len(date_str) == 8:
        api_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    else:
        api_date = date_str

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

    url = f"{API_BASE}/SokKungorelse"

    try:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        print(f"[ERROR] {e}")

    return []


def fetch_kungorelse_page(session: requests.Session, kung_id: str) -> dict:
    """Fetch individual kungörelse page content."""
    normalized_id = kung_id.replace("/", "-")
    url = f"{BASE_URL}/poit-app/kungorelse/{normalized_id}"

    try:
        r = session.get(url, timeout=30)

        if r.status_code == 200:
            text = r.text

            # Check if we got real content or CAPTCHA
            if "human visitor" in text or "CAPTCHA" in text:
                return {"success": False, "error": "CAPTCHA"}

            # Check for bot detection
            if "bobcmn" in text and len(text) < 50000:
                return {"success": False, "error": "Bot detection"}

            # Try to extract content
            # The page is rendered by Vue, so we need the full HTML
            return {"success": True, "url": url, "html": text, "size": len(text)}

    except Exception as e:
        return {"success": False, "error": str(e)}

    return {"success": False, "error": "Unknown"}


def main():
    parser = argparse.ArgumentParser(description="Scrape with Chrome session")
    parser.add_argument(
        "count", nargs="?", type=int, default=3, help="Count (default: 3)"
    )
    parser.add_argument("--date", "-d", type=str, default=None, help="Date (YYYYMMDD)")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y%m%d")

    print("=" * 60)
    print("KUNGÖRELSE SCRAPER (Chrome Session)")
    print("=" * 60)
    print(f"Date: {date_str}")
    print(f"Count: {args.count}")
    print("=" * 60)

    # Step 1: Get cookies from Chrome
    print("\n[1] Getting cookies from Chrome...")
    cookies = get_chrome_cookies()

    if not cookies:
        print("\n" + "=" * 60)
        print("INSTRUCTIONS:")
        print("=" * 60)
        print("1. Close Chrome completely")
        print("2. Start Chrome with debugging:")
        print(
            '   "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222'
        )
        print("3. Navigate to: https://poit.bolagsverket.se/poit-app/")
        print("4. Pass CAPTCHA if shown")
        print("5. Run this script again")
        print("=" * 60)
        return 1

    print(f"    Got {len(cookies)} cookies")

    # Create session with cookies
    session = requests.Session()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".bolagsverket.se")

    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
    )

    # Step 2: Fetch list
    print("\n[2] Fetching kungörelser list...")
    kungorelser = fetch_kungorelser_list(session, date_str)

    if not kungorelser:
        print("    No kungörelser found")
        return 1

    print(f"    Got {len(kungorelser)} kungörelser")

    # Create output folder
    date_folder = OUTPUT_DIR / date_str
    date_folder.mkdir(parents=True, exist_ok=True)

    # Save list
    list_file = date_folder / f"kungorelser_{date_str}.json"
    with open(list_file, "w", encoding="utf-8") as f:
        json.dump(
            {"meta": {"date": date_str}, "data": kungorelser},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"    Saved: {list_file.name}")

    # Step 3: Fetch individual pages
    print(f"\n[3] Fetching {args.count} individual pages...")

    to_fetch = [
        k.get("kungorelseid")
        for k in kungorelser[: args.count]
        if k.get("kungorelseid")
    ]
    success_count = 0

    for i, kung_id in enumerate(to_fetch, 1):
        normalized_id = kung_id.replace("/", "-")
        print(f"\n    [{i}/{len(to_fetch)}] {kung_id}")

        result = fetch_kungorelse_page(session, kung_id)

        if result["success"]:
            success_count += 1

            # Save HTML
            kung_folder = date_folder / normalized_id
            kung_folder.mkdir(parents=True, exist_ok=True)

            with open(kung_folder / "page.html", "w", encoding="utf-8") as f:
                f.write(result["html"])

            print(f"        ✓ Saved ({result['size']} bytes)")
        else:
            print(f"        ✗ {result.get('error', 'Failed')}")

        time.sleep(1)  # Be nice

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"List: {len(kungorelser)} kungörelser")
    print(f"Fetched: {success_count}/{len(to_fetch)} pages")
    print(f"Output: {date_folder}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
