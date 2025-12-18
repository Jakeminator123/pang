#!/usr/bin/env python3
"""
Docker-ready headless scraper for Bolagsverket kungörelser.

Entry point for Docker container. Handles both Docker (headless) and local modes.

Usage:
    # In Docker (via docker-compose)
    docker-compose up --build
    
    # Local testing
    python scrape.py --count 10 --date 20251218 --visible
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Fix encoding for Windows terminal
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
CONFIG_FILE = SCRIPT_DIR / "config.txt"

# Docker output path vs local path
IS_DOCKER = (
    os.environ.get("IS_DOCKER", "").lower() == "true" or
    os.environ.get("HEADLESS", "").lower() == "true" or
    Path("/.dockerenv").exists()
)

if IS_DOCKER:
    # In Docker: output is mounted volume
    OUTPUT_DIR = Path("/app/output")
else:
    # Local: use project's info_server
    PROJECT_ROOT = SCRIPT_DIR.parent
    OUTPUT_DIR = PROJECT_ROOT / "1_poit" / "info_server"


def load_config() -> dict:
    """Load configuration from config.txt and environment variables."""
    config = {
        "parallel": 1,
        "visible": False,
        "wait_min": 4,
        "wait_max": 6,
        "between_min": 2,
        "between_max": 4,
        "cookie_wait": 15,  # Viktigt för TS-cookies!
    }
    
    # Load from file
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
    
    # Override with environment variables
    if os.environ.get("SCRAPE_COUNT"):
        try:
            config["count"] = int(os.environ["SCRAPE_COUNT"])
        except ValueError:
            pass
    
    if os.environ.get("COOKIE_WAIT"):
        try:
            config["cookie_wait"] = int(os.environ["COOKIE_WAIT"])
        except ValueError:
            pass
    
    # Force headless in Docker
    if IS_DOCKER:
        config["visible"] = False
    
    return config


async def run_docker_scrape(
    date_str: str,
    count: int,
    visible: bool = False
) -> tuple[bool, int, int]:
    """
    Run scraping in Docker mode (or local with native browser).
    
    Args:
        date_str: Date string in YYYYMMDD format
        count: Number of kungörelser to scrape
        visible: Whether to show browser (ignored in Docker)
    
    Returns:
        Tuple of (success, total_in_list, successfully_scraped)
    """
    from lib.scraper import (
        get_browser_context, 
        get_cookies_from_browser,
        scrape_kungorelse_pages,
        IS_DOCKER
    )
    from lib.api import create_session, fetch_kungorelser_list
    
    config = load_config()
    if visible and not IS_DOCKER:
        config["visible"] = True
    
    # API date format
    api_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    
    # Output folder
    output_folder = OUTPUT_DIR / date_str
    output_folder.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("DOCKER HEADLESS SCRAPING" if IS_DOCKER else "HEADLESS SCRAPING")
    print("=" * 60)
    print(f"  Miljö:      {'Docker' if IS_DOCKER else 'Lokal'}")
    print(f"  Datum:      {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}")
    print(f"  Max antal:  {count}")
    print(f"  Output:     {output_folder}")
    print(f"  Browser:    {'headless Chromium' if IS_DOCKER else 'Chrome CDP'}")
    print("=" * 60)
    
    p = None
    browser = None
    context = None
    is_launched = False
    total_in_list = 0
    success_count = 0
    
    try:
        # Step 1: Get browser and context
        print(f"\n[SCRAPER 1/4] Startar browser...")
        p, browser, context, is_launched = await get_browser_context()
        print(f"    ✓ Browser redo")
        
        # Step 2: Get cookies
        print(f"\n[SCRAPER 2/4] Hämtar cookies...")
        cookies = await get_cookies_from_browser(context, cookie_wait=config["cookie_wait"])
        
        if not cookies:
            print("    ✗ Inga cookies! Kontrollera att sidan laddades.")
            return False, 0, 0
        
        print(f"    ✓ {len(cookies)} cookies hämtade")
        
        # Step 3: Fetch list via API
        print(f"\n[SCRAPER 3/4] Hämtar kungörelselista via API...")
        session = create_session(cookies)
        kungorelser = fetch_kungorelser_list(session, api_date)
        
        if not kungorelser:
            print("    ✗ Inga kungörelser hittades för detta datum")
            return False, 0, 0
        
        total_in_list = len(kungorelser)
        print(f"    ✓ {total_in_list} kungörelser hittade")
        
        # Save the list (same format as extension)
        list_file = output_folder / f"kungorelser_{date_str}.json"
        with open(list_file, "w", encoding="utf-8") as f:
            json.dump(kungorelser, f, ensure_ascii=False, indent=2)
        print(f"    Sparad: {list_file.name}")
        
        # Step 4: Scrape individual pages
        to_scrape = [
            k.get("kungorelseid") 
            for k in kungorelser[:count] 
            if k.get("kungorelseid")
        ]
        
        print(f"\n[SCRAPER 4/4] Scraping {len(to_scrape)} kungörelser...")
        start_time = time.time()
        
        results = await scrape_kungorelse_pages(
            to_scrape, 
            output_folder, 
            parallel=config["parallel"],
            wait_range=(config["wait_min"], config["wait_max"]),
            between_range=(config["between_min"], config["between_max"]),
            context=context
        )
        
        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r.get("success"))
        
        # Summary
        print("\n" + "=" * 60)
        print("SCRAPING - SAMMANFATTNING")
        print("=" * 60)
        print(f"  Miljö:                 {'Docker' if IS_DOCKER else 'Lokal'}")
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
        print(f"\n[SCRAPER ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False, total_in_list, success_count
    finally:
        # Cleanup browser/context if we launched it
        if is_launched and browser:
            try:
                # For persistent context, browser IS the context
                if hasattr(browser, 'close'):
                    await browser.close()
                print("    Browser stängd.")
            except Exception as e:
                print(f"    [WARN] Kunde inte stänga browser: {e}")
        if p:
            try:
                await p.stop()
            except Exception:
                pass


# Legacy function for backward compatibility with headless_main.py
async def run_headless_scrape(
    date_str: str,
    count: int,
    visible: bool = False
) -> tuple[bool, int, int]:
    """
    Legacy wrapper for backward compatibility.
    Calls run_docker_scrape internally.
    """
    return await run_docker_scrape(date_str, count, visible)


def main():
    """Main entry point for CLI and Docker."""
    import argparse
    
    # Get defaults from environment
    default_date = os.environ.get("TARGET_DATE", datetime.now().strftime("%Y%m%d"))
    default_count = int(os.environ.get("SCRAPE_COUNT", "10"))
    
    parser = argparse.ArgumentParser(description="Bolagsverket Kungörelse Scraper (Docker-ready)")
    parser.add_argument("--count", "-c", type=int, default=default_count, help="Antal kungörelser att hämta")
    parser.add_argument("--date", "-d", type=str, default=default_date, help="Datum (YYYYMMDD)")
    parser.add_argument("--visible", "-v", action="store_true", help="Visa browser (ignoreras i Docker)")
    args = parser.parse_args()
    
    success, total, scraped = asyncio.run(run_docker_scrape(args.date, args.count, args.visible))
    
    # Exit code
    if not success:
        sys.exit(1)
    elif scraped == 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
