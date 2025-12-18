#!/usr/bin/env python3
"""
Standalone script to test Bolagsverket API kungörelse count.
Queries the API directly and shows how many kungörelser exist for a given date.
"""

import sys
from datetime import datetime

import requests


def get_kungorelse_count(date_str: str = None) -> dict:
    """
    Query Bolagsverket API for kungörelser on a specific date.

    Args:
        date_str: Date in format YYYY-MM-DD (defaults to today)

    Returns:
        dict with count and sample data
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # API endpoint (discovered from extension traffic)
    base_url = "https://poit.bolagsverket.se/poit/rest/SokKungorelse"

    # Query parameters for "Konkurs" under "Aktiebolagsregistret"
    params = {
        "sokord": "",
        "kungorelseid": "",
        "kungorelseObjektPersonOrgnummer": "",
        "kungorelseObjektNamn": "",
        "tidsperiod": "ANNAN_PERIOD",
        "tidsperiodFrom": date_str,
        "tidsperiodTom": date_str,
        "amnesomradeId": "2",  # Bolagsverket
        "kungorelsetypId": "4",  # Aktiebolagsregistret
        "underRubrikId": "6",  # Konkurs
    }

    print(f"\n{'=' * 60}")
    print("BOLAGSVERKET API TEST")
    print(f"{'=' * 60}")
    print(f"Date: {date_str}")
    print(f"URL: {base_url}")
    print("Params: amnesomradeId=2, kungorelsetypId=4, underRubrikId=6")
    print(f"{'=' * 60}\n")

    # Browser-like headers (API may reject bare requests)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://poit.bolagsverket.se/poit-app/",
        "Origin": "https://poit.bolagsverket.se",
    }

    try:
        # Make the request
        print("Sending request...")
        response = requests.get(base_url, params=params, headers=headers, timeout=30)

        # Debug: show status and content type
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")

        if response.status_code != 200:
            print(f"Response text: {response.text[:500]}")
            return {"success": False, "error": f"HTTP {response.status_code}"}

        if not response.text.strip():
            print("Empty response - API may require session/cookies")
            return {"success": False, "error": "Empty response"}

        response.raise_for_status()

        data = response.json()

        if isinstance(data, list):
            count = len(data)
            print(f"✅ SUCCESS! Got {count} kungörelser")
            print()

            # Show first 5 as sample
            if count > 0:
                print("First 5 kungörelser:")
                print("-" * 40)
                for i, item in enumerate(data[:5]):
                    kid = item.get("kungorelseid", "?")
                    name = item.get("namn", "?")
                    print(f"  {i + 1}. {kid}: {name}")

                if count > 5:
                    print(f"  ... and {count - 5} more")

            return {"success": True, "count": count, "date": date_str, "data": data}
        else:
            print(f"❌ Unexpected response type: {type(data)}")
            return {"success": False, "error": "Unexpected response type"}

    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"success": False, "error": str(e)}


def main():
    # Get date from command line or use today
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        # Convert YYYYMMDD to YYYY-MM-DD if needed
        if len(date_str) == 8 and date_str.isdigit():
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    result = get_kungorelse_count(date_str)

    print()
    print("=" * 60)
    if result["success"]:
        print(f"RESULT: {result['count']} kungörelser for {result['date']}")
    else:
        print(f"RESULT: Failed - {result.get('error', 'Unknown error')}")
    print("=" * 60)

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
