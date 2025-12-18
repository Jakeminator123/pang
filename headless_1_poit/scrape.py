#!/usr/bin/env python3
"""
Headless scraping wrapper for main pipeline integration.

This module provides a simple interface for headless_main.py to run
the headless scraping and save results to 1_poit/info_server/.
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    import io
    try:
        if not isinstance(sys.stdout, io.TextIOWrapper) or getattr(sys.stdout, "encoding", None) != "utf-8":
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        if not isinstance(sys.stderr, io.TextIOWrapper) or getattr(sys.stderr, "encoding", None) != "utf-8":
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
POIT_INFO_SERVER = PROJECT_ROOT / "1_poit" / "info_server"
CONFIG_FILE = SCRIPT_DIR / "config.txt"
CONFIG_HEADLESS_FILE = SCRIPT_DIR / "config_headless.txt"

# =============================================================================
# COMPANY FILTERING - Skip holding companies, lagerbolag, etc. BEFORE scraping
# =============================================================================

# Keywords in company names to exclude
NAME_EXCLUDE_KEYWORDS = (
    "förening", "holding", "lagerbolag", "lagerbolaget", "startplattan",
    "stiftelse", "bostadsrättsförening", "brf ", "ideell", "kapital"
)

# Regex patterns for "shelf companies" (lagerbolag)
# Pattern 1: "Startplattan 201499 Aktiebolag"
# Pattern 2: "Lagerbolaget C 28068 AB"
LAGERBOLAG_PATTERNS = [
    re.compile(r"^[A-Za-zÅÄÖåäö]+\s+\d{5,6}\s+Aktiebolag$", re.IGNORECASE),
    re.compile(r"^[A-Za-zÅÄÖåäö]+\s+[A-Z]\s+\d{4,6}\s+AB$", re.IGNORECASE),
    re.compile(r"^[A-Za-zÅÄÖåäö]+\s+\d{4,6}\s+AB$", re.IGNORECASE),
]


def should_skip_company(name: str | None) -> bool:
    """
    Check if company should be skipped based on name patterns.
    Filters out holding companies, lagerbolag, shelf companies, etc.
    """
    if not isinstance(name, str) or not name:
        return False
    
    lowered = name.lower()
    
    # Check keywords
    if any(keyword in lowered for keyword in NAME_EXCLUDE_KEYWORDS):
        return True
    
    # Check lagerbolag patterns (e.g., "Startplattan 201499 Aktiebolag")
    stripped = name.strip()
    for pattern in LAGERBOLAG_PATTERNS:
        if pattern.match(stripped):
            return True
    
    return False


def load_max_kun_dag() -> int | None:
    """Load MAX_KUN_DAG from config_headless.txt. Returns None if ALL or not set."""
    if not CONFIG_HEADLESS_FILE.exists():
        return None
    
    with open(CONFIG_HEADLESS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("MAX_KUN_DAG="):
                value = line.split("=", 1)[1].strip()
                if value.upper() == "ALL":
                    return None  # No limit
                try:
                    return int(value)
                except ValueError:
                    return None
    return None


def load_config() -> dict:
    """Load configuration from config.txt and config_headless.txt."""
    config = {
        "parallel": 1,
        "visible": False,
        "wait_min": 4,
        "wait_max": 6,
        "between_min": 2,
        "between_max": 4,
        "cookie_wait": 14,
        "max_kun_dag": None,  # From config_headless.txt
    }
    
    # Load from config.txt
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
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
                        else:
                            try:
                                config[key] = int(value) if value else config[key]
                            except ValueError:
                                pass
    
    # Load MAX_KUN_DAG from config_headless.txt
    config["max_kun_dag"] = load_max_kun_dag()
    
    return config


async def run_headless_scrape(
    date_str: str,
    count: int | None = None,
    visible: bool = False
) -> tuple[bool, int, int]:
    """
    Run headless scraping and save results to 1_poit/info_server/.
    
    Args:
        date_str: Date string in YYYYMMDD format
        count: Number of kungörelser to scrape. If None, uses MAX_KUN_DAG from config_headless.txt
        visible: Whether to show Chrome window
    
    Returns:
        Tuple of (success, total_in_list, successfully_scraped)
    """
    # Import here to avoid circular imports
    from lib.chrome import start_chrome, stop_chrome
    from lib.api import create_session, fetch_kungorelser_list
    from lib.scraper import get_cookies_from_chrome, scrape_kungorelse_pages
    
    config = load_config()
    if visible:
        config["visible"] = True
    
    # Determine count: use argument > config_headless.txt > default 20
    max_kun_dag = config.get("max_kun_dag")
    if count is None:
        count = max_kun_dag if max_kun_dag else 20
    elif max_kun_dag and count > max_kun_dag:
        # If argument is larger than config limit, use config limit
        print(f"    [CONFIG] Begränsar till {max_kun_dag} (från config_headless.txt)")
        count = max_kun_dag
    
    # API date format
    api_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    
    # Output folder - save to 1_poit/info_server/
    output_folder = POIT_INFO_SERVER / date_str
    output_folder.mkdir(parents=True, exist_ok=True)
    
    # Show config source
    count_source = "config_headless.txt" if max_kun_dag else "argument/default"
    
    print("=" * 60)
    print("HEADLESS SCRAPING")
    print("=" * 60)
    print(f"  Datum:      {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")
    print(f"  Max antal:  {count} (från {count_source})")
    print(f"  Output:     {output_folder}")
    print(f"  Chrome:     {'synlig' if config['visible'] else 'off-screen'}")
    print("=" * 60)
    
    chrome_proc = None
    total_in_list = 0
    success_count = 0
    
    try:
        # Step 1: Start Chrome
        print(f"\n[HEADLESS 1/4] Startar Chrome...")
        chrome_proc = start_chrome(visible=config["visible"])
        
        # Step 2: Get cookies
        print(f"\n[HEADLESS 2/4] Hämtar cookies från Chrome...")
        cookies = await get_cookies_from_chrome(cookie_wait=config["cookie_wait"])
        
        if not cookies:
            print("    ✗ Inga cookies! Kontrollera att Chrome körs.")
            return False, 0, 0
        
        print(f"    ✓ {len(cookies)} cookies hämtade")
        
        # Step 3: Fetch list via API
        print(f"\n[HEADLESS 3/4] Hämtar kungörelselista via API...")
        session = create_session(cookies)
        kungorelser = fetch_kungorelser_list(session, api_date)
        
        if not kungorelser:
            print("    ✗ Inga kungörelser hittades för detta datum")
            return False, 0, 0
        
        total_in_list = len(kungorelser)
        print(f"    ✓ {total_in_list} kungörelser hittade")
        
        # Step 4: Filter and scrape individual pages
        # First filter out holding companies, lagerbolag, etc. BEFORE scraping
        filtered_kungorelser = []
        skipped_count = 0
        for k in kungorelser:
            company_name = k.get("namn", "")
            if should_skip_company(company_name):
                skipped_count += 1
            else:
                filtered_kungorelser.append(k)
        
        if skipped_count > 0:
            print(f"    [FILTER] Hoppade över {skipped_count} holding/lagerbolag")
        
        # Save the filtered list (same format as server/extension expects)
        list_file = output_folder / f"kungorelser_{date_str}.json"
        output_data = {
            "meta": {
                "timestamp": datetime.now().isoformat(),
                "date": api_date,
                "item_count": len(filtered_kungorelser),
                "original_count": total_in_list,
                "filtered_out": skipped_count
            },
            "data": filtered_kungorelser
        }
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"    Sparad: {list_file.name} ({len(filtered_kungorelser)} företag efter filtrering)")
        
        # Now create to_scrape list from filtered list
        to_scrape = [
            k.get("kungorelseid") 
            for k in filtered_kungorelser[:count] 
            if k.get("kungorelseid")
        ]
        
        print(f"\n[HEADLESS 4/4] Scraping {len(to_scrape)} kungörelser...")
        start_time = time.time()
        
        results = await scrape_kungorelse_pages(
            to_scrape, 
            output_folder, 
            parallel=config["parallel"],
            wait_range=(config["wait_min"], config["wait_max"]),
            between_range=(config["between_min"], config["between_max"])
        )
        
        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r.get("success"))
        
        # Summary
        print("\n" + "=" * 60)
        print("HEADLESS SCRAPING - SAMMANFATTNING")
        print("=" * 60)
        print(f"  Kungörelser i listan:  {total_in_list}")
        print(f"  Försökte hämta:        {len(to_scrape)}")
        print(f"  Lyckades:              {success_count}")
        print(f"  Misslyckades:          {len(to_scrape) - success_count}")
        print(f"  Tid:                   {elapsed:.1f}s ({elapsed/max(1,len(to_scrape)):.1f}s/sida)")
        print(f"  Output:                {output_folder}")
        print("=" * 60)
        
        return True, total_in_list, success_count
        
    except KeyboardInterrupt:
        print("\n\n[AVBRUTET] Ctrl+C")
        return False, total_in_list, success_count
    except Exception as e:
        print(f"\n[HEADLESS ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False, total_in_list, success_count
    finally:
        if chrome_proc and not config["visible"]:
            stop_chrome(chrome_proc)


# Allow running standalone for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Headless scraping")
    parser.add_argument("--count", "-c", type=int, default=10, help="Antal kungörelser")
    parser.add_argument("--date", "-d", type=str, default=datetime.now().strftime("%Y%m%d"), help="Datum (YYYYMMDD)")
    parser.add_argument("--visible", "-v", action="store_true", help="Visa Chrome")
    args = parser.parse_args()
    
    success, total, scraped = asyncio.run(run_headless_scrape(args.date, args.count, args.visible))
    sys.exit(0 if success else 1)

