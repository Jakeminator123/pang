#!/usr/bin/env python3
"""
Bolagsverket Kungörelse Scraper - Headless Edition
===================================================
Startar Chrome en gång för cookies, använder API för lista,
och Playwright för att scrapa enskilda kungörelser.

Snabbare än 1_poit/automation genom att skippa bildigenkänning.

Usage:
    python main.py                    # 20 kungörelser, dagens datum
    python main.py --count 50         # 50 st
    python main.py --date 20251217    # Specifikt datum
    python main.py --visible          # Visa Chrome (för debugging/CAPTCHA)
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Local imports
from lib.chrome import start_chrome, stop_chrome
from lib.api import create_session, fetch_kungorelser_list
from lib.scraper import get_cookies_from_chrome, scrape_kungorelse_pages

# Paths
SCRIPT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = SCRIPT_DIR / "output"
CONFIG_FILE = SCRIPT_DIR / "config.txt"


def load_config() -> dict:
    """Load configuration from config.txt."""
    config = {
        "count": 20,
        "date": "",
        "parallel": 1,
        "visible": False,
        "wait_min": 4,
        "wait_max": 6,
        "between_min": 2,
        "between_max": 4,
        "cookie_wait": 14,
    }
    
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
                        elif key == "date":
                            config[key] = value
                        else:
                            try:
                                config[key] = int(value) if value else config[key]
                            except ValueError:
                                pass
    return config


def print_banner(config: dict, date_str: str):
    """Print startup banner with configuration."""
    print("=" * 60)
    print("BOLAGSVERKET KUNGÖRELSE SCRAPER")
    print("Testning Edition")
    print("=" * 60)
    print(f"  Datum:      {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")
    print(f"  Antal:      {config['count']}")
    print(f"  Parallell:  {config['parallel']} tab(s)")
    print(f"  Väntetid:   {config['wait_min']}-{config['wait_max']}s per sida")
    print(f"  Cookie-väntan: {config['cookie_wait']}s")
    print(f"  Chrome:     {'synlig' if config['visible'] else 'minimerad (off-screen)'}")
    print("=" * 60)


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Bolagsverket Kungörelse Scraper")
    parser.add_argument("--count", "-c", type=int, help="Antal kungörelser att hämta")
    parser.add_argument("--date", "-d", type=str, help="Datum (YYYYMMDD)")
    parser.add_argument("--visible", "-v", action="store_true", help="Visa Chrome-fönster")
    args = parser.parse_args()
    
    # Load config and override with command line args
    config = load_config()
    if args.count:
        config["count"] = args.count
    if args.date:
        config["date"] = args.date
    if args.visible:
        config["visible"] = True
    
    # Date handling
    if config["date"]:
        date_str = config["date"].replace("-", "")
    else:
        date_str = datetime.now().strftime("%Y%m%d")
    
    api_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    
    # Create output folder
    output_folder = OUTPUT_DIR / date_str
    output_folder.mkdir(parents=True, exist_ok=True)
    
    print_banner(config, date_str)
    
    chrome_proc = None
    
    try:
        # Step 1: Start Chrome
        print(f"\n[1/4] Startar Chrome...")
        chrome_proc = start_chrome(visible=config["visible"])
        
        # Step 2: Get cookies from Chrome (handles cookie banner)
        print(f"\n[2/4] Hämtar cookies från Chrome...")
        cookies = await get_cookies_from_chrome(cookie_wait=config["cookie_wait"])
        
        if not cookies:
            print("    ✗ Inga cookies! Kontrollera att Chrome körs korrekt.")
            print("    Tips: Stäng alla Chrome-fönster och försök igen.")
            return 1
        
        print(f"    ✓ {len(cookies)} cookies hämtade")
        
        # Step 3: Fetch kungörelser list via API
        print(f"\n[3/4] Hämtar kungörelselista via API...")
        session = create_session(cookies)
        kungorelser = fetch_kungorelser_list(session, api_date)
        
        if not kungorelser:
            print("    ✗ Inga kungörelser hittades för detta datum")
            return 1
        
        print(f"    ✓ {len(kungorelser)} kungörelser hittade")
        
        # Save the list
        list_file = output_folder / f"kungorelser_{date_str}.json"
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(kungorelser, f, ensure_ascii=False, indent=2)
        print(f"    Sparad: {list_file.name}")
        
        # Step 4: Scrape individual kungörelser
        to_scrape = [
            k.get("kungorelseid") 
            for k in kungorelser[:config["count"]] 
            if k.get("kungorelseid")
        ]
        
        print(f"\n[4/4] Scraping {len(to_scrape)} kungörelser...")
        start_time = time.time()
        
        results = await scrape_kungorelse_pages(
            to_scrape, 
            output_folder, 
            parallel=config["parallel"],
            wait_range=(config["wait_min"], config["wait_max"]),
            between_range=(config["between_min"], config["between_max"])
        )
        
        elapsed = time.time() - start_time
        
        # Summary
        success_count = sum(1 for r in results if r.get("success"))
        
        print("\n" + "=" * 60)
        print("SAMMANFATTNING")
        print("=" * 60)
        print(f"  Kungörelser i listan:  {len(kungorelser)}")
        print(f"  Försökte hämta:        {len(to_scrape)}")
        print(f"  Lyckades:              {success_count}")
        print(f"  Misslyckades:          {len(to_scrape) - success_count}")
        print(f"  Tid:                   {elapsed:.1f}s ({elapsed/max(1,len(to_scrape)):.1f}s/sida)")
        print(f"  Output:                {output_folder}")
        print("=" * 60)
        
        if chrome_proc:
            print("\n[INFO] Chrome körs fortfarande. Stäng manuellt eller tryck Ctrl+C.")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n[AVBRUTET] Ctrl+C")
        return 130
    except Exception as e:
        print(f"\n[FEL] {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Only auto-close Chrome if it's hidden
        if chrome_proc and not config["visible"]:
            stop_chrome(chrome_proc)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

