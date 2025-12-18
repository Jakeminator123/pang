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

# Fixa encoding för Windows-terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import cv2 as cv
import numpy as np
import pyautogui as pg

pg.PAUSE = 0.12
pg.FAILSAFE = True

import mss
import pygetwindow as gw

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

# ===========================
# Periodiska screenshots & Pause/Resume
# ===========================
MAX_SCREENSHOT_LOG_FILES = 200  # Max antal loggbilder att behålla
SCREENSHOT_INTERVAL_SEC = 20  # Ta screenshot var 20:e sekund
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

# Bildvägar
COOKIE_DIR = BASE_DIR / "bilder" / "1_cookie"
IMG_POPUP = str((COOKIE_DIR / "popup.jpg").resolve())
IMG_OK = str((COOKIE_DIR / "ok.jpg").resolve())

SOK_DIR = BASE_DIR / "bilder" / "2_sok_kunngorelse"
IMG_LANK = str((SOK_DIR / "lank.jpg").resolve())  # kräver ≥ 0.88
IMG_LANK_ALT = str((SOK_DIR / "alternativ_lank.jpg").resolve())  # hoppa klick om redan på söksidan

MENY_DIR = BASE_DIR / "bilder" / "3_menyer"
MENY_GLOB = "*.*"  # jpg/png/jpeg

# Trösklar
# Sänkta trösklar för bättre matchning vid olika skärminställningar
CONF_POPUP = 0.78
CONF_OK = 0.80
CONF_LANK = 0.82
CONF_MENY_GRAY = 0.72  # Sänkt från 0.86 - hanterar DPI-skalning/ljusskillnader bättre
CONF_MENY_EDGE = 0.75  # Sänkt från 0.82
CONF_MENY_ORB = 0.50  # inlier-ratio, sänkt för mer flexibilitet

# Tidsouts & beteenden
WINDOW_FIND_TIMEOUT = 8.0
POPUP_TIMEOUT_SEC = 12.0  # <= 12s
STEP_TIMEOUT = 12.0
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
SCALES_LANK = [0.95, 1.00, 1.05]
SAMPLES_LANK = 5
LANK_TIMEOUT = 6.0

# Utökat skalintervall för bättre matchning vid olika DPI-inställningar
SCALES_MENY = [round(x, 2) for x in np.arange(0.70, 1.35, 0.03)]

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


def find_chrome_path() -> str:
    for c in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.exists(c):
            return c
    return shutil.which("chrome") or "chrome.exe"


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
    print("    📌 Loggbilder sparas automatiskt var 20:e sekund")
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


