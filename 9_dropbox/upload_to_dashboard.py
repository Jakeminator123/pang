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

# Dashboard config
DEFAULT_DASHBOARD_URL = "https://jocke-dashboard.onrender.com"
UPLOAD_ENDPOINT = "/api/upload/bundle"

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
                print(f"  ✅ Success! Extracted {files_count} files in {duration:.1f}s")
                return True, result.get("message", "Upload successful")
            else:
                error = result.get("error", response_data)
                print(f"  ❌ Server returned status {response.status}: {error}")
                return False, error
                
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
            error_json = json.loads(error_body)
            error_body = error_json.get("error", error_body)
        except Exception:
            pass
        print(f"  ❌ HTTP Error {e.code}: {error_body or e.reason}")
        return False, f"HTTP {e.code}: {error_body or e.reason}"
        
    except urllib.error.URLError as e:
        print(f"  ❌ Connection error: {e.reason}")
        return False, f"Connection error: {e.reason}"
        
    except TimeoutError:
        print(f"  ❌ Upload timed out after {UPLOAD_TIMEOUT}s")
        return False, "Upload timed out"
        
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False, str(e)


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
    specific_date = None
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--all":
            upload_all = True
        elif arg == "--help" or arg == "-h":
            print(__doc__)
            return 0
        elif len(arg) == 8 and arg.isdigit():
            specific_date = arg
        else:
            print(f"[ERROR] Unknown argument: {arg}")
            print("Usage: python upload_to_dashboard.py [YYYYMMDD | --all]")
            return 1
    
    # Check dashboard status
    print("\n[INFO] Checking dashboard status...")
    if not check_dashboard_status(dashboard_url, secret):
        print("[WARN] Dashboard check failed - attempting upload anyway...")
    
    # Find bundles to upload
    if upload_all:
        bundles = find_bundles()
        print(f"\n[INFO] Found {len(bundles)} bundles to upload")
    elif specific_date:
        bundles = find_bundles(specific_date)
        if not bundles:
            print(f"\n[ERROR] No bundle found for date: {specific_date}")
            return 1
    else:
        # Upload only the latest bundle
        bundles = find_bundles()
        if bundles:
            bundles = [bundles[0]]  # Just the newest
    
    if not bundles:
        print("\n[INFO] No bundles found to upload")
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

