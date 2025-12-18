"""Chrome process management for headless scraping."""

import subprocess
import time
from pathlib import Path

# Chrome paths
CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
CHROME_PROFILE = Path(__file__).parent.parent / "chrome_profile"
BASE_URL = "https://poit.bolagsverket.se/poit-app/"


def start_chrome(visible: bool = False) -> subprocess.Popen:
    """
    Start Chrome with remote debugging enabled.
    
    Args:
        visible: If True, show the Chrome window. If False, position off-screen.
    
    Returns:
        The Chrome subprocess handle.
    """
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        CHROME_PATH,
        f"--user-data-dir={CHROME_PROFILE}",
        "--remote-debugging-port=9222",
    ]
    
    if not visible:
        # Off-screen position (works with 4K screens too)
        cmd.extend([
            "--window-position=4000,4000",
            "--window-size=800,600",
        ])
    
    cmd.append(BASE_URL)
    
    print(f"    Startar Chrome {'(synlig)' if visible else '(off-screen)'}...")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for Chrome to fully start
    time.sleep(6)
    
    return proc


def stop_chrome(proc: subprocess.Popen):
    """
    Stop Chrome process gracefully.
    
    Args:
        proc: The Chrome subprocess handle to terminate.
    """
    try:
        proc.terminate()
        proc.wait(timeout=5)
        print("    Chrome stängd.")
    except Exception:
        pass