def match_best(screen_gray, templ_gray, scale=1.0, normalize=True):
    """
    Template matching med histogram equalization för bättre robusthet
    mot olika skärminställningar (ljusstyrka, kontrast, DPI).
    """
    t = templ_gray
    s = screen_gray

    # Normalisera ljusstyrka med histogram equalization (CLAHE)
    if normalize:
        clahe = cv.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        s = clahe.apply(s)
        t = clahe.apply(t)

    if scale != 1.0:
        h, w = t.shape[:2]
        t = cv.resize(
            t,
            (int(w * scale), int(h * scale)),
            interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_CUBIC,
        )
    if s.shape[0] < t.shape[0] or s.shape[1] < t.shape[1]:
        return None, None, None
    res = cv.matchTemplate(s, t, cv.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv.minMaxLoc(res)
    th, tw = t.shape[:2]
    return max_val, max_loc, (tw, th)


def ensure_saved(path, img_bgr):
    ok = cv.imwrite(path, img_bgr)
    if ok and os.path.exists(path):
        print(f"[DEBUG] Sparad: {path}")
    else:
        print(f"[DEBUG] Misslyckades spara: {path}")


# ===========================
# Länk (≥ 0.88, bästa-av-flera, 1s mellan frames)
# ===========================
def locate_best_over_samples(
    img_path, window_region, threshold, timeout_sec, scales, samples
):
    templ = read_template_gray(img_path)
    if templ is None:
        print(f"[FEL] Kan inte läsa: {img_path}")
        return None, None
    t_end = time.time() + timeout_sec
    best_score, best_box, best_frame = -1.0, None, None
    frames = 0
    while frames < samples and time.time() < t_end:
        bgr = grab_region_bgr_any(window_region)  # throttlad
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
        for sc in scales:
            score, loc, (tw, th) = match_best(gray, templ, scale=sc)
            if score is None:
                continue
            if score > best_score:
                L, T, W, H = window_region
                x, y = loc
                best_score, best_box, best_frame = score, (L + x, T + y, tw, th), bgr
        frames += 1
        time.sleep(max(0.0, FRAME_GAP_SEC))  # 1s fri innan nästa frame
    if best_score >= threshold:
        return best_box, best_score
    # debug om miss
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if best_frame is None:
        best_frame = grab_region_bgr_any(window_region)
    ensure_saved(str(Path(DEBUG_DIR) / f"lank_window_{ts}.png"), best_frame)
    if best_box:
        L, T, W, H = best_box
        x = L - window_region[0]
        y = T - window_region[1]
        out = best_frame.copy()
        cv.rectangle(out, (x, y), (x + W, y + H), (0, 0, 255), 2)
        ensure_saved(
            str(Path(DEBUG_DIR) / f"lank_best_below_{best_score:.3f}_{ts}.png"), out
        )
    return None, None


# ===========================
# Meny-matchning (grå+edge+ev. ORB), 1s mellan frames
# ===========================
def locate_menu_robust(img_path: str, window_region, timeout_sec: float):
    templ = read_template_gray(img_path)
    if templ is None:
        return None, None, None, None
    t_end = time.time() + timeout_sec
    best = (-1.0, None, None, None, None)  # score, box, scale, mode, frame
    while time.time() < t_end:
        bgr = grab_region_bgr_any(window_region)  # throttlad
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)

        # Gråskala
        for sc in SCALES_MENY:
            score, loc, (tw, th) = match_best(gray, templ, scale=sc)
            if score is None:
                continue
            if score > best[0]:
                L, T, W, H = window_region
                x, y = loc
                best = (score, (L + x, T + y, tw, th), sc, "gray", bgr)

        # Edge
        edges_scr = cv.Canny(gray, 50, 150)
        edges_tpl = cv.Canny(templ, 50, 150)
        for sc in SCALES_MENY:
            score, loc, (tw, th) = match_best(edges_scr, edges_tpl, scale=sc)
            if score is None:
                continue
            if score > best[0]:
                L, T, W, H = window_region
                x, y = loc
                best = (score, (L + x, T + y, tw, th), sc, "edge", bgr)

        time.sleep(max(0.0, FRAME_GAP_SEC))  # 1s fri till nästa frame
        if best[0] >= 0.97:
            break

    score, box, sc, mode, frame = best

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
    if cy < (wT + TITLEBAR_GUARD):
        return False
    if cx > (wL + wW - RIGHT_GUARD):
        return False
    if cx < (wL + LEFT_GUARD) or cy > (wT + wH - BOTTOM_GUARD):
        return False

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


def type_date_mmddyyyy():
    # Använd TARGET_DATE om den är satt, annars använd senaste arbetsdagen
    target_date_str = os.environ.get("TARGET_DATE")

    # DEBUG: Skriv ut vad som läses
    if target_date_str:
        print(f"[DATE] TARGET_DATE från miljö: {target_date_str}")
    else:
        print("[DATE] Ingen TARGET_DATE satt, använder fallback")

    if target_date_str and len(target_date_str) == 8 and target_date_str.isdigit():
        # TARGET_DATE är i formatet YYYYMMDD, konvertera till mm/dd/yyyy
        try:
            year = int(target_date_str[:4])
            month = int(target_date_str[4:6])
            day = int(target_date_str[6:8])
            target_date = datetime(year, month, day)
            formatted_date = target_date.strftime("%m/%d/%Y")
            print(
                f"[DATE] Skriver datum i formulär: {formatted_date} (från {target_date_str})"
            )
            pg.typewrite(formatted_date)
            return
        except (ValueError, IndexError) as e:
            # Om konvertering misslyckas, fallback till standard
            print(
                f"[DATE] TARGET_DATE konvertering misslyckades: {e}, använder fallback"
            )
            pass

    # Standard: använd senaste arbetsdagen
    today = datetime.now()
    biz = last_business_friday(today)
    fallback_date = biz.strftime("%m/%d/%Y")
    fallback_date_str = biz.strftime("%Y%m%d")
    print(
        f"[DATE] Använder fallback (senaste arbetsdag): {fallback_date} ({fallback_date_str})"
    )
    pg.typewrite(fallback_date)


