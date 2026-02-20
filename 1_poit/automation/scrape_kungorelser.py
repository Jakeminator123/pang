import atexit
import ctypes
import io
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

# Fixa encoding och buffering för Windows-terminal
# VIKTIGT: line_buffering=True för att se output i realtid
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# Sätt PYTHONUNBUFFERED för att säkerställa ingen buffring
os.environ["PYTHONUNBUFFERED"] = "1"

import cv2 as cv
import numpy as np
import pyautogui as pg

pg.PAUSE = 0.12
pg.FAILSAFE = True

import mss
import pygetwindow as gw

# --- DPI awareness (Windows) ---
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# ===========================
# Konfiguration
# ===========================
BASE_DIR = Path(__file__).parent.parent.resolve()  # Point to 1_poit root
PROFILE_DIR = str(BASE_DIR / "chrome_profile")
DEBUG_DIR = str(BASE_DIR / "debug")
SCREENSHOT_LOG_DIR = str(
    BASE_DIR / "debug" / "screenshots"
)  # Loggbilder (separerat från referensbilder)
Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)
Path(SCREENSHOT_LOG_DIR).mkdir(parents=True, exist_ok=True)

SCRAPE_LOCK_PATH = Path(__file__).with_suffix(".lock")

# ===========================
# Periodiska screenshots & Pause/Resume
# ===========================
# Env overrides (valfria):
# - DEBUG_IMAGE_MAX_FILES
# - DEBUG_SCREENSHOT_MAX_FILES
# - DEBUG_SCREENSHOT_INTERVAL_SEC
def _get_env_int(name: str, default: int) -> int:
    val = os.environ.get(name, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


MAX_SCREENSHOT_LOG_FILES = _get_env_int(
    "DEBUG_SCREENSHOT_MAX_FILES", 40
)  # Max antal loggbilder att behålla
SCREENSHOT_INTERVAL_SEC = _get_env_int(
    "DEBUG_SCREENSHOT_INTERVAL_SEC", 180
)  # Ta screenshot var 3:e minut
MAX_DEBUG_IMAGE_FILES = _get_env_int(
    "DEBUG_IMAGE_MAX_FILES", 40
)  # Max antal debug-bilder i debug/
_screenshot_thread = None
_screenshot_stop_event = threading.Event()
_automation_paused = threading.Event()  # Satt = pausad
_automation_paused.clear()  # Startar opausad

"""
scrape_kungorelser.py

Browser automation för att skrapa kungörelser från Bolagsverket:
- Navigerar automatiskt på poit.bolagsverket.se
- Fyller i sökformulär med datum och filter
- Öppnar kungörelser för att extensionen ska kunna fånga data
- Använder bildigenkänning (OpenCV) för att hitta UI-element
"""


# Läs config.txt för MAX_KUN_DAG
def read_config():
    # 1. Kolla miljövariabel först (satt av main.py med master-nummer)
    env_value = os.environ.get("MAX_KUN_DAG")
    if env_value:
        try:
            if env_value.upper() == "ALL":
                print("[CONFIG] MAX_KUN_DAG från miljövariabel: ALL (hämtar alla)")
                return "ALL"
            else:
                max_kun = int(env_value)
                print(f"[CONFIG] MAX_KUN_DAG från miljövariabel: {max_kun}")
                return max_kun
        except ValueError:
            print(f"[CONFIG] Ogiltigt miljövariabel-värde '{env_value}'")

    # 2. Om ingen miljövariabel, läs från config.txt
    config_path = BASE_DIR / "config.txt"
    max_kun = 10  # Default värde

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue

                    if line.startswith("MAX_KUN_DAG="):
                        value = line.split("=")[1].strip().upper()
                        if value == "ALL":
                            max_kun = "ALL"
                            print(
                                "[CONFIG] MAX_KUN_DAG från config.txt: ALL (hämtar alla)"
                            )
                        else:
                            try:
                                max_kun = int(value)
                                print(
                                    f"[CONFIG] MAX_KUN_DAG från config.txt: {max_kun}"
                                )
                            except ValueError:
                                print(
                                    f"[CONFIG] Ogiltigt värde '{value}', använder default: 10"
                                )
                                max_kun = 10

        except Exception:
            print(
                f"[CONFIG] Kunde inte läsa config.txt, använder default: MAX_KUN_DAG={max_kun}"
            )
    else:
        print(f"[CONFIG] Ingen config.txt hittad, använder default: {max_kun}")
        # Skapa exempel config.txt
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("# Konfigurationsfil för Bolagsverket Scraper\n\n")
                f.write("# Antal kungörelser att hämta per dag\n")
                f.write("# Använd MAX_KUN_DAG=ALL för att hämta alla\n")
                f.write("MAX_KUN_DAG=10\n")
            print("[CONFIG] Skapade exempel config.txt")
        except Exception:
            pass

    return max_kun


MAX_KUN_DAG = read_config()

URL_FIRST = "https://www.aftonbladet.se"
URL_SECOND = "https://poit.bolagsverket.se/poit-app/"
SERVER_HEALTH_URL = "http://127.0.0.1:51234/health"

# Bildvägar
COOKIE_DIR = BASE_DIR / "bilder" / "1_cookie"
IMG_POPUP = str((COOKIE_DIR / "popup.jpg").resolve())
IMG_OK = str((COOKIE_DIR / "ok.jpg").resolve())

SOK_DIR = BASE_DIR / "bilder" / "2_sok_kunngorelse"
IMG_LANK = str((SOK_DIR / "lank.jpg").resolve())  # Huvudlänk-bild
IMG_LANK_ALT = str((SOK_DIR / "alternativ_lank.jpg").resolve())  # Hoppa om redan på söksidan
IMG_LANK_LAPTOP = str((SOK_DIR / "laptop_sok_kungorelse.jpg").resolve())  # Laptop-specifik bild

OVRIGT_DIR = BASE_DIR / "bilder" / "4_ovrigt"
IMG_OK_FORTSATT = str((OVRIGT_DIR / "ok_fortsatt.jpg").resolve())  # Banner "ok, fortsätt" efter länk-klick

MENY_DIR = BASE_DIR / "bilder" / "3_menyer"
MENY_GLOB = "*.*"  # jpg/png/jpeg

# UI elements that can scale with DPI/zoom
# BRETT intervall för olika skärmar (1/6 storlek = ca 0.16 skala)
SCALES_UI = [round(x, 2) for x in np.arange(0.15, 2.05, 0.05)]

# ===========================
# KONTROLLERA COOKIE-HANTERING
# ===========================
# Cookie-banner kommer ibland men orsakar falska matchningar vid skala 0.15
# Inaktiveras tills vidare - popup dyker upp så sällan att det inte är värt
SKIP_COOKIE_CHECK = True   # INAKTIVERAD - orsakar falska matchningar
SKIP_OK_FORTSATT = True    # INAKTIVERAD - orsakar problem

# Trösklar - baserat på empiriska matchningar

CONF_POPUP = 0.80  # Cookie-popup (om den finns ska den vara tydlig)
CONF_OK = 0.80     # OK-knapp i cookie-popup

# LÄNK: Test visade 0.937-1.000, så 0.70 är säker marginal
CONF_LANK = 0.70   # Länk till "Sök kungörelse"
CONF_LANK_EDGE = max(0.60, CONF_LANK - 0.08)
CONF_LANK_BINARY = max(0.62, CONF_LANK - 0.05)

# ÖVRIGA
CONF_OK_FORTSATT = 0.85  # Banner efter länk-klick
CONF_MENY_GRAY = 0.60    # Meny-element
CONF_MENY_EDGE = 0.60
CONF_MENY_ORB = 0.40

# Matching modes for link
LINK_MATCH_MODES = ("gray", "edge", "binary")

# Tidsouts & beteenden
WINDOW_FIND_TIMEOUT = 8.0
POPUP_TIMEOUT_SEC = 15.0  # 15 sekunder för cookie-banner (som användaren önskade)
STEP_TIMEOUT = 15.0       # Timeout för meny-steg
POST_CLICK_WAIT = (1.2, 1.4)  # Halverat från (1.0, 2.0)
STRICT_SEQUENCE = True

# ===========================
# Väntetider (sekunder) - halverade för snabbare körning
# ===========================
WAIT_NEW_TAB = (1.0, 1.4)  # Vänta efter ny flik (halv av 0.8-1.2)
WAIT_AFTER_URL_TYPE = (0.15, 0.25)  # Efter URL-skrivning (halv av 0.3-0.5)
WAIT_PAGE_LOAD = (1.5, 1.6)  # Sidladdning (halv av 2.0-3.0)
WAIT_ENSKILD_CHECK = (1.2, 1.8)  # Enskild-hantering (halv av 2.5-3.5)
WAIT_DATA_CAPTURE = (2.0, 3.0)  # Datafångst av extension (halv av 4.0-6.0)
WAIT_CLOSE_TAB = (0.25, 0.4)  # Efter stäng flik (halv av 0.5-0.8)
WAIT_BETWEEN_KUNG = (0.75, 1.5)  # Paus mellan kungörelser (halv av 1.5-3.0)
WAIT_CHROME_START = 8  # Vänta på Chrome start (behöver tid för profil)
WAIT_AFTER_COOKIE = (2.0, 3.0)  # Efter cookie-hantering (halv av 4.0-6.0)
WAIT_AFTER_LINK = (1.9, 2.5)  # Efter länk-klick (halv av 3.5-5.0)
WAIT_SEARCH_RESULTS = (1.5, 2.5)  # Vänta på sökresultat (halv av 2.0-3.0)
WAIT_MOUSE_SHORT = 0.25  # Kort väntan vid musrörelse
WAIT_SCROLL_SHORT = 0.25  # Kort väntan vid scroll

# Multiskala
SCALES_LANK = SCALES_UI
SAMPLES_LANK = 5
LANK_TIMEOUT = 6.0

# Utökat skalintervall för bättre matchning vid olika DPI-inställningar
# Använd samma breda intervall som SCALES_UI för konsistens
SCALES_MENY = SCALES_UI

# ===========================
# Sökområden - begränsa var vi letar efter element
# ===========================
# Länk-element (lank.jpg, alternativ_lank.jpg) finns alltid i:
# X: 10% till 45% av fönsterbredden
# Y: topp 40% av fönsterhöjden
LANK_REGION_X_START = 0.10  # 10% från vänster
LANK_REGION_X_END = 0.45    # 45% från vänster
LANK_REGION_Y_START = 0.0   # Från toppen
LANK_REGION_Y_END = 0.40    # 40% från toppen

# Fallback region if primary search misses
LANK_FALLBACK_X_START = 0.05
LANK_FALLBACK_X_END = 0.60
LANK_FALLBACK_Y_START = 0.0
LANK_FALLBACK_Y_END = 0.55

# Klick-skydd
TITLEBAR_GUARD = 40
RIGHT_GUARD = 90
LEFT_GUARD = 6
BOTTOM_GUARD = 26

# Fönsterrektangel (skärm 1)
TARGET_X, TARGET_Y, TARGET_W, TARGET_H = 63, 0, 2534, 1444

# Throttle & klick-lås (robust cykel)
FRAME_GAP_SEC = 0.5  # Halverat från 1.0 - minst 0.5s mellan ALLA screenshots
IDLE_BEFORE_CLICK_SEC = (
    0.5  # Halverat från 1.0 - minst 0.5s mellan senaste foto och klick
)
LOCK_INPUT_MS = 500  # lås input under klick för att skydda mot störningar (0=av)

_last_capture_ts = 0.0


# ===========================
# Hjälp: OS/Chrome
# ===========================
def rsleep(a: float, b: float) -> None:
    time.sleep(random.uniform(a, b))


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
        except Exception:
            return False
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_scrape_lock() -> bool:
    try:
        if SCRAPE_LOCK_PATH.exists():
            data = SCRAPE_LOCK_PATH.read_text(encoding="utf-8").strip()
            if data:
                pid_str = data.split(":")[0]
                try:
                    pid = int(pid_str)
                except ValueError:
                    pid = 0
                if _pid_running(pid):
                    print(f"[LOCK] En annan scraping kör redan (PID {pid})")
                    return False
        SCRAPE_LOCK_PATH.write_text(
            f"{os.getpid()}:{datetime.now().isoformat()}",
            encoding="utf-8",
        )
        return True
    except Exception as e:
        print(f"[LOCK] Kunde inte hantera lock-fil: {e}")
        return True


def release_scrape_lock():
    try:
        if SCRAPE_LOCK_PATH.exists():
            data = SCRAPE_LOCK_PATH.read_text(encoding="utf-8").strip()
            if data.startswith(f"{os.getpid()}:"):
                SCRAPE_LOCK_PATH.unlink()
    except Exception:
        pass


def check_server_health() -> bool:
    try:
        import urllib.request

        resp = urllib.request.urlopen(SERVER_HEALTH_URL, timeout=2)
        return resp.getcode() == 200
    except Exception:
        return False


def has_existing_scrape_data() -> bool:
    date_str = os.environ.get("TARGET_DATE", datetime.now().strftime("%Y%m%d"))
    info_dir = BASE_DIR / "info_server" / date_str
    json_path = info_dir / f"kungorelser_{date_str}.json"
    return json_path.exists() and json_path.stat().st_size > 0


def find_chrome_path() -> str:
    for c in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.exists(c):
            return c
    return shutil.which("chrome") or "chrome.exe"


def kill_existing_chrome():
    """Kill any running Chrome processes to prevent new instance from delegating and exiting."""
    try:
        result = subprocess.run(
            ["taskkill", "/IM", "chrome.exe", "/F"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            print("[CHROME] Killed existing Chrome processes")
            time.sleep(2)
        else:
            print("[CHROME] No existing Chrome processes found")
    except Exception as e:
        print(f"[CHROME] Could not check/kill Chrome: {e}")

    for lock_file in ["SingletonLock", "SingletonSocket", "SingletonCookie", "Lockfile"]:
        lock_path = Path(PROFILE_DIR) / lock_file
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass


def launch_chrome_with_profile(start_url: str) -> subprocess.Popen:
    """Startar Chrome med persistent profil och extension laddad"""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    ext_path = str(BASE_DIR / "ext_bolag")

    print(f"[CHROME] Startar Chrome med profil: {PROFILE_DIR}")
    print(f"[CHROME] Extension: {ext_path}")

    return subprocess.Popen(
        [
            find_chrome_path(),
            f"--user-data-dir={PROFILE_DIR}",
            "--profile-directory=Default",
            f"--load-extension={ext_path}",
            # Förhindra att Chrome throttlar bakgrundstabbar
            "--disable-background-timer-throttling",      # Timers (setTimeout) körs normalt i bakgrund
            "--disable-backgrounding-occluded-windows",   # Rendera även dolda fönster
            "--disable-renderer-backgrounding",           # Renderer-processer throttlas inte
            "--disable-features=IntensiveWakeUpThrottling",  # Ingen intensiv throttling
            start_url,
        ],
        shell=False,
    )


def pick_best_chrome_window(timeout: float = WINDOW_FIND_TIMEOUT):
    global escape_pressed
    end = time.time() + timeout
    while time.time() < end and not escape_pressed:
        wins = [
            w
            for w in gw.getAllWindows()
            if "Chrome" in (w.title or "")
            and not w.isMinimized
            and w.width > 200
            and w.height > 200
        ]
        if wins:
            wins.sort(key=lambda x: (x.width * x.height), reverse=True)
            w = wins[0]
            # Tvinga fokus på fönstret
            force_window_focus(w)
            try:
                w.activate()
                time.sleep(0.4)
            except Exception:
                pass
            return w
        time.sleep(0.2)
    return None


def is_window_foreground(win):
    """Kontrollera om ett fönster faktiskt är i foreground"""
    try:
        if sys.platform != "win32":
            return True  # Skip check on non-Windows
        
        hwnd = win._hWnd
        user32 = ctypes.windll.user32
        foreground_hwnd = user32.GetForegroundWindow()
        return foreground_hwnd == hwnd
    except Exception:
        return False


def set_clipboard_text(text):
    """Sätt text i Windows clipboard med ctypes (inga extra dependencies)"""
    try:
        if sys.platform != "win32":
            return False
        
        # Windows API för clipboard
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        # Öppna clipboard
        if not user32.OpenClipboard(None):
            return False
        
        user32.EmptyClipboard()
        
        # Allokera minne för texten (UTF-16LE med null terminator)
        text_utf16 = text.encode('utf-16le')
        size = len(text_utf16) + 2  # +2 för null terminator
        GMEM_MOVEABLE = 0x0002
        mem_handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not mem_handle:
            user32.CloseClipboard()
            return False
        
        mem_ptr = kernel32.GlobalLock(mem_handle)
        if not mem_ptr:
            kernel32.GlobalFree(mem_handle)
            user32.CloseClipboard()
            return False
        
        # Kopiera text till minnet
        ctypes.memmove(ctypes.c_void_p(mem_ptr), text_utf16, len(text_utf16))
        # Lägg till null terminator
        null_term = ctypes.c_char_p(mem_ptr + len(text_utf16))
        ctypes.memmove(null_term, b'\x00\x00', 2)
        
        kernel32.GlobalUnlock(mem_handle)
        
        # Sätt clipboard-data
        CF_UNICODETEXT = 13
        if user32.SetClipboardData(CF_UNICODETEXT, mem_handle):
            user32.CloseClipboard()
            return True
        else:
            kernel32.GlobalFree(mem_handle)
            user32.CloseClipboard()
            return False
    except Exception as e:
        try:
            user32.CloseClipboard()
        except:
            pass
        print(f"[CLIPBOARD] Kunde inte sätta clipboard: {e}")
        return False


def get_clipboard_text():
    """Hämta text från Windows clipboard med ctypes"""
    try:
        if sys.platform != "win32":
            return None
        
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        if not user32.OpenClipboard(None):
            return None
        
        CF_UNICODETEXT = 13
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        
        if handle:
            mem_ptr = kernel32.GlobalLock(handle)
            if mem_ptr:
                text_len = kernel32.GlobalSize(handle)
                # Skapa buffer och kopiera data
                buffer = (ctypes.c_char * text_len).from_address(mem_ptr)
                text_bytes = bytes(buffer)
                kernel32.GlobalUnlock(handle)
                user32.CloseClipboard()
                
                # Konvertera från UTF-16LE till Python string
                try:
                    text = text_bytes.decode('utf-16le').rstrip('\x00')
                    return text
                except:
                    return None
            else:
                user32.CloseClipboard()
                return None
        
        user32.CloseClipboard()
        return None
    except Exception as e:
        try:
            user32.CloseClipboard()
        except:
            pass
        return None


def write_url_via_clipboard(url: str, max_attempts: int = 3) -> bool:
    """
    Skriv en URL till adressfältet via clipboard för att undvika autocomplete-artefakter som '-sok'.
    Returnerar True om texten i adressfältet matchar URL:en utan oönskade suffix, annars False.
    """
    # Spara nuvarande clipboard
    old_clipboard = get_clipboard_text()

    def paste_once() -> bool:
        if not set_clipboard_text(url):
            return False
        # Markera allt, rensa, klistra in
        safe_hotkey("ctrl", "a")
        rsleep(0.1, 0.15)
        pg.press("delete")
        rsleep(0.1, 0.15)
        safe_hotkey("ctrl", "v")
        rsleep(0.2, 0.3)
        # Stäng ev. dropdown
        pg.press("escape")
        rsleep(0.1, 0.15)
        return True

    success = paste_once()
    if not success:
        return False

    for attempt in range(max_attempts):
        # Läs tillbaka adressfältet för att verifiera att inga suffix (t.ex. "-sok") lades till
        safe_hotkey("ctrl", "a")
        rsleep(0.1, 0.15)
        safe_hotkey("ctrl", "c")
        rsleep(0.1, 0.15)
        current = get_clipboard_text() or ""
        cur_clean = current.strip().rstrip("/")
        target_clean = url.strip().rstrip("/")
        if cur_clean == target_clean and "-sok" not in cur_clean and "sok" != cur_clean.lower():
            break

        # Försök igen om det inte matchar
        paste_once()
    else:
        # Max försök, misslyckades
        if old_clipboard:
            set_clipboard_text(old_clipboard)
        return False

    # Återställ clipboard till tidigare värde
    if old_clipboard:
        set_clipboard_text(old_clipboard)
    return True


def force_window_focus(win):
    """Tvinga fokus på ett fönster med Windows API"""
    try:
        hwnd = win._hWnd
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Visa fönstret om det är minimerat
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)

        # Försök med SetForegroundWindow (kräver ibland extra steg)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)

        # Om det inte fungerade, prova med AttachThreadInput-tricket
        current_thread = kernel32.GetCurrentThreadId()
        foreground_thread = user32.GetWindowThreadProcessId(
            user32.GetForegroundWindow(), None
        )

        if current_thread != foreground_thread:
            user32.AttachThreadInput(foreground_thread, current_thread, True)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(foreground_thread, current_thread, False)

        # Klicka på fönstret för att säkerställa fokus
        user32.BringWindowToTop(hwnd)
        time.sleep(0.1)

        print("[CHROME] Fönster tvingat till fokus")
        return True
    except Exception as e:
        print(f"[CHROME] Kunde inte tvinga fokus: {e}")
        return False


def ensure_chrome_foreground(win, max_retries=3):
    """
    Säkerställ att Chrome-fönstret är i foreground innan input-operationer.
    Försöker flera gånger om nödvändigt.
    
    Returns:
        True om Chrome är i foreground, False om det misslyckades efter max_retries
    """
    if not win:
        print("[FOCUS] Ingen Chrome-fönster att fokusera")
        return False
    
    for attempt in range(max_retries):
        # Verifiera att fönstret är i foreground
        if is_window_foreground(win):
            return True
        
        # Om inte, försök tvinga fokus
        print(f"[FOCUS] Försök {attempt + 1}/{max_retries}: Tvingar Chrome till foreground...")
        
        # Försök med force_window_focus
        force_window_focus(win)
        
        # Försök även med pygetwindow's activate
        try:
            win.activate()
            time.sleep(0.2)
        except Exception:
            pass
        
        # Verifiera igen efter fokus-försök
        if is_window_foreground(win):
            print("[FOCUS] Chrome är nu i foreground")
            return True
        
        # Om det inte fungerade, vänta lite och försök igen
        if attempt < max_retries - 1:
            time.sleep(0.3)
    
    print(f"[FOCUS] VARNING: Kunde inte säkerställa att Chrome är i foreground efter {max_retries} försök")
    print("[FOCUS] Fortsätter ändå, men input kan hamna på fel fönster")
    return False


def set_window_always_on_top(win, on_top=True):
    """Sätt fönster som alltid överst"""
    try:
        hwnd = win._hWnd
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_SHOWWINDOW = 0x0040

        # Sätt fönster som topmost eller inte
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST if on_top else HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        if on_top:
            print("[CHROME] Fönster satt som 'alltid överst'")
    except Exception as e:
        print(f"[CHROME] Kunde inte sätta always-on-top: {e}")


# Global variabel för escape-kontroll
escape_pressed = False


def escape_monitor():
    """Lyssna efter escape-tangenten i en separat tråd"""
    global escape_pressed
    try:
        import keyboard

        keyboard.wait("escape")
        escape_pressed = True
        print("\n[!] ESCAPE tryckt - avbryter scraping...")
    except Exception:
        # Fallback om keyboard inte fungerar
        pass


def pause_resume_monitor():
    """Lyssna efter F9 för pause/resume i en separat tråd"""
    try:
        import keyboard

        while not escape_pressed:
            keyboard.wait("f9")
            if escape_pressed:
                break
            if _automation_paused.is_set():
                _automation_paused.clear()
                print("\n[▶] AUTOMATION ÅTERUPPTAGEN (F9)")
            else:
                _automation_paused.set()
                print("\n[⏸] AUTOMATION PAUSAD - tryck F9 för att fortsätta")
    except Exception:
        pass


def check_pause():
    """Kontrollera om automationen är pausad och vänta isf"""
    while _automation_paused.is_set() and not escape_pressed:
        time.sleep(0.5)


def cleanup_old_screenshots():
    """Ta bort gamla loggbilder om det finns fler än MAX_SCREENSHOT_LOG_FILES"""
    try:
        files = sorted(
            Path(SCREENSHOT_LOG_DIR).glob("*.png"), key=lambda p: p.stat().st_mtime
        )
        while len(files) > MAX_SCREENSHOT_LOG_FILES:
            oldest = files.pop(0)
            oldest.unlink()
            print(f"[SCREENSHOT] Raderade gammal: {oldest.name}")
    except Exception as e:
        print(f"[SCREENSHOT] Kunde inte städa: {e}")


def cleanup_old_debug_images():
    """Ta bort gamla debug-bilder om det finns fler än MAX_DEBUG_IMAGE_FILES"""
    try:
        files = sorted(
            Path(DEBUG_DIR).glob("*.png"), key=lambda p: p.stat().st_mtime
        )
        while len(files) > MAX_DEBUG_IMAGE_FILES:
            oldest = files.pop(0)
            oldest.unlink()
            print(f"[DEBUG] Raderade gammal: {oldest.name}")
    except Exception as e:
        print(f"[DEBUG] Kunde inte städa: {e}")


def screenshot_logger():
    """Bakgrundstråd som tar screenshots med jämna mellanrum"""
    cleanup_old_screenshots()  # Städa vid start

    while not _screenshot_stop_event.is_set():
        try:
            # Vänta intervallet, men kolla stop-event ofta
            for _ in range(int(SCREENSHOT_INTERVAL_SEC * 2)):
                if _screenshot_stop_event.is_set():
                    return
                time.sleep(0.5)

            # Ta screenshot om inte pausad
            if not _automation_paused.is_set() and not _screenshot_stop_event.is_set():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"log_{ts}.png"
                filepath = Path(SCREENSHOT_LOG_DIR) / filename

                with mss.mss() as sct:
                    # Ta screenshot av hela skärmen (eller primär monitor)
                    img = sct.grab(sct.monitors[1])  # Monitor 1 = primär
                    # Spara direkt med mss
                    mss.tools.to_png(img.rgb, img.size, output=str(filepath))

                # Städa om vi har för många
                files = list(Path(SCREENSHOT_LOG_DIR).glob("*.png"))
                if len(files) > MAX_SCREENSHOT_LOG_FILES:
                    cleanup_old_screenshots()

        except Exception as e:
            print(f"[SCREENSHOT] Fel: {e}")


def start_screenshot_logger():
    """Starta screenshot-loggern i en bakgrundstråd"""
    global _screenshot_thread
    _screenshot_stop_event.clear()
    cleanup_old_screenshots()  # Städa gamla bilder vid ny körning
    _screenshot_thread = threading.Thread(target=screenshot_logger, daemon=True)
    _screenshot_thread.start()
    print(
        f"[SCREENSHOT] Logger startad (var {SCREENSHOT_INTERVAL_SEC}s, max {MAX_SCREENSHOT_LOG_FILES} bilder)"
    )
    print(f"[SCREENSHOT] Sparas till: {SCREENSHOT_LOG_DIR}")


def stop_screenshot_logger():
    """Stoppa screenshot-loggern"""
    global _screenshot_thread
    _screenshot_stop_event.set()
    if _screenshot_thread and _screenshot_thread.is_alive():
        _screenshot_thread.join(timeout=2)
    print("[SCREENSHOT] Logger stoppad")


def block_mouse_input(block=True):
    """Blockera/avblockera användarens musinput (Windows)"""
    try:
        if sys.platform == "win32":
            # Windows API för att blockera/avblockera mus
            # BlockInput kräver elevated permissions, så vi använder en alternativ metod
            # Vi sätter en låg-nivå hook istället
            if block:
                # TODO: Implementera musblockering om nödvändigt
                pass
    except Exception:
        pass


def show_mouse_warning():
    """Visa varning om musinteraktion och kontroller"""
    print("\n" + "=" * 60)
    print("🛡️  SKYDDAD SCRAPING AKTIV!")
    print("=" * 60)
    print("    📌 Musen blockeras under alla klick (500ms)")
    print("    📌 Chrome-fönstret är satt som 'alltid överst'")
    print(f"    📌 Loggbilder sparas automatiskt var {SCREENSHOT_INTERVAL_SEC} sekund")
    print()
    print("    ⌨️  KONTROLLER:")
    print("    • ESC  = Avbryt scraping helt")
    print("    • F9   = Pausa / Återuppta automation")
    print()
    print(f"    📂 Loggbilder: {SCREENSHOT_LOG_DIR}")
    print(f"    📂 Referensbilder: {BASE_DIR / 'bilder'}")
    print("=" * 60 + "\n")


# Skapa en säker wrapper för pyautogui-operationer
def safe_click(x, y, **kwargs):
    """Säker klick som blockerar användarinput temporärt"""
    try:
        # Blockera användarens mus precis innan klick
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            # Använd en kort delay före block för att låta eventuell pågående rörelse avslutas
            time.sleep(0.1)
            # Blockera all input (kräver ej admin på Windows 10+)
            user32.BlockInput(True)

        # Utför klicket
        pg.click(x, y, **kwargs)

        # Vänta lite så klicket hinner registreras
        time.sleep(0.1)

    finally:
        # Avblockera alltid input även om något går fel
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.BlockInput(False)
            # Extra säkerhet - vänta lite efter avblockering
            time.sleep(0.2)


def safe_moveTo(x, y, **kwargs):
    """Säker musförflyttning som blockerar användarinput temporärt"""
    try:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            time.sleep(0.1)
            user32.BlockInput(True)

        pg.moveTo(x, y, **kwargs)
        time.sleep(0.1)

    finally:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.BlockInput(False)
            time.sleep(0.2)


def safe_hotkey(*args, **kwargs):
    """Säker hotkey som blockerar användarinput temporärt"""
    try:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            time.sleep(0.1)
            user32.BlockInput(True)

        pg.hotkey(*args, **kwargs)
        time.sleep(0.1)

    finally:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.BlockInput(False)
            time.sleep(0.2)


def safe_typewrite(text, **kwargs):
    """Säker textinmatning som blockerar användarinput temporärt"""
    try:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            time.sleep(0.1)
            user32.BlockInput(True)

        pg.typewrite(text, **kwargs)
        time.sleep(0.1)

    finally:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.BlockInput(False)
            time.sleep(0.2)


def keep_mouse_away(win_region, stop_event):
    """Övervaka musposition men blockera inte programmatiska klick"""
    # Inaktiverad för att tillåta pyautogui att klicka
    # Vi förlitar oss på always-on-top istället
    pass


def set_window_rect(win, x, y, w, h):
    try:
        win.restore()
    except Exception:
        pass
    time.sleep(0.05)
    try:
        win.moveTo(x, y)
        time.sleep(0.05)
        win.resizeTo(w, h)
        time.sleep(0.05)
    except Exception:
        try:
            hwnd = win._hWnd
            SWP_NOZORDER = 0x0004
            ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER)
        except Exception:
            pass


def refresh_region(win):
    try:
        w = gw.Window(win._hWnd)
        return (int(w.left), int(w.top), int(w.width), int(w.height))
    except Exception:
        return None


def get_link_search_region(full_region):
    """
    Beräkna sökregion för länk-element (lank.jpg, alternativ_lank.jpg).
    Länken finns alltid i:
    - X: 10% till 45% av fönsterbredden
    - Y: topp 40% av fönsterhöjden
    
    Args:
        full_region: (left, top, width, height) av hela fönstret
    
    Returns:
        (left, top, width, height) för sökregionen
    """
    if full_region is None:
        return None
    
    win_left, win_top, win_width, win_height = full_region
    
    # Beräkna sub-region
    sub_left = int(win_left + win_width * LANK_REGION_X_START)
    sub_top = int(win_top + win_height * LANK_REGION_Y_START)
    sub_width = int(win_width * (LANK_REGION_X_END - LANK_REGION_X_START))
    sub_height = int(win_height * (LANK_REGION_Y_END - LANK_REGION_Y_START))
    
    print(f"[REGION] Länk-sökområde: x={sub_left}, y={sub_top}, w={sub_width}, h={sub_height}")
    print(f"[REGION] (Fönster: x={win_left}, y={win_top}, w={win_width}, h={win_height})")
    
    return (sub_left, sub_top, sub_width, sub_height)


def get_link_fallback_region(full_region):
    """Larger search area if the primary region misses."""
    if full_region is None:
        return None
    win_left, win_top, win_width, win_height = full_region

    sub_left = int(win_left + win_width * LANK_FALLBACK_X_START)
    sub_top = int(win_top + win_height * LANK_FALLBACK_Y_START)
    sub_width = int(win_width * (LANK_FALLBACK_X_END - LANK_FALLBACK_X_START))
    sub_height = int(win_height * (LANK_FALLBACK_Y_END - LANK_FALLBACK_Y_START))

    print(
        f"[REGION] Fallback länk-sökområde: x={sub_left}, y={sub_top}, w={sub_width}, h={sub_height}"
    )
    return (sub_left, sub_top, sub_width, sub_height)


def goto_url(url: str, win=None):
    """Navigera till en URL med förbättrad adressfältshantering"""
    check_pause()  # Kolla om pausad

    # VIKTIGT: Säkerställ att Chrome är i foreground innan vi gör något
    if win:
        ensure_chrome_foreground(win)
        # Extra säkerhet: aktivera fönstret igen
        try:
            win.activate()
            time.sleep(0.2)
        except Exception:
            pass

    print(f"[URL] Navigerar till: {url[:60]}...")

    # Steg 1: Fokusera adressfältet
    print("  -> Fokuserar adressfältet...")
    pg.press("f6")
    rsleep(0.2, 0.3)
    safe_hotkey("ctrl", "l")
    rsleep(0.3, 0.5)

    # Steg 2: Skriv URL via clipboard (robust mot autocomplete)
    print("  -> Skriver URL via clipboard (för att undvika '-sok')")
    ok = write_url_via_clipboard(url)
    if not ok:
        # Fallback: skriv manuellt om clipboard misslyckas
        print("  -> Fallback: clipboard misslyckades, skriver manuellt...")
        safe_hotkey("ctrl", "a")
        rsleep(0.1, 0.15)
        pg.press("delete")
        rsleep(0.1, 0.15)
        pg.typewrite(url, interval=random.uniform(0.04, 0.08))
        rsleep(0.2, 0.3)
        pg.press("escape")
        rsleep(0.1, 0.15)

    # Ytterligare väntan innan Enter
    rsleep(0.2, 0.3)

    # Tryck Enter
    print("  -> Enter...")
    pg.press("enter")

    print("  -> Navigering startad")


# ===========================
# Skärmdump (med throttling) & OpenCV
# ===========================
def _grab_region_bgr_raw(region):
    L, T, W, H = region
    with mss.mss() as sct:
        full = sct.monitors[0]
        rel_left = max(0, L - full["left"])
        rel_top = max(0, T - full["top"])
        rel_right = min(full["width"], rel_left + W)
        rel_bottom = min(full["height"], rel_top + H)
        bbox = {
            "left": full["left"] + rel_left,
            "top": full["top"] + rel_top,
            "width": max(1, rel_right - rel_left),
            "height": max(1, rel_bottom - rel_top),
        }
        img = sct.grab(bbox)  # BGRA
        return np.array(img)[:, :, :3]  # BGR


def grab_region_bgr_any(region):
    global _last_capture_ts
    now = time.time()
    delta = now - _last_capture_ts
    if delta < FRAME_GAP_SEC:
        time.sleep(FRAME_GAP_SEC - delta)
    bgr = _grab_region_bgr_raw(region)
    _last_capture_ts = time.time()
    return bgr


def wait_since_last_capture(min_gap_sec: float):
    global _last_capture_ts
    gap = time.time() - _last_capture_ts
    if gap < min_gap_sec:
        time.sleep(min_gap_sec - gap)


def read_template_gray(path_str):
    return cv.imread(path_str, cv.IMREAD_GRAYSCALE)


def match_best(screen_gray, templ_gray, scale=1.0, normalize=True, blur_ksize=5):
    """
    Template matching robust mot DPI/antialias/kontrast.
    """
    t = templ_gray
    s = screen_gray

    if normalize:
        clahe = cv.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        s = clahe.apply(s)
        t = clahe.apply(t)

    if blur_ksize and blur_ksize >= 3:
        if blur_ksize % 2 == 0:
            blur_ksize += 1
        s = cv.GaussianBlur(s, (blur_ksize, blur_ksize), 0)
        t = cv.GaussianBlur(t, (blur_ksize, blur_ksize), 0)

    if scale != 1.0:
        h, w = t.shape[:2]
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        t = cv.resize(
            t,
            (new_w, new_h),
            interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_CUBIC,
        )

    if s.shape[0] < t.shape[0] or s.shape[1] < t.shape[1]:
        return None, None, None
    res = cv.matchTemplate(s, t, cv.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv.minMaxLoc(res)
    th, tw = t.shape[:2]
    return max_val, max_loc, (tw, th)


def ensure_saved(path, img_bgr):
    ok = cv.imwrite(path, img_bgr)
    if ok and os.path.exists(path):
        print(f"[DEBUG] Sparad: {path}")
        try:
            if Path(path).parent.resolve() == Path(DEBUG_DIR).resolve():
                cleanup_old_debug_images()
        except Exception:
            pass
    else:
        print(f"[DEBUG] Misslyckades spara: {path}")


def adaptive_binarize(gray):
    h, w = gray.shape[:2]
    block = min(31, h, w)
    if block % 2 == 0:
        block -= 1
    if block < 3:
        _, binary = cv.threshold(gray, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
        return binary
    return cv.adaptiveThreshold(
        gray, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, block, 2
    )


def get_link_mode_threshold(mode: str, base: float) -> float:
    if mode == "edge":
        return CONF_LANK_EDGE
    if mode == "binary":
        return CONF_LANK_BINARY
    return base


# ===========================
# Länk (bästa-av-flera samples)
# ===========================
def locate_best_over_samples(
    img_path, window_region, threshold, timeout_sec, scales, samples
):
    """
    Sök efter en bild i window_region och returnera den BÄSTA matchningen.
    
    VIKTIGT: Tar alltid den HÖGSTA poängen, inte första som passerar threshold.
    
    Args:
        img_path: Sökväg till template-bild
        window_region: (left, top, width, height) - SKÄRMKOORDINATER att söka i
        threshold: Minsta poäng för godkänd matchning
        timeout_sec: Max tid att söka
        scales: Lista av skalor att prova
        samples: Antal frames att ta
    
    Returns:
        (box, score, scale, mode). box är None om matchning är under threshold.
    """
    img_name = Path(img_path).name
    templ = read_template_gray(img_path)
    if templ is None:
        print(f"[MATCH] Kan inte läsa mall: {img_path}")
        return None, None, None, None

    templ_edge = cv.Canny(templ, 50, 150)
    templ_bin = adaptive_binarize(templ)
    
    templ_h, templ_w = templ.shape[:2]
    L, T, W, H = window_region
    
    print(f"")
    print(f"[MATCH] ========================================")
    print(f"[MATCH] Söker: '{img_name}'")
    print(f"[MATCH] Template: {templ_w}x{templ_h} pixlar")
    print(f"[MATCH] Sökområde: x={L}, y={T}, w={W}, h={H}")
    print(f"[MATCH] Skala: {min(scales):.2f} - {max(scales):.2f} ({len(scales)} steg)")
    print(f"[MATCH] Modes: {', '.join(LINK_MATCH_MODES)}")
    print(f"[MATCH] Threshold: {threshold:.2f}")
    print(f"[MATCH] ========================================")
    
    # SPARA debug-bild av sökområdet INNAN sökning
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    t_end = time.time() + timeout_sec
    best_score = -1.0
    best_box = None
    best_frame = None
    best_scale = None
    best_loc_in_frame = None
    best_mode = None
    frames = 0
    
    while frames < samples and time.time() < t_end:
        bgr = grab_region_bgr_any(window_region)
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
        edges = cv.Canny(gray, 50, 150)
        binary = adaptive_binarize(gray)
        
        # Spara första frame som debug
        if frames == 0:
            debug_path = str(Path(DEBUG_DIR) / f"search_area_{img_name.replace('.', '_')}_{ts}.png")
            ensure_saved(debug_path, bgr)
            print(f"[MATCH] Debug-bild sparad: {debug_path}")
        
        for sc in scales:
            for mode in LINK_MATCH_MODES:
                if mode == "gray":
                    score, loc, dims = match_best(gray, templ, scale=sc)
                elif mode == "edge":
                    score, loc, dims = match_best(
                        edges, templ_edge, scale=sc, normalize=False, blur_ksize=0
                    )
                else:
                    score, loc, dims = match_best(
                        binary, templ_bin, scale=sc, normalize=False, blur_ksize=0
                    )

                if score is None or dims is None:
                    continue
                tw, th = dims
                
                # ALLTID spara den bästa matchningen
                if score > best_score:
                    x, y = loc
                    # Box i SKÄRMKOORDINATER
                    best_score = score
                    best_box = (L + x, T + y, tw, th)
                    best_frame = bgr.copy()
                    best_scale = sc
                    best_mode = mode
                    best_loc_in_frame = (x, y, tw, th)
                
        frames += 1
        if frames < samples:
            time.sleep(max(0.0, FRAME_GAP_SEC))
    
    # Logga resultat
    print(f"[MATCH] ----------------------------------------")
    if best_scale is not None and best_mode is not None:
        print(f"[MATCH] Bästa score: {best_score:.3f} (skala={best_scale:.2f}, mode={best_mode})")
        print(f"[MATCH] Position i frame: x={best_loc_in_frame[0]}, y={best_loc_in_frame[1]}")
        print(f"[MATCH] Position på skärm: x={best_box[0]}, y={best_box[1]}")
    else:
        print(f"[MATCH] Ingen matchning hittad för '{img_name}'")
    
    # SPARA alltid debug-bild med markering av var bästa matchningen är
    if best_frame is not None and best_loc_in_frame is not None:
        x, y, tw, th = best_loc_in_frame
        out = best_frame.copy()
        mode_threshold = get_link_mode_threshold(best_mode or "gray", threshold)
        # Rita rektangel runt matchningen
        color = (0, 255, 0) if best_score >= mode_threshold else (0, 0, 255)  # Grön=OK, Röd=Under threshold
        cv.rectangle(out, (x, y), (x + tw, y + th), color, 2)
        # Skriv score på bilden
        cv.putText(out, f"score={best_score:.3f}", (x, y - 10), cv.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        debug_match_path = str(Path(DEBUG_DIR) / f"match_{img_name.replace('.', '_')}_{best_score:.3f}_{ts}.png")
        ensure_saved(debug_match_path, out)
    
    if best_mode is None:
        print(f"[MATCH] ========================================")
        return None, None, None, None

    mode_threshold = get_link_mode_threshold(best_mode, threshold)
    if best_score >= mode_threshold:
        print(
            f"[MATCH] ✓ GODKÄND (score {best_score:.3f} >= threshold {mode_threshold:.2f}, mode={best_mode})"
        )
        print(f"[MATCH] ========================================")
        return best_box, best_score, best_scale, best_mode
    
    print(
        f"[MATCH] ✗ UNDERKÄND (score {best_score:.3f} < threshold {mode_threshold:.2f}, mode={best_mode})"
    )
    print(f"[MATCH] ========================================")
    return None, best_score, best_scale, best_mode


# ===========================
# Meny-matchning (grå+edge+ev. ORB), 1s mellan frames
# ===========================
def locate_menu_robust(img_path: str, window_region, timeout_sec: float):
    img_name = Path(img_path).name
    templ = read_template_gray(img_path)
    if templ is None:
        print(f"[MENY] Kan inte läsa template: {img_path}")
        return None, None, None, None
    
    templ_h, templ_w = templ.shape[:2]
    print(f"[MENY] Söker '{img_name}' (template {templ_w}x{templ_h}px)")
    print(f"[MENY] Skalintervall: {min(SCALES_MENY):.2f} - {max(SCALES_MENY):.2f} ({len(SCALES_MENY)} steg)")
    
    t_end = time.time() + timeout_sec
    best = (-1.0, None, None, None, None)  # score, box, scale, mode, frame
    iteration = 0
    while time.time() < t_end:
        iteration += 1
        bgr = grab_region_bgr_any(window_region)  # throttlad
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)

        # Gråskala
        for sc in SCALES_MENY:
            score, loc, dims = match_best(gray, templ, scale=sc)
            if score is None or dims is None:
                continue
            tw, th = dims
            if score > best[0]:
                L, T, W, H = window_region
                x, y = loc
                best = (score, (L + x, T + y, tw, th), sc, "gray", bgr)

        # Edge
        edges_scr = cv.Canny(gray, 50, 150)
        edges_tpl = cv.Canny(templ, 50, 150)
        for sc in SCALES_MENY:
            score, loc, dims = match_best(edges_scr, edges_tpl, scale=sc, normalize=False, blur_ksize=0)
            if score is None or dims is None:
                continue
            tw, th = dims
            if score > best[0]:
                L, T, W, H = window_region
                x, y = loc
                best = (score, (L + x, T + y, tw, th), sc, "edge", bgr)

        time.sleep(max(0.0, FRAME_GAP_SEC))  # 1s fri till nästa frame
        if best[0] >= 0.97:
            print(f"[MENY] Tidig exit vid iteration {iteration} med score {best[0]:.3f}")
            break

    score, box, sc, mode, frame = best
    
    if sc is not None:
        print(f"[MENY] Bästa matchning för '{img_name}': score={score:.3f} skala={sc:.2f} mode={mode}")

    # ORB-fallback om under tröskel
    def orb_try():
        b = frame if frame is not None else grab_region_bgr_any(window_region)
        g = cv.cvtColor(b, cv.COLOR_BGR2GRAY)
        orb = cv.ORB_create(800)
        kp1, des1 = orb.detectAndCompute(templ, None)
        kp2, des2 = orb.detectAndCompute(g, None)
        if des1 is None or des2 is None or len(kp1) < 10 or len(kp2) < 10:
            return None
        bf = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=False)
        matches = bf.knnMatch(des1, des2, k=2)
        good = [m for m, n in matches if m.distance < 0.75 * n.distance]
        if len(good) < 12:
            return None
        src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv.findHomography(src, dst, cv.RANSAC, 5.0)
        if H is None:
            return None
        inliers = int(mask.sum())
        ratio = inliers / max(1, len(good))
        h, w = templ.shape[:2]
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        proj = cv.perspectiveTransform(corners, H)
        xs = proj[:, 0, 0]
        ys = proj[:, 0, 1]
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        L, T = window_region[0], window_region[1]
        return (L + x0, T + y0, x1 - x0, y1 - y0), ratio, 1.0, "orb"

    threshold = (
        CONF_MENY_GRAY
        if mode == "gray"
        else (CONF_MENY_EDGE if mode == "edge" else CONF_MENY_ORB)
    )
    if box is None or score < threshold:
        orb_res = orb_try()
        if orb_res is not None:
            return orb_res

    return box, score, sc, mode


# ===========================
# Klick (med 1s vila före & efter + kort input-lås)
# ===========================
def safe_click_center(box, win_region, win=None):
    # Säkerställ att Chrome är i foreground innan klick
    if win:
        ensure_chrome_foreground(win)
    
    # vila sedan senaste screenshot
    wait_since_last_capture(IDLE_BEFORE_CLICK_SEC)

    wL, wT, wW, wH = win_region
    L, T, W, H = box
    cx, cy = L + W // 2, T + H // 2
    
    # Logga klick-koordinater och guards
    print(f"[KLICK] Försöker klicka på ({cx}, {cy})")
    print(f"[KLICK] Fönster: x={wL}, y={wT}, w={wW}, h={wH}")
    
    if cy < (wT + TITLEBAR_GUARD):
        print(f"[KLICK] ✗ Blockerad: cy={cy} < wT+TITLEBAR_GUARD={wT + TITLEBAR_GUARD}")
        return False
    if cx > (wL + wW - RIGHT_GUARD):
        print(f"[KLICK] ✗ Blockerad: cx={cx} > wL+wW-RIGHT_GUARD={wL + wW - RIGHT_GUARD}")
        return False
    if cx < (wL + LEFT_GUARD):
        print(f"[KLICK] ✗ Blockerad: cx={cx} < wL+LEFT_GUARD={wL + LEFT_GUARD}")
        return False
    if cy > (wT + wH - BOTTOM_GUARD):
        print(f"[KLICK] ✗ Blockerad: cy={cy} > wT+wH-BOTTOM_GUARD={wT + wH - BOTTOM_GUARD}")
        return False
    
    print(f"[KLICK] ✓ Position godkänd, klickar...")

    pg.moveTo(cx, cy, duration=random.uniform(0.12, 0.24))
    time.sleep(0.06)

    locked = False
    if LOCK_INPUT_MS > 0:
        try:
            ctypes.windll.user32.BlockInput(True)
            locked = True
        except Exception:
            locked = False

    try:
        pg.mouseDown()
        time.sleep(random.uniform(0.02, 0.05))
        pg.mouseUp()
    finally:
        if locked:
            try:
                time.sleep(max(0.0, (LOCK_INPUT_MS / 1000.0) - 0.05))
                ctypes.windll.user32.BlockInput(False)
            except Exception:
                pass

    # vila efter klick så nästa foto tas först efter minst 1s
    time.sleep(FRAME_GAP_SEC)
    return True


def small_moves_balanced():
    pg.moveRel(
        random.randint(-25, 25),
        random.randint(-15, 15),
        duration=random.uniform(0.06, 0.18),
    )
    if random.random() < 0.5:
        pg.scroll(-250)
        rsleep(0.03, 0.08)
        pg.scroll(+250)
    else:
        pg.scroll(+250)
        rsleep(0.03, 0.08)
        pg.scroll(-250)


# ===========================
# Meny & datum
# ===========================
NUM_RE = re.compile(r"^(\d+)_.*\.(jpg|jpeg|png)$", re.IGNORECASE)


def list_ordered_menu_images(directory: Path):
    files = []
    for p in directory.glob(MENY_GLOB):
        m = NUM_RE.match(p.name)
        if m:
            files.append((int(m.group(1)), p))
    files.sort(key=lambda t: t[0])
    return files


def last_business_friday(d: datetime) -> datetime:
    wd = d.weekday()
    if wd == 5:
        return d - timedelta(days=1)
    if wd == 6:
        return d - timedelta(days=2)
    return d


def type_text_via_clipboard(text: str, select_all_first: bool = True):
    """
    Skriver text via clipboard för att undvika tangentbordslayout-problem.
    Svenskt tangentbord har - på annan plats, så typewrite funkar inte.
    
    Args:
        text: Texten att skriva
        select_all_first: Om True, kör Ctrl+A först för att markera och ersätta befintlig text
    """
    # Försök med vår egna set_clipboard_text() först (samma som write_url_via_clipboard använder)
    # Den är testad och fungerar bättre än den inbyggda varianten
    clipboard_success = False
    
    try:
        if set_clipboard_text(text):
            # Markera allt i fältet först (så vi ersätter istället för lägger till)
            if select_all_first:
                pg.hotkey("ctrl", "a")
                time.sleep(0.08)
            
            # Klistra in
            pg.hotkey("ctrl", "v")
            time.sleep(0.15)
            clipboard_success = True
            print(f"[DATE] Clipboard lyckades: '{text}'")
        else:
            print(f"[DATE] set_clipboard_text returnerade False")
    except Exception as e:
        print(f"[DATE] Clipboard misslyckades: {e}")
    
    if not clipboard_success:
        # Fallback: Försök med alternativ clipboard-metod via ctypes direkt
        print(f"[DATE] Primär clipboard misslyckades, försöker alternativ metod för: '{text}'")
        try:
            import ctypes
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            
            # Öppna clipboard
            if user32.OpenClipboard(0):
                try:
                    user32.EmptyClipboard()
                    data = text.encode("utf-16-le") + b"\x00\x00"
                    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if h_mem:
                        p_mem = kernel32.GlobalLock(h_mem)
                        ctypes.memmove(p_mem, data, len(data))
                        kernel32.GlobalUnlock(h_mem)
                        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                        clipboard_success = True
                finally:
                    user32.CloseClipboard()
                
                if clipboard_success:
                    if select_all_first:
                        pg.hotkey("ctrl", "a")
                        time.sleep(0.08)
                    pg.hotkey("ctrl", "v")
                    time.sleep(0.15)
                    print(f"[DATE] Alternativ clipboard lyckades: '{text}'")
        except Exception as e2:
            print(f"[DATE] Alternativ clipboard också misslyckades: {e2}")
        
        # Om fortfarande inte lyckats, använd sista utvägen: SendKeys via ctypes
        if not clipboard_success:
            print(f"[DATE] Sista utväg: SendInput för '{text}'")
            if select_all_first:
                pg.hotkey("ctrl", "a")
                time.sleep(0.08)
                pg.press("delete")
                time.sleep(0.05)
            
            # Skriv varje tecken via SendInput (fungerar med alla tangentbordslayouter)
            try:
                import ctypes
                from ctypes import wintypes
                
                user32 = ctypes.windll.user32
                
                # Definiera strukturer för SendInput
                INPUT_KEYBOARD = 1
                KEYEVENTF_UNICODE = 0x0004
                KEYEVENTF_KEYUP = 0x0002
                
                class KEYBDINPUT(ctypes.Structure):
                    _fields_ = [
                        ("wVk", wintypes.WORD),
                        ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
                    ]
                
                class INPUT(ctypes.Structure):
                    class _INPUT(ctypes.Union):
                        _fields_ = [("ki", KEYBDINPUT)]
                    _fields_ = [
                        ("type", wintypes.DWORD),
                        ("_input", _INPUT)
                    ]
                
                def send_unicode_char(char):
                    inputs = (INPUT * 2)()
                    
                    # Key down
                    inputs[0].type = INPUT_KEYBOARD
                    inputs[0]._input.ki.wVk = 0
                    inputs[0]._input.ki.wScan = ord(char)
                    inputs[0]._input.ki.dwFlags = KEYEVENTF_UNICODE
                    
                    # Key up
                    inputs[1].type = INPUT_KEYBOARD
                    inputs[1]._input.ki.wVk = 0
                    inputs[1]._input.ki.wScan = ord(char)
                    inputs[1]._input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                    
                    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(INPUT))
                
                for char in text:
                    send_unicode_char(char)
                    time.sleep(0.02)
                
                print(f"[DATE] SendInput lyckades för '{text}'")
            except Exception as e3:
                print(f"[DATE] KRITISKT: Kunde inte skriva datum! {e3}")
                print(f"[DATE] Datum som skulle skrivas: '{text}'")


def type_date_first_field(year: str, month: str, day: str):
    """
    Skriver datum i FÖRSTA fältet (Från och med).
    
    Sekvens som funkar på Bolagsverket:
    1. Skriv år (4 siffror)
    2. Höger-pil
    3. Skriv månad+dag (4 siffror i följd)
    
    Args:
        year: År (4 siffror, t.ex. "2026")
        month: Månad (2 siffror, t.ex. "01")
        day: Dag (2 siffror, t.ex. "09")
    """
    print(f"[DATE] FÖRSTA FÄLTET: {year}-{month}-{day}")
    
    # Skriv år (4 siffror) med paus mellan varje
    print(f"[DATE]   År: {year}")
    for digit in year:
        pg.press(digit)
        rsleep(0.7, 1.2)
    
    # Höger-pil för att komma till månad
    print(f"[DATE]   -> Höger-pil")
    pg.press("right")
    rsleep(0.7, 1.2)
    
    # Skriv månad+dag (4 siffror i följd, utan pil mellan)
    month_day = month + day  # "0109"
    print(f"[DATE]   Månad+Dag: {month_day}")
    for digit in month_day:
        pg.press(digit)
        rsleep(0.7, 1.2)
    
    print(f"[DATE] Första fältet klart: {year}-{month}-{day}")


def type_date_second_field(year: str, month: str, day: str):
    """
    Skriver datum i ANDRA fältet (Till och med).
    
    Sekvens som funkar på Bolagsverket:
    - Skriv år+månad+dag (8 siffror i följd, utan pil eller tab)
    
    Args:
        year: År (4 siffror, t.ex. "2026")
        month: Månad (2 siffror, t.ex. "01")
        day: Dag (2 siffror, t.ex. "09")
    """
    print(f"[DATE] ANDRA FÄLTET: {year}-{month}-{day}")
    
    # Skriv alla 8 siffror i följd
    full_date = year + month + day  # "20260109"
    print(f"[DATE]   År+Månad+Dag: {full_date}")
    for digit in full_date:
        pg.press(digit)
        rsleep(0.7, 1.2)
    
    print(f"[DATE] Andra fältet klart: {year}-{month}-{day}")


def type_date_yyyymmdd():
    """
    Skriver datum i ett HTML5 date-fält.
    Dessa fält har separata delar för År/Månad/Dag.
    """
    # Använd TARGET_DATE om den är satt, annars använd senaste arbetsdagen
    target_date_str = os.environ.get("TARGET_DATE")

    # DEBUG: Skriv ut vad som läses
    if target_date_str:
        print(f"[DATE] TARGET_DATE från miljö: {target_date_str}")
    else:
        print("[DATE] Ingen TARGET_DATE satt, använder fallback")

    if target_date_str and len(target_date_str) == 8 and target_date_str.isdigit():
        # TARGET_DATE är i formatet YYYYMMDD
        try:
            year = target_date_str[:4]
            month = target_date_str[4:6]
            day = target_date_str[6:8]
            print(f"[DATE] Skriver datum i formulär: {year}-{month}-{day} (från {target_date_str})")
            type_date_parts(year, month, day)
            return
        except (ValueError, IndexError) as e:
            print(f"[DATE] TARGET_DATE konvertering misslyckades: {e}, använder fallback")
            pass

    # Standard: använd senaste arbetsdagen
    today = datetime.now()
    biz = last_business_friday(today)
    year = biz.strftime("%Y")
    month = biz.strftime("%m")
    day = biz.strftime("%d")
    print(f"[DATE] Använder fallback (senaste arbetsdag): {year}-{month}-{day}")
    type_date_parts(year, month, day)


def take_date_debug_screenshot(label: str):
    """Ta en debug-screenshot för att se datumfälten."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"date_debug_{label}_{ts}.png"
        filepath = Path(DEBUG_DIR) / filename
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[1])
            mss.tools.to_png(img.rgb, img.size, output=str(filepath))
        print(f"[DATE-DEBUG] Screenshot sparad: {filepath}")
    except Exception as e:
        print(f"[DATE-DEBUG] Kunde inte ta screenshot: {e}")


def special_after_3_bol():
    """
    Fyller i datumfälten för "Från och med" och "Till och med".
    
    Sekvens som funkar på Bolagsverket:
    
    FÖRSTA FÄLTET:
    1. Skriv år (4 siffror)
    2. Höger-pil
    3. Skriv månad+dag (4 siffror i följd)
    
    TAB två gånger
    
    ANDRA FÄLTET:
    1. Skriv år+månad+dag (8 siffror i följd)
    
    Med 0.7-1.2 sek mellan varje knapptryck.
    """
    # Hämta datum att använda
    target_date_str = os.environ.get("TARGET_DATE")
    
    if target_date_str and len(target_date_str) == 8 and target_date_str.isdigit():
        year = target_date_str[:4]
        month = target_date_str[4:6]
        day = target_date_str[6:8]
        print(f"[DATE] Använder TARGET_DATE: {year}-{month}-{day}")
    else:
        today = datetime.now()
        biz = last_business_friday(today)
        year = biz.strftime("%Y")
        month = biz.strftime("%m")
        day = biz.strftime("%d")
        print(f"[DATE] Använder fallback (senaste arbetsdag): {year}-{month}-{day}")
    
    # Ta screenshot INNAN vi börjar
    take_date_debug_screenshot("1_before")
    
    # Klicka för att fokusera första datumfältet
    pg.click()
    rsleep(0.7, 1.2)
    pg.click()  # Extra klick för att säkerställa fokus
    rsleep(0.7, 1.2)
    
    # === FÖRSTA FÄLTET (Från och med) ===
    print("[DATE] === FYLLER I 'FRÅN OCH MED' ===")
    type_date_first_field(year, month, day)
    
    # Ta screenshot efter första fältet
    take_date_debug_screenshot("2_after_first")
    
    # TAB två gånger för att komma till andra datumfältet
    print("[DATE] Tab -> Tab för att komma till 'Till och med'...")
    pg.press("tab")
    rsleep(0.7, 1.2)
    pg.press("tab")
    rsleep(0.7, 1.2)
    
    # === ANDRA FÄLTET (Till och med) ===
    print("[DATE] === FYLLER I 'TILL OCH MED' ===")
    type_date_second_field(year, month, day)
    
    # Ta screenshot efter andra fältet
    take_date_debug_screenshot("3_after_second")
    
    print("[DATE] === DATUMFÄLT KLARA ===")


def after_step_1_down_enter():
    """Efter steg 1: 5× pil ned, sedan Enter."""
    try:
        time.sleep(0.25)
        for _ in range(5):
            pg.press("down")
            time.sleep(0.10)
        pg.press("enter")
    except Exception:
        pass


def after_step_select_one():
    """Efter steg 5/7/9: vänta 0.3s, en (1) ned, 0.3s, Enter."""
    try:
        time.sleep(0.30)
        pg.press("down")
        time.sleep(0.30)
        pg.press("enter")
        # liten extra vila så nästa screenshot garanterat tas senare
        time.sleep(0.20)
    except Exception:
        pass


# ===========================
# Orkestrering
# ===========================
def handle_cookie_then_proceed(win):
    """
    Hantera cookie-popup om den dyker upp.
    
    VIKTIGT: Cookie-popup ska bara matchas om den faktiskt finns.
    Vi söker endast i den centrala delen av skärmen där popup dyker upp.
    """
    # KONTROLLERA OM VI SKA HOPPA ÖVER COOKIE-CHECK
    if SKIP_COOKIE_CHECK:
        print("[COOKIE] ⏭️ HOPPAS ÖVER (SKIP_COOKIE_CHECK=True)")
        return
    
    # Säkerställ att Chrome är i foreground innan vi klickar
    ensure_chrome_foreground(win)
    
    full_region = refresh_region(win)
    if not full_region:
        return
    
    # Cookie-popup dyker upp i MITTEN av skärmen
    # Sök bara i den centrala regionen (20-80% X, 20-80% Y)
    win_left, win_top, win_width, win_height = full_region
    popup_region = (
        int(win_left + win_width * 0.20),
        int(win_top + win_height * 0.20),
        int(win_width * 0.60),
        int(win_height * 0.60),
    )
    
    print(f"[COOKIE] Letar efter popup.jpg i centrum (threshold={CONF_POPUP:.2f}, timeout={POPUP_TIMEOUT_SEC}s)")
    print(f"[COOKIE] Sökområde: x={popup_region[0]}, y={popup_region[1]}, w={popup_region[2]}, h={popup_region[3]}")
    
    templ = read_template_gray(IMG_POPUP)
    if templ is None:
        print("[COOKIE] Kunde inte läsa popup.jpg - hoppar över cookie-hantering")
        return
    
    templ_h, templ_w = templ.shape[:2]
    print(f"[COOKIE] Template: {templ_w}x{templ_h}px")
    
    end = time.time() + POPUP_TIMEOUT_SEC
    found = False
    best_score = 0.0
    best_scale = None
    best_loc = None
    
    while time.time() < end and not found:
        bgr = grab_region_bgr_any(popup_region)
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
        for sc in SCALES_UI:
            score, loc, dims = match_best(gray, templ, scale=sc)
            if score is None or dims is None:
                continue
            if score > best_score:
                best_score = score
                best_scale = sc
                best_loc = loc
            if score >= CONF_POPUP:
                found = True
                print(f"[COOKIE] ✓ Popup hittad! score={score:.3f} skala={sc:.2f}")
                break
        if not found:
            time.sleep(FRAME_GAP_SEC)
    
    if not found:
        print(f"[COOKIE] Ingen popup hittad inom {POPUP_TIMEOUT_SEC}s (bästa score={best_score:.3f})")
        print("[COOKIE] Fortsätter utan cookie-hantering")
        return
    
    rsleep(0.5, 1.0)
    
    # Hitta och klicka på OK-knappen (i samma popup-region)
    print(f"[COOKIE] Letar efter ok.jpg (threshold={CONF_OK:.2f})")
    templ_ok = read_template_gray(IMG_OK)
    if templ_ok is None:
        print("[COOKIE] Kunde inte läsa ok.jpg - kan inte klicka")
        return
    
    bgr = grab_region_bgr_any(popup_region)
    gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    
    best_ok_score = 0.0
    best_ok_scale = None
    
    for sc in SCALES_UI:
        score, loc, dims = match_best(gray, templ_ok, scale=sc)
        if score is None or dims is None:
            continue
        if score > best_ok_score:
            best_ok_score = score
            best_ok_scale = sc
        if score >= CONF_OK:
            tw, th = dims
            x, y = loc
            # Koordinaterna är relativa till popup_region, inte full_region
            box = (popup_region[0] + x, popup_region[1] + y, tw, th)
            click_x = box[0] + tw // 2
            click_y = box[1] + th // 2
            print(f"[COOKIE] ✓ OK-knapp hittad! score={score:.3f} skala={sc:.2f}")
            print(f"[COOKIE] Klickar på ({click_x}, {click_y})")
            if safe_click_center(box, full_region, win=win):
                print("[COOKIE] ✓ OK klickad!")
            return
    
    print(f"[COOKIE] OK-knapp ej hittad (bästa score={best_ok_score:.3f} vid skala={best_ok_scale})")


def handle_ok_fortsatt_banner(win):
    """Hantera 'ok, fortsätt' banner som kan dyka upp efter länk-klick"""
    # KONTROLLERA OM VI SKA HOPPA ÖVER
    if SKIP_OK_FORTSATT:
        print("[BANNER] ⏭️ HOPPAS ÖVER (SKIP_OK_FORTSATT=True)")
        return False
    
    # Säkerställ att Chrome är i foreground
    ensure_chrome_foreground(win)
    
    region = refresh_region(win)
    if not region:
        return False
    
    # Kontrollera om bildfilen finns
    if not os.path.exists(IMG_OK_FORTSATT):
        # Om bildfilen saknas, försök använda samma OK-bild som cookie-popup
        img_path = IMG_OK
        if not os.path.exists(img_path):
            print("[BANNER] Ingen bildfil för 'ok, fortsätt' hittades")
            return False
        print("[BANNER] Använder ok.jpg som fallback för 'ok, fortsätt'")
    else:
        img_path = IMG_OK_FORTSATT
    
    print(f"[BANNER] Letar efter {Path(img_path).name} (threshold={CONF_OK_FORTSATT:.2f})")
    
    templ = read_template_gray(img_path)
    if templ is None:
        print(f"[BANNER] Kunde inte läsa {img_path}")
        return False
    
    templ_h, templ_w = templ.shape[:2]
    print(f"[BANNER] Template: {templ_w}x{templ_h}px, skalor: {min(SCALES_UI):.2f}-{max(SCALES_UI):.2f}")
    
    # Leta efter banner med kort timeout (banner dyker upp snabbt)
    timeout = 5.0  # Ökat från 3.0
    end = time.time() + timeout
    best_score = 0.0
    best_scale = None
    
    while time.time() < end:
        bgr = grab_region_bgr_any(region)
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
        for sc in SCALES_UI:
            score, loc, dims = match_best(gray, templ, scale=sc)
            if score is None or dims is None:
                continue
            if score > best_score:
                best_score = score
                best_scale = sc
            if score >= CONF_OK_FORTSATT:
                tw, th = dims
                x, y = loc
                box = (region[0] + x, region[1] + y, tw, th)
                print(f"[BANNER] ✓ Banner hittad! score={score:.3f} skala={sc:.2f}")
                if safe_click_center(box, region, win=win):
                    print("[BANNER] ✓ 'Ok, fortsätt' banner klickad!")
                    rsleep(0.5, 1.0)
                    return True
        time.sleep(0.3)
    
    print(f"[BANNER] Ingen banner hittad (bästa score={best_score:.3f} vid skala={best_scale})")
    return False


def locate_menu_and_click(img_path: str, win, timeout: float):
    """Hitta menyelem och klicka på det."""
    # Säkerställ att Chrome är i foreground innan vi letar/klickar
    ensure_chrome_foreground(win)
    
    region = refresh_region(win)
    img_name = Path(img_path).name
    
    box, score, sc, mode = locate_menu_robust(img_path, region, timeout_sec=timeout)
    
    if box is None:
        print(f"[MENY-KLICK] ✗ '{img_name}' - ingen matchning hittad")
        bgr = grab_region_bgr_any(region)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ensure_saved(
            str(Path(DEBUG_DIR) / f"{img_name.replace('.', '_')}_window_{ts}.png"), bgr
        )
        return False, None
    
    th = (
        CONF_MENY_GRAY
        if mode == "gray"
        else (CONF_MENY_EDGE if mode == "edge" else CONF_MENY_ORB)
    )
    
    if score < th:
        print(f"[MENY-KLICK] ✗ '{img_name}' - score={score:.3f} < threshold={th:.2f} (skala={sc:.2f}, mode={mode})")
        bgr = grab_region_bgr_any(region)
        L, T, W, H = box
        x = L - region[0]
        y = T - region[1]
        out = bgr.copy()
        cv.rectangle(out, (x, y), (x + W, y + H), (0, 0, 255), 2)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ensure_saved(
            str(
                Path(DEBUG_DIR)
                / f"{img_name.replace('.', '_')}_below_{score:.3f}_scale{sc:.2f}_{ts}.png"
            ),
            out,
        )
        return False, None
    
    print(f"[MENY-KLICK] ✓ '{img_name}' - score={score:.3f} >= threshold={th:.2f} (skala={sc:.2f}, mode={mode})")
    ok = safe_click_center(box, region, win=win)
    if ok:
        print(f"[MENY-KLICK] ✓ Klickade på '{img_name}'")
    else:
        print(f"[MENY-KLICK] ✗ Klick blockerat för '{img_name}'")
    return ok, box


def run_menu_sequence(win):
    steps = list_ordered_menu_images(MENY_DIR)
    if not steps:
        print(f"[VARNING] Inga meny-bilder i {MENY_DIR}")
        return
    print("[*] Meny-steg:", ", ".join(f"{n}:{p.name}" for n, p in steps))

    for num, path in steps:
        ok, box = locate_menu_and_click(str(path.resolve()), win, timeout=STEP_TIMEOUT)
        if not ok:
            print("[!] Avbryter (STRICT_SEQUENCE=True).") if STRICT_SEQUENCE else print(
                "[!] Fortsätter."
            )
            if STRICT_SEQUENCE:
                return
            else:
                continue

        # Efter steg 1 → 5× ned + Enter
        if num == 1:
            after_step_1_down_enter()

        # Efter steg 5, 7, 9 → 1× ned + Enter (standard)
        if num in (5, 7, 9):
            after_step_select_one()
            time.sleep(0.25)  # Halverat från 0.5

            # NYTT: extra sekvens för steg 5
            if num == 5:
                time.sleep(random.uniform(0.0, 2.5))  # Halverat från 0-5s
                pg.press("down")
                time.sleep(0.5)  # Halverat från 1.0
                pg.press("down")
                time.sleep(0.25)  # Halverat från 0.5
                pg.press("enter")

        # Särfall 3_bol (datum)
        if num == 3 and "bol" in path.stem.lower():
            special_after_3_bol()

        # lite mänskliga rörelser + paus
        small_moves_balanced()
        rsleep(*POST_CLICK_WAIT)


def open_missing_kungorelser(win, max_count=None):
    """
    Öppna saknade kungörelser i nya flikar i samma Chrome-session
    Hanterar både direkta kungörelse-sidor och "enskild" mellansidor
    """
    if max_count is None:
        max_count = MAX_KUN_DAG  # Använd värde från config.txt

    print("\n" + "=" * 60)
    print("ÖPPNAR SAKNADE KUNGÖRELSER")
    if max_count == "ALL":
        print("Max antal att hämta: ALLA")
    else:
        print(f"Max antal att hämta: {max_count}")
    print("=" * 60)

    # Hitta senaste JSON-fil
    info_server_dir = BASE_DIR / "info_server"
    json_files = []

    # Först kolla i TARGET_DATE eller dagens datummapp (föredra den)
    date_str = os.environ.get("TARGET_DATE", datetime.now().strftime("%Y%m%d"))
    print(
        f"[SCRAPE] open_missing_kungorelser: Använder datum: {date_str} (TARGET_DATE={'satt' if os.environ.get('TARGET_DATE') else 'ej satt'})"
    )
    date_folder = info_server_dir / date_str
    if date_folder.exists():
        json_files.extend(date_folder.glob("kungorelser_*.json"))
        print(f"[SCRAPE] Hittade JSON-filer i datummapp: {date_folder}")

    # Kolla även i alla andra datummappar
    for date_dir in info_server_dir.iterdir():
        if date_dir.is_dir() and re.fullmatch(r"\d{8}", date_dir.name):
            json_files.extend(date_dir.glob("kungorelser_*.json"))

    # Kolla även i root (bakåtkompatibilitet)
    json_files.extend(info_server_dir.glob("kungorelser_*.json"))

    if not json_files:
        print("[INFO] Ingen kungorelser JSON hittades")
        return

    # Sortera efter datum (föredra dagens datum, annars senaste)
    def get_date_from_file(f):
        try:
            date_part = f.stem.split("_")[1] if "_" in f.stem else ""
            return date_part
        except (IndexError, ValueError):
            return ""

    # Föredra dagens datum
    today_files = [f for f in json_files if get_date_from_file(f) == date_str]
    if today_files:
        json_file = today_files[0]
    else:
        # Annars använd senaste filen baserat på datum
        json_files.sort(key=lambda x: get_date_from_file(x), reverse=True)
        json_file = json_files[0]

    print(f"[INFO] Använder: {json_file.parent.name}/{json_file.name}")

    # Ladda kungörelser
    try:
        import json

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_kungorelser = []
        if "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                if isinstance(item, dict) and "kungorelseid" in item:
                    all_kungorelser.append(item["kungorelseid"])
    except Exception as e:
        print(f"[ERROR] Kunde inte läsa JSON: {e}")
        return

    print(f"[INFO] Totalt {len(all_kungorelser)} kungörelser i JSON")

    # Kolla vilka som redan finns i TARGET_DATE eller dagens datummapp
    existing = set()
    date_str = os.environ.get("TARGET_DATE", datetime.now().strftime("%Y%m%d"))
    print(f"[SCRAPE] Kontrollerar befintliga kungörelser i mapp: {date_str}")
    date_folder = info_server_dir / date_str

    # Kolla även i root-mappen för bakåtkompatibilitet
    for folder in info_server_dir.iterdir():
        if folder.is_dir() and folder.name.startswith("K") and "-" in folder.name:
            existing.add(folder.name.replace("-", "/"))

    # Kolla i datummappen om den finns
    if date_folder.exists():
        for folder in date_folder.iterdir():
            if folder.is_dir() and folder.name.startswith("K") and "-" in folder.name:
                existing.add(folder.name.replace("-", "/"))

    existing_count = len(existing)
    print(f"[INFO] {existing_count} redan nedladdade")

    # Hitta saknade
    missing = [k for k in all_kungorelser if k not in existing]
    print(f"[INFO] {len(missing)} saknas")

    if not missing:
        print("✅ Alla kungörelser redan nedladdade!")
        return

    # Aktivera Chrome-fönstret och säkerställ fokus
    ensure_chrome_foreground(win)
    try:
        win.activate()
        time.sleep(0.5)
    except:
        pass

    json_total = len(all_kungorelser)
    remaining_from_json = max(0, json_total - existing_count)

    if max_count == "ALL":
        allowed = remaining_from_json
    else:
        allowed_from_config = max(0, max_count - existing_count)
        allowed = min(remaining_from_json, allowed_from_config)
        if remaining_from_json > allowed:
            print(
                f"[INFO] Begränsar antal att öppna till {allowed} pga MAX_KUN_DAG={max_count}"
            )

    if allowed <= 0:
        print("[INFO] Inget utrymme kvar att hämta baserat på config/json-antal.")
        return

    count = min(len(missing), allowed)
    print(
        f"\n[ACTION] Öppnar {count} kungörelser (cap: {allowed}, json_total: {json_total}, existing: {existing_count})..."
    )

    for i, kung_id in enumerate(missing[:count], 1):
        print(f"\n[{i}/{count}] Kungörelse: {kung_id}")

        # Säkerställ att Chrome är i foreground innan varje operation
        ensure_chrome_foreground(win)

        # Öppna ny flik med lite mänskliga rörelser först
        pg.moveRel(random.randint(-20, 20), random.randint(-10, 10), duration=0.15)
        pg.hotkey("ctrl", "t")
        time.sleep(random.uniform(*WAIT_NEW_TAB))

        # Säkerställ fokus igen innan URL-skrivning (fliken kan ha förlorat fokus)
        ensure_chrome_foreground(win)
        
        # Skriv URL (konvertera / till -)
        url_id = kung_id.replace("/", "-")
        url = f"https://poit.bolagsverket.se/poit-app/kungorelse/{url_id}"

        # Fokusera adressfältet
        safe_hotkey("ctrl", "l")
        rsleep(0.2, 0.3)
        
        # Använd samma robusta clipboard-metod som goto_url
        if not write_url_via_clipboard(url):
            # Fallback till typewrite
            pg.typewrite(url, interval=random.uniform(0.01, 0.03))
            rsleep(0.2, 0.3)
            pg.press("escape")
            rsleep(0.1, 0.15)
        
        time.sleep(random.uniform(*WAIT_AFTER_URL_TYPE))
        pg.press("enter")

        # Initial väntan för sidladdning
        print("  Väntar på laddning...")
        time.sleep(random.uniform(*WAIT_PAGE_LOAD))

        # Lite musrörelser medan vi väntar
        pg.moveRel(random.randint(-100, 100), random.randint(-50, 50), duration=0.2)
        time.sleep(WAIT_MOUSE_SHORT)

        # Scrolla lite för att verka mänsklig
        scroll_amount = random.randint(-200, 300)
        pg.scroll(scroll_amount)
        time.sleep(WAIT_SCROLL_SHORT)

        # Om vi hamnat på en "enskild" mellansida, vänta längre
        # Extensionen (content.js) har kod för att hantera detta automatiskt
        # Vi ger den tid att klicka sig vidare
        print("  Kontrollerar för mellansidor (enskild)...")
        time.sleep(random.uniform(*WAIT_ENSKILD_CHECK))

        # Mer musrörelser och scroll
        pg.moveRel(random.randint(-80, 80), random.randint(-40, 40), duration=0.2)
        time.sleep(WAIT_MOUSE_SHORT)
        pg.scroll(random.randint(100, 200))
        time.sleep(WAIT_SCROLL_SHORT)
        pg.scroll(random.randint(-150, -50))  # Scrolla tillbaka lite

        # Vänta så extensionen kan fånga data från slutsidan
        wait_time = random.uniform(*WAIT_DATA_CAPTURE)
        print(f"  Väntar {wait_time:.1f}s för datafångst...")
        time.sleep(wait_time)

        # Sista musrörelse innan vi stänger
        pg.moveRel(random.randint(-30, 30), random.randint(-20, 20), duration=0.15)
        time.sleep(WAIT_MOUSE_SHORT)

        # Stäng fliken
        pg.hotkey("ctrl", "w")
        time.sleep(random.uniform(*WAIT_CLOSE_TAB))

        print("  ✓ Klar")

        # Paus mellan kungörelser
        if i < count:
            pause = random.uniform(*WAIT_BETWEEN_KUNG)
            print(f"  Paus {pause:.1f}s innan nästa...")
            time.sleep(pause)
            # Extra musrörelse under pausen
            pg.moveRel(random.randint(-50, 50), random.randint(-30, 30), duration=0.2)

    print(f"\n✅ Öppnade {count} kungörelser")
    print(f"💡 {len(missing) - count} kungörelser återstår")


def main():
    print("=" * 60)
    print("BOLAGSVERKET SCRAPER")
    print(f"Max kungörelser: {MAX_KUN_DAG}")
    print("=" * 60)
    print(
        f"[THRESHOLDS] POPUP={CONF_POPUP} OK={CONF_OK} LANK={CONF_LANK} MENY_GRAY={CONF_MENY_GRAY} MENY_EDGE={CONF_MENY_EDGE} MENY_ORB={CONF_MENY_ORB}"
    )

    if not acquire_scrape_lock():
        return 1

    if not check_server_health():
        print("[FEL] Servern svarar inte på /health.")
        print("[FEL] Starta servern via main.py innan scraping.")
        release_scrape_lock()
        return 1

    if has_existing_scrape_data():
        print("[INFO] Dagens scraping-data finns redan - hoppar över scraping.")
        release_scrape_lock()
        return 0

    # Starta screenshot-logger för debugging
    start_screenshot_logger()

    kill_existing_chrome()

    proc = None
    proc = launch_chrome_with_profile(URL_FIRST)

    # Vänta kort så Chrome hinner starta
    print("[*] Väntar på att Chrome startar...")
    time.sleep(WAIT_CHROME_START)

    # Setup cleanup handlers för att stänga Chrome om programmet avbryts
    def cleanup_all():
        try:
            stop_screenshot_logger()
        except:
            pass
        try:
            if proc and proc.poll() is None:
                print("\n[CLEANUP] Stänger Chrome...")
                proc.terminate()
                time.sleep(1)
                if proc.poll() is None:
                    proc.kill()
        except:
            pass

    # Registrera cleanup för olika avbrott
    atexit.register(cleanup_all)
    signal.signal(signal.SIGINT, lambda s, f: (cleanup_all(), exit(0)))  # Ctrl+C
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup_all(), exit(0)))  # Terminate

    success = False
    try:
        # Kontrollera att Chrome-processen fortfarande körs
        if proc.poll() is not None:
            print("[KRITISKT FEL] Chrome-processen avslutades innan scraping började!")
            return 1

        time.sleep(1.0)  # Halverad väntetid
        win = pick_best_chrome_window()
        if not win:
            print("[FEL] Hittade inget Chrome-fönster.")
            # Kontrollera om Chrome-processen fortfarande körs
            if proc.poll() is not None:
                print("[KRITISKT FEL] Chrome-processen avslutades!")
            return 1

        # Starta escape-övervakning i en separat tråd
        escape_thread = threading.Thread(target=escape_monitor, daemon=True)
        escape_thread.start()

        # Starta pause/resume-övervakning (F9)
        pause_thread = threading.Thread(target=pause_resume_monitor, daemon=True)
        pause_thread.start()

        # Sätt Chrome-fönstret som alltid överst
        set_window_always_on_top(win, True)

        # Extra fokusering för att säkerställa att Chrome är aktivt
        force_window_focus(win)
        time.sleep(0.3)

        # Visa varning om musinteraktion och kontroller
        show_mouse_warning()

        # Vi använder smart blockering vid varje input-operation
        win_region = refresh_region(win)
        mouse_stop_event = threading.Event()  # Behålls för kompatibilitet

        # Kontinuerlig kontroll att Chrome-processen körs, escape och pause
        def check_chrome_alive():
            global escape_pressed
            # Kolla pause först (väntar om pausad)
            check_pause()
            if escape_pressed:
                print("\n[!] Avbruten av användaren (ESC)")
                return False
            if proc.poll() is not None:
                print("\n[KRITISKT FEL] Chrome-processen avslutades under scraping!")
                return False
            return True

        set_window_rect(win, TARGET_X, TARGET_Y, TARGET_W, TARGET_H)
        time.sleep(0.15)
        region = refresh_region(win)
        print(f"→ Fönster: {region}")

        if not check_chrome_alive():
            return 1

        try:
            win.activate()
            time.sleep(0.15)
        except Exception:
            pass
        pg.hotkey("ctrl", "0")
        time.sleep(0.1)

        # Säkerställ att Chrome är i foreground innan navigation
        ensure_chrome_foreground(win)
        goto_url(URL_SECOND, win=win)
        handle_cookie_then_proceed(win)
        rsleep(*WAIT_AFTER_COOKIE)

        if not check_chrome_alive():
            return 1

        # Hämta fönsterregion
        full_region = refresh_region(win)
        if full_region:
            print(
                f"[LINK] Fönsterregion: x={full_region[0]}, y={full_region[1]}, w={full_region[2]}, h={full_region[3]}"
            )
        
        # Begränsa sökning till rätt område (X: 10-45%, Y: topp 40%)
        link_region = get_link_search_region(full_region)
        if link_region is None:
            print("[FEL] Kunde inte beräkna länk-sökområde")
            return 1
        print(
            f"[LINK] Länk-sökområde: x={link_region[0]}, y={link_region[1]}, w={link_region[2]}, h={link_region[3]}"
        )
        fallback_region = get_link_fallback_region(full_region)
        
        # ===========================================
        # SÖK EFTER LÄNK - PRIORITERA laptop_sok_kungorelse.jpg
        # ===========================================
        # Testar i ordning och tar BÄSTA totala matchning
        link_images = [
            (IMG_LANK_LAPTOP, "laptop_sok_kungorelse.jpg"),  # Laptop-specifik FÖRST (score 1.0 i test)
            (IMG_LANK, "lank.jpg"),                          # Original (score 0.937 i test)
        ]
        
        def search_link_in_region(region, label):
            if region is None:
                return None, 0.0, None, None, None

            best = None
            best_score = 0.0
            best_scale = None
            best_mode = None
            matched_image = None

            for img_path, img_name in link_images:
                if not os.path.exists(img_path):
                    print(f"[*] Hoppar över '{img_name}' (fil saknas)")
                    continue

                print(f"[*] Letar efter '{img_name}' i {label} område...")
                candidate, score, scale, mode = locate_best_over_samples(
                    img_path,
                    region,
                    threshold=CONF_LANK,
                    timeout_sec=LANK_TIMEOUT,
                    scales=SCALES_LANK,
                    samples=SAMPLES_LANK,
                )

                if candidate and isinstance(score, (int, float)) and score > best_score:
                    best = candidate
                    best_score = score
                    best_scale = scale
                    best_mode = mode
                    matched_image = img_name
                    print(
                        f"[+] Ny bästa matchning ({label}): '{img_name}' score={score:.3f} mode={mode}"
                    )

                # Early exit ENDAST om vi har score >= 0.95 (nästan perfekt match)
                if best and best_score >= 0.95:
                    print(f"[+] Perfekt matchning ({best_score:.3f}) - avslutar sökning")
                    break

            return best, best_score, best_scale, best_mode, matched_image

        best, best_score, best_scale, best_mode, matched_image = search_link_in_region(
            link_region, "primärt"
        )

        if not best and fallback_region:
            print("[LINK] Ingen match i primärt område - provar fallback...")
            best, best_score, best_scale, best_mode, matched_image = search_link_in_region(
                fallback_region, "fallback"
            )

        if not best:
            print("[FEL] Hittade ingen länk-bild över tröskeln. Se debug i 'debug\\'.")
            print("[FEL] Provade bilderna: " + ", ".join(name for _, name in link_images))
            if not check_chrome_alive():
                return 1
            return 1
        
        # Logga klick-position
        click_x = best[0] + best[2] // 2
        click_y = best[1] + best[3] // 2
        print(f"[+] KLICK PÅ LÄNK:")
        print(f"[+]   Bild: '{matched_image}'")
        print(f"[+]   Score: {best_score:.3f}")
        if best_mode:
            print(f"[+]   Mode: {best_mode}")
        if best_scale is not None:
            print(f"[+]   Skala: {best_scale:.2f}")
        print(f"[+]   Position: ({click_x}, {click_y})")
        print(f"[+]   Box: x={best[0]}, y={best[1]}, w={best[2]}, h={best[3]}")
        
        # Använd full_region för klick-validering (guards är relativa till hela fönstret)
        if not safe_click_center(best, full_region, win=win):
            print("[VARN] Klick blockerat (kant/header) – avbryter.")
            if not check_chrome_alive():
                return 1
            return 1

        if not check_chrome_alive():
            return 1

        rsleep(*WAIT_AFTER_LINK)
        
        # Hantera eventuell "ok, fortsätt" banner efter länk-klick
        if not check_chrome_alive():
            return 1
        handle_ok_fortsatt_banner(win)
            
        run_menu_sequence(win)
        print("[✓] Sökformulär klar.")

        if not check_chrome_alive():
            return 1

        # Efter att sökningen är klar, öppna saknade kungörelser
        rsleep(*WAIT_SEARCH_RESULTS)  # Vänta lite så sökresultaten laddas
        open_missing_kungorelser(win)  # Använder MAX_KUN_DAG från config.txt

        if not check_chrome_alive():
            return 1

        success = True
        print("\n[✓] ALLT KLART!")

    except KeyboardInterrupt:
        print("\n[AVBRUTEN] Användaren avbröt scraping.")
        return 1
    except Exception as e:
        print(f"\n[KRITISKT FEL] Oväntat fel under scraping: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        # Release scraping lock
        release_scrape_lock()
        # Rensa upp varningar
        try:
            if "mouse_stop_event" in locals():
                mouse_stop_event.set()  # För kompatibilitet
        except:
            pass

        # Ta bort always-on-top om Chrome fortfarande körs
        try:
            if "win" in locals() and win:
                set_window_always_on_top(win, False)
        except:
            pass

        # Stäng Chrome när vi är klara
        print("\n[*] Stänger Chrome...")
        try:
            if proc.poll() is None:  # Om processen fortfarande kör
                proc.terminate()  # Försök stänga snällt
                time.sleep(1.5)
                if proc.poll() is None:  # Om den fortfarande kör
                    print("[*] Tvingar stängning...")
                    proc.kill()  # Tvinga stängning
                print("[✓] Chrome stängd")
            else:
                print("[VARNING] Chrome-processen var redan avslutad")
        except Exception as e:
            print(f"[VARNING] Kunde inte stänga Chrome helt: {e}")

    # Returnera exit-kod: 0 = success, 1 = fel
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code if exit_code is not None else 0)
