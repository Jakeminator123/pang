"""Chrome process management for headless scraping."""

import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

# Chrome paths
CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
CHROME_PROFILE = Path(__file__).parent.parent / "chrome_profile"
BASE_URL = "https://poit.bolagsverket.se/poit-app/"
DEBUG_PORT = 9222

# Lock file to prevent multiple scrapers
LOCK_FILE = Path(__file__).parent.parent / ".scrape_lock"


def is_port_in_use(port: int = DEBUG_PORT) -> bool:
    """Check if the debug port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", port))
        return result == 0


def check_chrome_running() -> bool:
    """Check if Chrome is running with remote debugging on our port."""
    if not is_port_in_use(DEBUG_PORT):
        return False
    
    # Try to connect to verify it's actually Chrome
    try:
        import requests
        r = requests.get(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2)
        return "Chrome" in r.text or "Chromium" in r.text
    except Exception:
        return False


def acquire_scrape_lock() -> bool:
    """
    Acquire lock to prevent multiple scrapers running simultaneously.
    
    Returns:
        True if lock acquired, False if another scraper is running.
    """
    if LOCK_FILE.exists():
        # Check if lock is stale (older than 2 hours)
        lock_age = time.time() - LOCK_FILE.stat().st_mtime
        if lock_age > 7200:  # 2 hours
            print(f"    ⚠️ Gammal lock-fil hittades ({lock_age/3600:.1f}h) - tar bort")
            LOCK_FILE.unlink()
        else:
            # Read lock info
            try:
                lock_info = LOCK_FILE.read_text(encoding="utf-8").strip()
                print(f"    ❌ En annan scraper körs redan!")
                print(f"    Lock-info: {lock_info}")
                print(f"    Vänta tills den är klar, eller ta bort: {LOCK_FILE}")
                return False
            except Exception:
                pass
            return False
    
    # Create lock file
    try:
        from datetime import datetime
        import os
        lock_info = f"Started: {datetime.now().isoformat()}\nPID: {os.getpid()}"
        LOCK_FILE.write_text(lock_info, encoding="utf-8")
        return True
    except Exception as e:
        print(f"    ⚠️ Kunde inte skapa lock-fil: {e}")
        return True  # Continue anyway


def release_scrape_lock():
    """Release the scrape lock."""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass


def start_chrome(visible: bool = False, port: int = DEBUG_PORT) -> Optional[subprocess.Popen]:
    """
    Start Chrome with remote debugging enabled.
    
    Args:
        visible: If True, show the Chrome window. If False, position off-screen.
        port: Debug port to use (default: 9222).
    
    Returns:
        The Chrome subprocess handle, or None if Chrome is already running.
    
    Raises:
        RuntimeError: If port is in use by non-Chrome process.
    """
    # Check if port is already in use
    if is_port_in_use(port):
        if check_chrome_running():
            print(f"    ✓ Chrome körs redan på port {port} - använder befintlig instans")
            return None
        else:
            print(f"    ❌ Port {port} används av en annan process!")
            print(f"    Stäng processen som använder porten, eller ändra DEBUG_PORT.")
            raise RuntimeError(f"Port {port} is in use by non-Chrome process")
    
    # Acquire scrape lock
    if not acquire_scrape_lock():
        raise RuntimeError("Another scraper is already running")
    
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        CHROME_PATH,
        f"--user-data-dir={CHROME_PROFILE}",
        f"--remote-debugging-port={port}",
        # Disable throttling for background tabs
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    
    if not visible:
        # Off-screen position (works with 4K screens too)
        cmd.extend([
            "--window-position=4000,4000",
            "--window-size=800,600",
        ])
    
    cmd.append(BASE_URL)
    
    print(f"    Startar Chrome {'(synlig)' if visible else '(off-screen)'} på port {port}...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for Chrome to fully start
    max_wait = 15
    for i in range(max_wait):
        time.sleep(1)
        if check_chrome_running():
            print(f"    ✓ Chrome startad efter {i+1}s")
            return proc
    
    print(f"    ⚠️ Chrome startade men svarar inte på port {port}")
    return proc


def stop_chrome(proc: Optional[subprocess.Popen]):
    """
    Stop Chrome process gracefully.
    
    Args:
        proc: The Chrome subprocess handle to terminate. Can be None.
    """
    # Always release lock
    release_scrape_lock()
    
    if proc is None:
        print("    Chrome kördes redan - låter den vara.")
        return
    
    try:
        proc.terminate()
        proc.wait(timeout=5)
        print("    Chrome stängd.")
    except Exception:
        pass