def special_after_3_bol():
    for _ in range(10):
        pg.click()
        time.sleep(0.04)
    type_date_mmddyyyy()
    rsleep(0.25, 0.50)  # Halverat från (0.50, 1.00)
    pg.press("tab")
    rsleep(0.25, 0.50)  # Halverat
    pg.press("tab")
    rsleep(0.25, 0.50)  # Halverat
    type_date_mmddyyyy()


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
    # Säkerställ att Chrome är i foreground innan vi klickar
    ensure_chrome_foreground(win)
    
    region = refresh_region(win)
    if not region:
        return
    templ = read_template_gray(IMG_POPUP)
    if templ is None:
        return
    end = time.time() + POPUP_TIMEOUT_SEC
    found = False
    while time.time() < end and not found:
        bgr = grab_region_bgr_any(region)
        gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
        for sc in [0.95, 1.00, 1.05]:
            score, loc, (tw, th) = match_best(gray, templ, scale=sc)
            if score and score >= CONF_POPUP:
                found = True
                break
        time.sleep(FRAME_GAP_SEC)
    if found:
        rsleep(0.5, 1.0)  # Halverat från (1.0, 2.0)
        templ_ok = read_template_gray(IMG_OK)
        if templ_ok is not None:
            bgr = grab_region_bgr_any(region)
            gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
            for sc in [0.95, 1.00, 1.05]:
                score, loc, (tw, th) = match_best(gray, templ_ok, scale=sc)
                if score and score >= CONF_OK:
                    x, y = loc
                    box = (region[0] + x, region[1] + y, tw, th)
                    if safe_click_center(box, region, win=win):
                        print("[+] OK klickad.")
                    break


def locate_menu_and_click(img_path: str, win, timeout: float):
    # Säkerställ att Chrome är i foreground innan vi letar/klickar
    ensure_chrome_foreground(win)
    
    region = refresh_region(win)
    print(f"[*] Matchar {Path(img_path).name} ...", end="")
    box, score, sc, mode = locate_menu_robust(img_path, region, timeout_sec=timeout)
    if box is None:
        print(" miss (ingen kandidat).")
        bgr = grab_region_bgr_any(region)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ensure_saved(
            str(Path(DEBUG_DIR) / f"{Path(img_path).stem}_window_{ts}.png"), bgr
        )
        return False, None
    th = (
        CONF_MENY_GRAY
        if mode == "gray"
        else (CONF_MENY_EDGE if mode == "edge" else CONF_MENY_ORB)
    )
    print(f" score={score:.3f} scale={sc if sc else 1.0:.2f} mode={mode}", end="")
    if score < th:
        print(" (under tröskel).")
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
                / f"{Path(img_path).stem}_best_below_{score:.3f}_{ts}.png"
            ),
            out,
        )
        return False, None
    print(" ✓")
    ok = safe_click_center(box, region, win=win)
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

    # Starta screenshot-logger för debugging
    start_screenshot_logger()

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

        # Kontrollera om vi redan är på söksidan (autocomplete har tagit oss dit)
        region = refresh_region(win)
        print("[*] Letar efter 'alternativ_lank.jpg' (≥ 0.82)...")
        alt_best, alt_score = locate_best_over_samples(
            IMG_LANK_ALT,
            region,
            threshold=CONF_LANK,
            timeout_sec=LANK_TIMEOUT,
            scales=SCALES_LANK,
            samples=SAMPLES_LANK,
        )

        if alt_best:
            print(f"[✓] Redan på söksidan (alternativ_lank) score={alt_score:.3f} – hoppar över klick.")
        else:
            # Länk (≥ 0.82)
            print("[*] Letar efter 'lank.jpg' (≥ 0.82)...")
            best, best_score = locate_best_over_samples(
                IMG_LANK,
                region,
                threshold=CONF_LANK,
                timeout_sec=LANK_TIMEOUT,
                scales=SCALES_LANK,
                samples=SAMPLES_LANK,
            )
            if not best:
                print("[FEL] Hittade inte 'lank.jpg' över tröskeln. Se debug i 'debug\\'.")
                if not check_chrome_alive():
                    return 1
                return 1
            print(f"[+] Hittade länk: score={best_score:.3f}")
            if not safe_click_center(best, region, win=win):
                print("[VARN] Klick blockerat (kant/header) – avbryter.")
                if not check_chrome_alive():
                    return 1
                return 1

            if not check_chrome_alive():
                return 1

            rsleep(*WAIT_AFTER_LINK)
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
