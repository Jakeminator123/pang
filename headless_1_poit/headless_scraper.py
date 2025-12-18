#!/usr/bin/env python3
"""
Headless scraper for Bolagsverket kungörelser.

Completely headless - uses only requests, no browser needed.

1. Fetches kungörelser list from API
2. Tries to fetch individual kungörelse details via API
3. Saves everything to testning/output/

Usage:
    python headless_scraper.py           # Default: 3 kungörelser
    python headless_scraper.py 5         # Test 5 kungörelser
    python headless_scraper.py --date 20251217
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Paths
TESTNING_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = TESTNING_DIR / "output"
LOG_DIR = TESTNING_DIR / "logs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# URLs
BASE_URL = "https://poit.bolagsverket.se"
API_BASE = f"{BASE_URL}/poit/rest"
START_URL = f"{BASE_URL}/poit-app/"


def create_session() -> requests.Session:
    """Create session with browser-like headers."""
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": START_URL,
            "Origin": BASE_URL,
        }
    )
    return session


def fetch_kungorelser_list(session: requests.Session, date_str: str) -> list:
    """Fetch kungörelser list from API."""
    # Format date
    if len(date_str) == 8 and date_str.isdigit():
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
    print(f"[API] GET {url}")

    try:
        response = session.get(url, params=params, timeout=30)
        print(f"[API] Status: {response.status_code}")

        if response.status_code == 200 and response.text.strip():
            data = response.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        print(f"[API] Error: {e}")

    return []


def fetch_kungorelse_details(session: requests.Session, kung_id: str) -> dict:
    """
    Try to fetch individual kungörelse details via API.

    Tries several possible API endpoints.
    """
    # Normalize ID: K959439/25 -> K959439-25
    normalized_id = kung_id.replace("/", "-")

    # Try different API endpoints
    endpoints = [
        f"{API_BASE}/Kungorelse/{normalized_id}",
        f"{API_BASE}/kungorelse/{normalized_id}",
        f"{API_BASE}/HamtaKungorelse/{normalized_id}",
        f"{API_BASE}/GetKungorelse/{normalized_id}",
        f"{API_BASE}/SokKungorelse?kungorelseid={kung_id}",
        f"{API_BASE}/SokKungorelse?kungorelseid={normalized_id}",
    ]

    for endpoint in endpoints:
        try:
            response = session.get(endpoint, timeout=15)

            if response.status_code == 200:
                text = response.text.strip()
                if text and text != "[]" and len(text) > 10:
                    try:
                        data = response.json()
                        if data:
                            return {
                                "success": True,
                                "endpoint": endpoint,
                                "data": data,
                            }
                    except json.JSONDecodeError:
                        # Maybe it's HTML with content?
                        if len(text) > 500 and "javascript" not in text.lower():
                            return {
                                "success": True,
                                "endpoint": endpoint,
                                "html": text,
                            }
        except Exception:
            pass

    return {"success": False}


def main():
    parser = argparse.ArgumentParser(description="Headless Bolagsverket scraper")
    parser.add_argument(
        "count",
        nargs="?",
        type=int,
        default=3,
        help="Kungörelser to fetch (default: 3)",
    )
    parser.add_argument("--date", "-d", type=str, default=None, help="Date (YYYYMMDD)")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y%m%d")

    print("=" * 60)
    print("HEADLESS BOLAGSVERKET SCRAPER")
    print("=" * 60)
    print(f"Date: {date_str}")
    print(f"Count: {args.count}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    # Create output folder
    date_folder = OUTPUT_DIR / date_str
    date_folder.mkdir(parents=True, exist_ok=True)

    # Create session
    session = create_session()

    # Step 1: Fetch list
    print("\n[1] Fetching kungörelser list...")
    kungorelser = fetch_kungorelser_list(session, date_str)

    if not kungorelser:
        print("    ✗ No kungörelser found")
        return 1

    print(f"    ✓ Got {len(kungorelser)} kungörelser")

    # Save list
    list_file = date_folder / f"kungorelser_{date_str}.json"
    with open(list_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "meta": {"date": date_str, "count": len(kungorelser)},
                "data": kungorelser,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"    Saved to: {list_file.name}")

    # Print sample
    print("\n    Sample:")
    for i, k in enumerate(kungorelser[:5], 1):
        kid = k.get("kungorelseid", "?")
        namn = k.get("namn", "?")
        print(f"      {i}. {kid}: {namn}")

    # Step 2: Try to fetch individual details
    print("\n[2] Testing API endpoints for individual kungörelser...")

    to_fetch = [
        k.get("kungorelseid")
        for k in kungorelser[: args.count]
        if k.get("kungorelseid")
    ]

    found_endpoint = None
    success_count = 0

    for i, kung_id in enumerate(to_fetch, 1):
        print(f"\n    [{i}/{len(to_fetch)}] {kung_id}")

        result = fetch_kungorelse_details(session, kung_id)

        if result["success"]:
            success_count += 1
            endpoint = result.get("endpoint", "?")
            print(f"        ✓ Found data via: {endpoint}")

            if not found_endpoint:
                found_endpoint = endpoint

            # Save the data
            normalized_id = kung_id.replace("/", "-")
            kung_folder = date_folder / normalized_id
            kung_folder.mkdir(parents=True, exist_ok=True)

            if "data" in result:
                with open(kung_folder / "data.json", "w", encoding="utf-8") as f:
                    json.dump(result["data"], f, ensure_ascii=False, indent=2)
                print(f"        Saved: {normalized_id}/data.json")
            elif "html" in result:
                with open(kung_folder / "content.html", "w", encoding="utf-8") as f:
                    f.write(result["html"])
                print(f"        Saved: {normalized_id}/content.html")
        else:
            print("        ✗ No API endpoint found")

        time.sleep(0.5)  # Be nice to the server

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total in API list: {len(kungorelser)}")
    print(f"Attempted to fetch: {len(to_fetch)}")
    print(f"Successfully fetched: {success_count}")

    if found_endpoint:
        print(f"\nWorking API endpoint: {found_endpoint}")  # noqa: F541
    else:
        print("\n⚠ No working API endpoint found for individual kungörelser.")
        print("  The site may require JavaScript rendering.")
        print("  Options:")
        print("    1. Use browser automation (pyautogui + extension)")
        print("    2. The list data may already contain what you need")

    print(f"\nOutput: {date_folder}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
