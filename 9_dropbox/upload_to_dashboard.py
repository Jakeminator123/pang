#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_to_dashboard.py - Upload ZIP bundles to the dashboard's persistent storage

Usage:
    python upload_to_dashboard.py                 # Upload latest bundle
    python upload_to_dashboard.py 20251219        # Upload specific date
    python upload_to_dashboard.py --all           # Upload all bundles

Environment variables:
    UPLOAD_SECRET     - API key for dashboard authentication (required)
    DASHBOARD_URL     - Dashboard base URL (default: https://jocke-dashboard.onrender.com)
    
The script reads ZIP files from 10_jocke/data_bundles/ and uploads them to
the dashboard's API endpoint, which extracts them to persistent storage.
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Tuple
import urllib.request
import urllib.error
import json

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOCKE_DIR = PROJECT_ROOT / "10_jocke"
DATA_BUNDLES_DIR = JOCKE_DIR / "data_bundles"

# Load .env file from project root
def load_env_file():
    """Load environment variables from .env file."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value

load_env_file()

# Dashboard config
DEFAULT_DASHBOARD_URL = "https://jocke.onrender.com"
UPLOAD_ENDPOINT = "/api/upload/bundle"
DATES_ENDPOINT = "/api/data/dates"

# Timeout for upload (5 minutes for large files)
UPLOAD_TIMEOUT = 300


def get_dashboard_url() -> str:
    """Get dashboard URL from environment or use default."""
    return os.environ.get("DASHBOARD_URL", DEFAULT_DASHBOARD_URL).rstrip("/")


def get_upload_secret() -> Optional[str]:
    """Get upload secret from environment."""
    # Try multiple possible env var names
    for var_name in ["UPLOAD_SECRET", "JOCKE_API", "DASHBOARD_API_KEY"]:
        secret = os.environ.get(var_name)
        if secret:
            return secret
    return None


def find_bundles(specific_date: Optional[str] = None) -> List[Path]:
    """
    Find ZIP bundles to upload.
    
    Args:
        specific_date: If provided, only return bundle for this date
        
    Returns:
        List of paths to ZIP files, sorted by date (newest first)
    """
    if not DATA_BUNDLES_DIR.exists():
        print(f"[ERROR] data_bundles directory not found: {DATA_BUNDLES_DIR}")
        return []
    
    bundles = []
    for zip_file in DATA_BUNDLES_DIR.glob("*.zip"):
        # Extract date from filename (expecting YYYYMMDD.zip)
        date_str = zip_file.stem
        if len(date_str) == 8 and date_str.isdigit():
            if specific_date is None or date_str == specific_date:
                bundles.append(zip_file)
    
    # Sort by date (newest first)
    bundles.sort(key=lambda x: x.stem, reverse=True)
    return bundles


def upload_bundle(zip_path: Path, dashboard_url: str, secret: str) -> Tuple[bool, str]:
    """
    Upload a ZIP bundle to the dashboard.
    
    Args:
        zip_path: Path to the ZIP file
        dashboard_url: Base URL of the dashboard
        secret: API secret for authentication
        
    Returns:
        (success: bool, message: str)
    """
    date_str = zip_path.stem
    upload_url = f"{dashboard_url}{UPLOAD_ENDPOINT}"
    
    print(f"[UPLOAD] Uploading {zip_path.name} to {dashboard_url}...")
    print(f"  File size: {zip_path.stat().st_size / 1024 / 1024:.2f} MB")
    
    try:
        # Read the ZIP file
        with open(zip_path, "rb") as f:
            data = f.read()
        
        # Create the request
        request = urllib.request.Request(
            upload_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {secret}",
                "X-Date": date_str,
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
            }
        )
        
        # Send the request
        start_time = time.time()
        with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT) as response:
            duration = time.time() - start_time
            response_data = response.read().decode("utf-8")
            
            try:
                result = json.loads(response_data)
            except json.JSONDecodeError:
                result = {"raw": response_data}
            
            if response.status == 200:
                files_count = result.get("filesExtracted", "?")
                print(f"  [OK] Success! Extracted {files_count} files in {duration:.1f}s")
                return True, result.get("message", "Upload successful")
            else:
                error = result.get("error", response_data)
                print(f"  [ERROR] Server returned status {response.status}: {error}")
                return False, error
                
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
            error_json = json.loads(error_body)
            error_body = error_json.get("error", error_body)
        except Exception:
            pass
        print(f"  [ERROR] HTTP Error {e.code}: {error_body or e.reason}")
        return False, f"HTTP {e.code}: {error_body or e.reason}"
        
    except urllib.error.URLError as e:
        print(f"  [ERROR] Connection error: {e.reason}")
        return False, f"Connection error: {e.reason}"
        
    except TimeoutError:
        print(f"  [ERROR] Upload timed out after {UPLOAD_TIMEOUT}s")
        return False, "Upload timed out"
        
    except Exception as e:
        print(f"  [ERROR] Unexpected error: {e}")
        return False, str(e)


def get_existing_dates_on_server(dashboard_url: str, secret: str) -> List[str]:
    """
    Get list of dates that already exist on the server.
    
    Returns:
        List of date strings (YYYYMMDD) that already exist on the server
    """
    dates_url = f"{dashboard_url}{DATES_ENDPOINT}"
    
    try:
        request = urllib.request.Request(
            dates_url,
            method="GET",
            headers={"Authorization": f"Bearer {secret}"}
        )
        
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                dates = data.get("dates", [])
                # Extract just the date strings
                return [d.get("date", d) if isinstance(d, dict) else d for d in dates]
            return []
            
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("[WARN] Cannot check existing dates - unauthorized")
        else:
            print(f"[WARN] Cannot check existing dates - HTTP {e.code}")
        return []
        
    except Exception as e:
        print(f"[WARN] Cannot check existing dates: {e}")
        return []


def interactive_select(bundles: List[Path], existing_dates: List[str]) -> List[Path]:
    """
    Interactive selection of bundles to upload.
    
    Args:
        bundles: All available bundles
        existing_dates: Dates that already exist on server
        
    Returns:
        List of selected bundles to upload
    """
    if not bundles:
        print("\n[INFO] No bundles available")
        return []
    
    print("\n" + "=" * 60)
    print("AVAILABLE BUNDLES")
    print("=" * 60)
    print("\n  #  Date        Size      Status")
    print("  " + "-" * 45)
    
    for i, bundle in enumerate(bundles, 1):
        date_str = bundle.stem
        size_mb = bundle.stat().st_size / 1024 / 1024
        exists = date_str in existing_dates
        status = "[EXISTS]" if exists else "[NEW]"
        status_color = status
        print(f"  {i:2}. {date_str}    {size_mb:6.2f} MB  {status_color}")
    
    print("\n  " + "-" * 45)
    print("  Options:")
    print("    - Enter numbers (e.g., 1,2,3 or 1-3)")
    print("    - 'all' or 'a' = Upload all")
    print("    - 'new' or 'n' = Upload only NEW (not on server)")
    print("    - 'q' or Enter = Cancel")
    print()
    
    try:
        choice = input("  Select bundles to upload: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return []
    
    if not choice or choice in ("q", "quit", "exit"):
        print("  Cancelled.")
        return []
    
    selected: List[Path] = []
    
    if choice in ("all", "a"):
        selected = bundles
        print(f"\n  Selected ALL ({len(selected)} bundles)")
    elif choice in ("new", "n"):
        selected = [b for b in bundles if b.stem not in existing_dates]
        print(f"\n  Selected NEW only ({len(selected)} bundles)")
    else:
        # Parse number selections (e.g., "1,2,3" or "1-3" or "1,3-5")
        indices = set()
        parts = choice.replace(" ", "").split(",")
        for part in parts:
            if "-" in part:
                try:
                    start, end = part.split("-", 1)
                    for i in range(int(start), int(end) + 1):
                        indices.add(i)
                except ValueError:
                    pass
            else:
                try:
                    indices.add(int(part))
                except ValueError:
                    pass
        
        for i in sorted(indices):
            if 1 <= i <= len(bundles):
                selected.append(bundles[i - 1])
        
        if selected:
            print(f"\n  Selected {len(selected)} bundle(s): {', '.join(b.stem for b in selected)}")
        else:
            print("  No valid selection.")
            return []
    
    # Confirm if any already exist
    existing_selected = [b for b in selected if b.stem in existing_dates]
    if existing_selected:
        print(f"\n  WARNING: {len(existing_selected)} bundle(s) already exist on server:")
        for b in existing_selected:
            print(f"    - {b.stem}")
        try:
            confirm = input("  Overwrite? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return []
        
        if confirm not in ("y", "yes"):
            # Remove existing from selection
            selected = [b for b in selected if b.stem not in existing_dates]
            print(f"  Removed existing. {len(selected)} bundle(s) remaining.")
    
    return selected


def check_dashboard_status(dashboard_url: str, secret: str) -> bool:
    """
    Check if the dashboard is accessible and the API key is valid.
    
    Returns:
        True if dashboard is ready, False otherwise
    """
    status_url = f"{dashboard_url}{UPLOAD_ENDPOINT}"
    
    try:
        request = urllib.request.Request(
            status_url,
            method="GET",
            headers={"Authorization": f"Bearer {secret}"}
        )
        
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                print(f"[INFO] Dashboard status: {data.get('status', 'unknown')}")
                storage = data.get("storage", {})
                if storage.get("persistent", {}).get("available"):
                    print("[INFO] Persistent disk: Available")
                else:
                    print("[INFO] Persistent disk: Not available (will use local storage)")
                return True
            return False
            
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("[ERROR] Invalid API key")
        else:
            print(f"[ERROR] Dashboard returned HTTP {e.code}")
        return False
        
    except Exception as e:
        print(f"[ERROR] Cannot reach dashboard: {e}")
        return False


def main():
    """Main function."""
    print("=" * 60)
    print("UPLOAD TO DASHBOARD")
    print("=" * 60)
    
    # Get configuration
    dashboard_url = get_dashboard_url()
    secret = get_upload_secret()
    
    print(f"Dashboard URL: {dashboard_url}")
    
    if not secret:
        print("\n[ERROR] No upload secret found!")
        print("Set one of these environment variables:")
        print("  - UPLOAD_SECRET")
        print("  - JOCKE_API")
        print("  - DASHBOARD_API_KEY")
        return 1
    
    print(f"API Key: {'*' * (len(secret) - 4)}{secret[-4:]}")
    
    # Parse arguments
    upload_all = False
    force_upload = False
    interactive_mode = False
    specific_date = None
    
    args = sys.argv[1:]
    
    # Default to interactive mode if no arguments
    if not args:
        interactive_mode = True
    
    for arg in args:
        if arg == "--all":
            upload_all = True
        elif arg == "--force" or arg == "-f":
            force_upload = True
        elif arg in ("--interactive", "-i"):
            interactive_mode = True
        elif arg == "--help" or arg == "-h":
            print(__doc__)
            print("\nOptions:")
            print("  (no args)  Interactive mode - select which bundles to upload")
            print("  -i         Interactive mode")
            print("  --all      Upload all new bundles (skip existing)")
            print("  --force    Force upload even if date exists on server")
            print("  YYYYMMDD   Upload specific date")
            print("  -h, --help Show this help")
            return 0
        elif len(arg) == 8 and arg.isdigit():
            specific_date = arg
        else:
            print(f"[ERROR] Unknown argument: {arg}")
            print("Usage: python upload_to_dashboard.py [YYYYMMDD | --all | -i] [--force]")
            return 1
    
    # Check dashboard status
    print("\n[INFO] Checking dashboard status...")
    if not check_dashboard_status(dashboard_url, secret):
        print("[WARN] Dashboard check failed - attempting upload anyway...")
    
    # Get existing dates on server
    print("[INFO] Checking existing dates on server...")
    existing_dates = get_existing_dates_on_server(dashboard_url, secret)
    if existing_dates:
        print(f"[INFO] Found {len(existing_dates)} dates on server: {', '.join(sorted(existing_dates, reverse=True)[:5])}{'...' if len(existing_dates) > 5 else ''}")
    else:
        print("[INFO] No existing dates found (or could not check)")
    
    # Find all bundles first
    all_bundles = find_bundles()
    
    # Interactive mode
    if interactive_mode:
        bundles = interactive_select(all_bundles, existing_dates)
        if not bundles:
            return 0
    # Find bundles to upload based on mode
    elif upload_all:
        if force_upload:
            bundles = all_bundles
            print(f"\n[INFO] Found {len(bundles)} bundles (force mode - uploading all)")
        else:
            # Filter out already existing dates
            bundles = [b for b in all_bundles if b.stem not in existing_dates]
            skipped = len(all_bundles) - len(bundles)
            print(f"\n[INFO] Found {len(all_bundles)} bundles total, {skipped} already on server, {len(bundles)} to upload")
    elif specific_date:
        bundles = find_bundles(specific_date)
        if not bundles:
            print(f"\n[ERROR] No bundle found for date: {specific_date}")
            return 1
        # Check if already exists
        if specific_date in existing_dates and not force_upload:
            print(f"\n[INFO] Date {specific_date} already exists on server")
            print("  Use --force to upload anyway")
            return 0
    else:
        # Upload only the latest bundle
        if all_bundles:
            if force_upload:
                bundles = [all_bundles[0]]
            else:
                # Filter out already existing
                new_bundles = [b for b in all_bundles if b.stem not in existing_dates]
                if new_bundles:
                    bundles = [new_bundles[0]]  # Just the newest that doesn't exist
                else:
                    print(f"\n[INFO] Latest bundle ({all_bundles[0].stem}) already on server")
                    print("  Use --force to upload anyway")
                    return 0
        else:
            bundles = []
    
    if not bundles:
        print("\n[INFO] No new bundles to upload")
        print(f"  Looking in: {DATA_BUNDLES_DIR}")
        return 0
    
    # Upload bundles
    print("\n" + "=" * 60)
    print("UPLOADING BUNDLES")
    print("=" * 60)
    
    success_count = 0
    fail_count = 0
    
    for bundle in bundles:
        print(f"\n--- {bundle.name} ---")
        success, message = upload_bundle(bundle, dashboard_url, secret)
        
        if success:
            success_count += 1
        else:
            fail_count += 1
        
        # Small delay between uploads
        if len(bundles) > 1:
            time.sleep(1)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

