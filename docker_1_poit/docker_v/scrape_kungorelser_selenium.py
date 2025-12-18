# -*- coding: utf-8 -*-
"""
scrape_kungorelser_selenium.py

Browser automation för att skrapa kungörelser från Bolagsverket med Selenium.
- Navigerar automatiskt på poit.bolagsverket.se
- Fyller i sökformulär med datum och filter
- Öppnar kungörelser för att extensionen ska kunna fånga data
- Använder bildigenkänning (OpenCV) som fallback när DOM-selektorer inte fungerar
- Fungerar både lokalt och i Docker (headless)

Refaktorerad från scrape_kungorelser.py för att använda Selenium istället för pyautogui.
"""

import os
import re
import time
import random
import sys
import io
import json
import signal
import atexit
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Fixa encoding för Windows-terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import numpy as np
import cv2 as cv
from PIL import Image
from selenium import webdriver  # type: ignore
from selenium.webdriver.chrome.options import Options  # type: ignore
from selenium.webdriver.common.by import By  # type: ignore
from selenium.webdriver.common.action_chains import ActionChains  # type: ignore
from selenium.webdriver.common.keys import Keys  # type: ignore
from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
from selenium.webdriver.support import expected_conditions as EC  # type: ignore
from selenium.common.exceptions import TimeoutException  # type: ignore

# ===========================
# Konfiguration
# ===========================
BASE_DIR = Path(__file__).parent.parent.resolve()
PROFILE_DIR = str(BASE_DIR / "chrome_profile")
DEBUG_DIR = str(BASE_DIR / "debug")
Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)

# Läs config.txt för MAX_KUN_DAG
def read_config():
    config_path = BASE_DIR / "config.txt"
    max_kun = 10
    
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('MAX_KUN_DAG='):
                        value = line.split('=')[1].strip().upper()
                        if value == 'ALL':
                            max_kun = 'ALL'
                            print("[CONFIG] MAX_KUN_DAG satt till: ALL (hämtar alla)")
                        else:
                            try:
                                max_kun = int(value)
                                print(f"[CONFIG] MAX_KUN_DAG satt till: {max_kun}")
                            except ValueError:
                                print(f"[CONFIG] Ogiltigt värde '{value}', använder default: 10")
                                max_kun = 10
                        break
        except Exception:
            print(f"[CONFIG] Kunde inte läsa config.txt, använder default: {max_kun}")
    else:
        print(f"[CONFIG] Ingen config.txt hittad, använder default: {max_kun}")
    
    return max_kun

MAX_KUN_DAG = read_config()

URL_FIRST = "https://www.aftonbladet.se"
URL_SECOND = "https://poit.bolagsverket.se/poit-app/"

# Bildvägar
COOKIE_DIR = BASE_DIR / "bilder" / "1_cookie"
IMG_POPUP = str((COOKIE_DIR / "popup.jpg").resolve()) if (COOKIE_DIR / "popup.jpg").exists() else None
IMG_OK = str((COOKIE_DIR / "ok.jpg").resolve()) if (COOKIE_DIR / "ok.jpg").exists() else None

SOK_DIR = BASE_DIR / "bilder" / "2_sok_kunngorelse"
IMG_LANK = str((SOK_DIR / "lank.jpg").resolve()) if (SOK_DIR / "lank.jpg").exists() else None

MENY_DIR = BASE_DIR / "bilder" / "3_menyer"
MENY_GLOB = "*.*"

# Trösklar för bildmatchning
CONF_POPUP = 0.83
CONF_OK = 0.86
CONF_LANK = 0.92
CONF_MENY_GRAY = 0.88
CONF_MENY_EDGE = 0.84

# Tidsouts
POPUP_TIMEOUT_SEC = 16.0
STEP_TIMEOUT = 18.0
ELEMENT_WAIT_TIMEOUT = 10.0
POST_CLICK_WAIT = (1.0, 2.0)
STRICT_SEQUENCE = True

# Screenshot throttling
FRAME_GAP_SEC = 1.0
_last_capture_ts = 0.0

# Multiskala för bildmatchning
SCALES_LANK = [0.95, 1.00, 1.05]
SAMPLES_LANK = 5
LANK_TIMEOUT = 6.0
SCALES_MENY = [round(x, 2) for x in np.arange(0.85, 1.18, 0.03)]

# ===========================
# Hjälpfunktioner
# ===========================
def rsleep(a: float, b: float) -> None:
    """Random sleep"""
    time.sleep(random.uniform(a, b))

def last_business_friday(d: datetime) -> datetime:
    """Hitta senaste arbetsdagen (fredag om lördag/söndag)"""
    wd = d.weekday()
    if wd == 5:  # Lördag
        return d - timedelta(days=1)
    if wd == 6:  # Söndag
        return d - timedelta(days=2)
    return d

# ===========================
# Selenium WebDriver Setup
# ===========================
def create_chrome_driver(headless: bool = False, extension_path: Optional[str] = None, server_url: Optional[str] = None) -> webdriver.Chrome:
    """Skapa Chrome WebDriver med extension laddad och konfigurerad - optimerad för att undvika bot-detection"""
    chrome_options = Options()
    
    if headless:
        chrome_options.add_argument('--headless=new')  # Ny headless-mode
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
    
    # Ladda extension om angiven
    if extension_path and os.path.exists(extension_path):
        abs_ext_path = os.path.abspath(extension_path)
        chrome_options.add_argument(f'--load-extension={abs_ext_path}')
        print(f"[CHROME] Loading extension from: {abs_ext_path}")
    
    # Använd persistent profile (sparas i volume) - viktigt för cookies och session
    os.makedirs(PROFILE_DIR, exist_ok=True)
    profile_path = os.path.abspath(PROFILE_DIR)
    chrome_options.add_argument(f'--user-data-dir={profile_path}')
    chrome_options.add_argument('--profile-directory=Default')
    print(f"[CHROME] Använder profil: {profile_path}/Default")
    
    # Se till att Chrome inte stänger sig själv
    chrome_options.add_argument('--disable-background-networking')
    chrome_options.add_argument('--disable-background-timer-throttling')
    chrome_options.add_argument('--disable-renderer-backgrounding')
    
    # Anti-bot-detection: Dölj automation-flaggor
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Realistisk user agent (Windows Chrome)
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Ytterligare inställningar för att se mer mänsklig ut
    chrome_options.add_argument('--lang=sv-SE,sv')
    chrome_options.add_argument('--accept-lang=sv-SE,sv;q=0.9,en;q=0.8')
    
    # Window size för konsistenta screenshots (vanlig skärmstorlek)
    chrome_options.add_argument('--window-size=1920,1080')
    
    # Ytterligare inställningar för stabilitet och realism
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-extensions-file-access-check')
    chrome_options.add_argument('--disable-extensions-http-throttling')
    
    # Behåll cache och history för att verka mer mänsklig
    chrome_options.add_argument('--enable-features=NetworkService,NetworkServiceInProcess')
    
    # Om server_url är satt, skapa en konfigurerad extension-version
    if server_url:
        print(f"[CHROME] Server URL: {server_url} (extension kommer använda denna)")
    
    try:
        # Använd ChromeDriver från PATH eller explicit sökväg
        driver = webdriver.Chrome(options=chrome_options)
        print("[CHROME] Driver skapad framgångsrikt")
        
        # Ytterligare anti-detection via CDP (Chrome DevTools Protocol)
        # Dölj webdriver-egenskapen
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            '''
        })
        
        # Dölj automation-flaggor i navigator och lägg till realistiska värden
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                window.navigator.chrome = {
                    runtime: {},
                };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['sv-SE', 'sv', 'en-US', 'en'],
                });
                // Lägg till hardwareConcurrency för realism
                Object.defineProperty(navigator, 'hardwareConcurrency', {
                    get: () => 8,
                });
                // Lägg till deviceMemory för realism
                Object.defineProperty(navigator, 'deviceMemory', {
                    get: () => 8,
                });
            '''
        })
        
        # Sätt realistiska permissions
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            '''
        })
        
        # Dölj automation i window.chrome
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(window, 'chrome', {
                    get: () => ({
                        runtime: {},
                        loadTimes: function() {},
                        csi: function() {},
                        app: {}
                    })
                });
            '''
        })
        
        # Canvas fingerprint randomization (lite variation)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(type) {
                    if (type === 'image/png') {
                        const context = this.getContext('2d');
                        const imageData = context.getImageData(0, 0, this.width, this.height);
                        // Lägg till minimal noise (1 pixel) för att variera fingerprint
                        const data = imageData.data;
                        const index = Math.floor(Math.random() * data.length);
                        data[index] = data[index] ^ (Math.random() < 0.5 ? 1 : 0);
                        context.putImageData(imageData, 0, 0);
                    }
                    return originalToDataURL.apply(this, arguments);
                };
            '''
        })
        
        print("[CHROME] Anti-detection scripts injicerade")
        return driver
    except Exception as e:
        print(f"[FEL] Kunde inte skapa Chrome driver: {e}")
        print("[INFO] Kontrollera att ChromeDriver är installerad och i PATH")
        raise

# ===========================
# Browser Screenshot & OpenCV
# ===========================
def save_debug_screenshot(driver: webdriver.Chrome, name: str) -> None:
    """Spara screenshot för debugging"""
    try:
        debug_dir = BASE_DIR / "debug"
        debug_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = debug_dir / f"{timestamp}_{name}.png"
        driver.save_screenshot(str(screenshot_path))
        print(f"[DEBUG] Screenshot: {screenshot_path.name}")
    except Exception as e:
        print(f"[VARNING] Kunde inte ta screenshot '{name}': {e}")

def grab_browser_screenshot(driver: webdriver.Chrome) -> np.ndarray:
    """Ta screenshot från webbläsaren och konvertera till BGR för OpenCV"""
    global _last_capture_ts
    now = time.time()
    delta = now - _last_capture_ts
    if delta < FRAME_GAP_SEC:
        time.sleep(FRAME_GAP_SEC - delta)
    
    screenshot_png = driver.get_screenshot_as_png()
    img = Image.open(io.BytesIO(screenshot_png))
    # Konvertera RGB -> BGR för OpenCV
    bgr = cv.cvtColor(np.array(img), cv.COLOR_RGB2BGR)
    _last_capture_ts = time.time()
    return bgr

def read_template_gray(path_str: str) -> Optional[np.ndarray]:
    """Läs template-bild som gråskala"""
    if not path_str or not os.path.exists(path_str):
        return None
    return cv.imread(path_str, cv.IMREAD_GRAYSCALE)

def match_template(screen_gray: np.ndarray, templ_gray: np.ndarray, scale: float = 1.0) -> Tuple[Optional[float], Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Matcha template i screenshot med OpenCV"""
    t = templ_gray
    if scale != 1.0:
        h, w = t.shape[:2]
        t = cv.resize(t, (int(w*scale), int(h*scale)),
                      interpolation=cv.INTER_AREA if scale < 1 else cv.INTER_CUBIC)
    
    if screen_gray.shape[0] < t.shape[0] or screen_gray.shape[1] < t.shape[1]:
        return None, None, None
    
    res = cv.matchTemplate(screen_gray, t, cv.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv.minMaxLoc(res)
    th, tw = t.shape[:2]
    return max_val, max_loc, (tw, th)

def locate_by_image(driver: webdriver.Chrome, template_path: str, threshold: float, 
                   timeout: float = 5.0, scales: list = None) -> Tuple[Optional[Tuple[int, int]], Optional[float]]:
    """Hitta element via bildmatchning i browser screenshot"""
    if scales is None:
        scales = [1.0]
    
    templ = read_template_gray(template_path)
    if templ is None:
        return None, None
    
    t_end = time.time() + timeout
    best_score = -1.0
    best_loc = None
    
    while time.time() < t_end:
        screenshot = grab_browser_screenshot(driver)
        gray = cv.cvtColor(screenshot, cv.COLOR_BGR2GRAY)
        
        for scale in scales:
            score, loc, (tw, th) = match_template(gray, templ, scale=scale)
            if score is None:
                continue
            if score > best_score:
                best_score = score
                best_loc = loc
        
        if best_score >= threshold:
            return best_loc, best_score
        
        time.sleep(0.5)  # Kort paus mellan försök
    
    return best_loc, best_score

def click_by_image(driver: webdriver.Chrome, template_path: str, threshold: float, 
                  timeout: float = 5.0) -> bool:
    """Hitta och klicka på element via bildmatchning"""
    loc, score = locate_by_image(driver, template_path, threshold, timeout)
    if loc and score >= threshold:
        x, y = loc
        # Använd JavaScript för att klicka på absoluta koordinater
        try:
            driver.execute_script(f"""
                var element = document.elementFromPoint({x}, {y});
                if (element) {{
                    element.click();
                }} else {{
                    // Fallback: skapa ett klick-event
                    var evt = new MouseEvent('click', {{
                        view: window,
                        bubbles: true,
                        cancelable: true,
                        clientX: {x},
                        clientY: {y}
                    }});
                    document.dispatchEvent(evt);
                }}
            """)
            rsleep(0.5, 1.0)
            return True
        except Exception as e:
            print(f"[VARNING] Kunde inte klicka på bildmatchning: {e}")
            # Fallback till ActionChains
            try:
                action = ActionChains(driver)
                body = driver.find_element(By.TAG_NAME, "body")
                action.move_to_element_with_offset(body, x, y).click().perform()
                action.reset_actions()
                rsleep(0.5, 1.0)
                return True
            except Exception as e2:
                print(f"[VARNING] Fallback klick misslyckades också: {e2}")
                return False
    return False

# ===========================
# DOM-baserade funktioner (föredraget)
# ===========================
def click_by_selector(driver: webdriver.Chrome, selector: str, by: By = By.CSS_SELECTOR, 
                     timeout: float = ELEMENT_WAIT_TIMEOUT) -> bool:
    """Klicka på element via CSS/XPath selector"""
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, selector))
        )
        element.click()
        rsleep(*POST_CLICK_WAIT)
        return True
    except TimeoutException:
        return False
    except Exception as e:
        print(f"[VARNING] Kunde inte klicka på {selector}: {e}")
        return False

def type_text(driver: webdriver.Chrome, selector: str, text: str, by: By = By.CSS_SELECTOR,
              clear_first: bool = True) -> bool:
    """Skriv text i input-fält"""
    try:
        element = WebDriverWait(driver, ELEMENT_WAIT_TIMEOUT).until(
            EC.presence_of_element_located((by, selector))
        )
        if clear_first:
            element.clear()
        # Simulera mänsklig typing
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.01, 0.03))
        return True
    except Exception as e:
        print(f"[VARNING] Kunde inte skriva i {selector}: {e}")
        return False

def press_keys(driver: webdriver.Chrome, *keys) -> None:
    """Tryck tangentbordstangenter"""
    action = ActionChains(driver)
    for key in keys:
        action.send_keys(key)
    action.perform()
    rsleep(0.1, 0.3)

# ===========================
# Cookie & Popup hantering
# ===========================
def handle_cookie_popup(driver: webdriver.Chrome) -> bool:
    """Hantera cookie-popup (försök först med selector, sedan bildmatchning)"""
    # Försök först med vanliga selectors för cookie-popups
    cookie_selectors = [
        "button[id*='accept']",
        "button[class*='accept']",
        "button[class*='cookie']",
        "#cookieAccept",
        ".cookie-accept",
        # XPath för text-innehåll
        "//button[contains(text(), 'Acceptera')]",
        "//button[contains(text(), 'OK')]",
        "//button[contains(text(), 'Accept')]",
    ]
    
    for selector in cookie_selectors:
        try:
            # Använd XPath om selector börjar med //
            by = By.XPATH if selector.startswith("//") else By.CSS_SELECTOR
            if click_by_selector(driver, selector, by=by, timeout=2.0):
                print("[+] Cookie-popup accepterad via selector")
                return True
        except Exception:
            continue
    
    # Fallback till bildmatchning om selectors inte fungerar
    if IMG_POPUP and IMG_OK:
        print("[*] Försöker hitta cookie-popup via bildmatchning...")
        if locate_by_image(driver, IMG_POPUP, CONF_POPUP, timeout=POPUP_TIMEOUT_SEC)[0]:
            rsleep(1.0, 2.0)
            if click_by_image(driver, IMG_OK, CONF_OK, timeout=5.0):
                print("[+] Cookie-popup accepterad via bildmatchning")
                return True
    
    return False

# ===========================
# Meny-navigering
# ===========================
NUM_RE = re.compile(r"^(\d+)_.*\.(jpg|jpeg|png)$", re.IGNORECASE)

def list_ordered_menu_images(directory: Path) -> list:
    """Lista meny-bilder i nummerordning"""
    files = []
    for p in directory.glob(MENY_GLOB):
        m = NUM_RE.match(p.name)
        if m:
            files.append((int(m.group(1)), p))
    files.sort(key=lambda t: t[0])
    return files

def locate_menu_and_click(driver: webdriver.Chrome, img_path: str, timeout: float) -> bool:
    """Hitta och klicka på meny-element via bildmatchning"""
    print(f"[*] Matchar {Path(img_path).name} ...", end="")
    
    templ = read_template_gray(img_path)
    if templ is None:
        print(" miss (kan inte läsa bild).")
        return False
    
    t_end = time.time() + timeout
    best_score = -1.0
    best_loc = None
    
    while time.time() < t_end:
        screenshot = grab_browser_screenshot(driver)
        gray = cv.cvtColor(screenshot, cv.COLOR_BGR2GRAY)
        
        # Testa gråskala-matchning
        for scale in SCALES_MENY:
            score, loc, (tw, th) = match_template(gray, templ, scale=scale)
            if score and score > best_score:
                best_score = score
                best_loc = loc
        
        # Testa edge-detection
        edges_scr = cv.Canny(gray, 50, 150)
        edges_tpl = cv.Canny(templ, 50, 150)
        for scale in SCALES_MENY:
            score, loc, (tw, th) = match_template(edges_scr, edges_tpl, scale=scale)
            if score and score > best_score:
                best_score = score
                best_loc = loc
        
        if best_score >= CONF_MENY_GRAY:
            break
        
        time.sleep(FRAME_GAP_SEC)
    
    threshold = CONF_MENY_GRAY
    print(f" score={best_score:.3f}", end="")
    
    if best_loc and best_score >= threshold:
        print(" ✓")
        x, y = best_loc
        try:
            # Använd JavaScript för att klicka på absoluta koordinater
            driver.execute_script(f"""
                var element = document.elementFromPoint({x}, {y});
                if (element) {{
                    element.click();
                }} else {{
                    var evt = new MouseEvent('click', {{
                        view: window,
                        bubbles: true,
                        cancelable: true,
                        clientX: {x},
                        clientY: {y}
                    }});
                    document.dispatchEvent(evt);
                }}
            """)
            rsleep(*POST_CLICK_WAIT)
            return True
        except Exception as e:
            print(f" (klick misslyckades: {e})")
            # Fallback till ActionChains
            try:
                action = ActionChains(driver)
                body = driver.find_element(By.TAG_NAME, "body")
                action.move_to_element_with_offset(body, x, y).click().perform()
                action.reset_actions()
                rsleep(*POST_CLICK_WAIT)
                return True
            except Exception as e2:
                print(f" (fallback klick misslyckades: {e2})")
                return False
    else:
        print(" (under tröskel)")
        return False

def run_menu_sequence(driver: webdriver.Chrome):
    """Kör meny-sekvensen baserat på numrerade bilder"""
    steps = list_ordered_menu_images(MENY_DIR)
    if not steps:
        print(f"[VARNING] Inga meny-bilder i {MENY_DIR}")
        return
    
    print("[*] Meny-steg:", ", ".join(f"{n}:{p.name}" for n, p in steps))
    
    for num, path in steps:
        ok = locate_menu_and_click(driver, str(path.resolve()), timeout=STEP_TIMEOUT)
        if not ok:
            if STRICT_SEQUENCE:
                print("[!] Avbryter (STRICT_SEQUENCE=True).")
                return
            else:
                print("[!] Fortsätter...")
                continue
        
        # Efter steg 1 → 5× ned + Enter
        if num == 1:
            time.sleep(0.25)
            for _ in range(5):
                press_keys(driver, Keys.ARROW_DOWN)
                time.sleep(0.10)
            press_keys(driver, Keys.ENTER)
        
        # Efter steg 5, 7, 9 → 1× ned + Enter
        if num in (5, 7, 9):
            time.sleep(0.30)
            press_keys(driver, Keys.ARROW_DOWN)
            time.sleep(0.30)
            press_keys(driver, Keys.ENTER)
            time.sleep(0.20)
            
            # Extra sekvens för steg 5
            if num == 5:
                time.sleep(random.uniform(0.0, 5.0))
                press_keys(driver, Keys.ARROW_DOWN)
                time.sleep(1.0)
                press_keys(driver, Keys.ARROW_DOWN)
                time.sleep(0.5)
                press_keys(driver, Keys.ENTER)
        
        # Särfall 3_bol (datum)
        if num == 3 and "bol" in path.stem.lower():
            # Försök hitta datum-fält och fyll i
            today = datetime.now()
            biz = last_business_friday(today)
            date_str = biz.strftime("%m/%d/%Y")
            
            # Försök hitta datum-inputs (vanliga selectors)
            date_selectors = [
                "input[type='date']",
                "input[name*='date']",
                "input[id*='date']",
            ]
            
            for selector in date_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        for elem in elements[:2]:  # Max 2 datum-fält
                            elem.clear()
                            elem.send_keys(date_str)
                            rsleep(0.5, 1.0)
                            press_keys(driver, Keys.TAB)
                        break
                except Exception:
                    continue

# ===========================
# Öppna kungörelser
# ===========================
def open_missing_kungorelser(driver: webdriver.Chrome, max_count=None):
    """Öppna saknade kungörelser i nya flikar"""
    if max_count is None:
        max_count = MAX_KUN_DAG
    
    print("\n" + "="*60)
    print("ÖPPNAR SAKNADE KUNGÖRELSER")
    if max_count == 'ALL':
        print("Max antal att hämta: ALLA")
    else:
        print(f"Max antal att hämta: {max_count}")
    print("="*60)
    
    # Hitta senaste JSON-fil
    info_server_dir = BASE_DIR / "info_server"
    date_str = datetime.now().strftime("%Y%m%d")
    date_folder = info_server_dir / date_str
    json_file = None
    
    if date_folder.exists():
        json_files = list(date_folder.glob("kungorelser_*.json"))
        if json_files:
            json_file = json_files[0]
    
    if not json_file:
        json_files = list(info_server_dir.glob("kungorelser_*.json"))
        if not json_files:
            print("[INFO] Ingen kungorelser JSON hittades")
            return
        json_files.sort(key=lambda x: x.stem.split('_')[1] if '_' in x.stem else '', reverse=True)
        json_file = json_files[0]
    
    print(f"[INFO] Använder: {json_file.parent.name}/{json_file.name}")
    
    # Ladda kungörelser
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
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
    
    # Kolla vilka som redan finns
    existing = set()
    for folder in info_server_dir.iterdir():
        if folder.is_dir() and folder.name.startswith('K') and '-' in folder.name:
            existing.add(folder.name.replace('-', '/'))
    
    if date_folder.exists():
        for folder in date_folder.iterdir():
            if folder.is_dir() and folder.name.startswith('K') and '-' in folder.name:
                existing.add(folder.name.replace('-', '/'))
    
    print(f"[INFO] {len(existing)} redan nedladdade")
    
    # Hitta saknade
    missing = [k for k in all_kungorelser if k not in existing]
    print(f"[INFO] {len(missing)} saknas")
    
    if not missing:
        print("✅ Alla kungörelser redan nedladdade!")
        return
    
    # Öppna upp till max_count kungörelser
    if max_count == 'ALL':
        count = len(missing)
    else:
        count = min(max_count, len(missing))
    print(f"\n[ACTION] Öppnar {count} kungörelser...")
    
    original_window = driver.current_window_handle
    
    for i, kung_id in enumerate(missing[:count], 1):
        print(f"\n[{i}/{count}] Kungörelse: {kung_id}")
        
        # Öppna ny flik
        driver.execute_script("window.open('');")
        driver.switch_to.window(driver.window_handles[-1])
        
        # Navigera till kungörelse
        url_id = kung_id.replace('/', '-')
        url = f"https://poit.bolagsverket.se/poit-app/kungorelse/{url_id}"
        driver.get(url)
        
        print("  Väntar på laddning...")
        rsleep(2.0, 3.0)
        
        # Scrolla lite för att verka mänsklig
        driver.execute_script(f"window.scrollBy(0, {random.randint(100, 300)});")
        rsleep(0.3, 0.6)
        driver.execute_script(f"window.scrollBy(0, {random.randint(-150, -50)});")
        
        # Vänta så extensionen kan fånga data
        wait_time = random.uniform(4.0, 6.0)
        print(f"  Väntar {wait_time:.1f}s för datafångst...")
        time.sleep(wait_time)
        
        # Stäng fliken
        driver.close()
        driver.switch_to.window(original_window)
        
        print("  ✓ Klar")
        
        # Paus mellan kungörelser
        if i < count:
            pause = random.uniform(1.5, 3.0)
            print(f"  Paus {pause:.1f}s innan nästa...")
            time.sleep(pause)
    
    print(f"\n✅ Öppnade {count} kungörelser")
    print(f"💡 {len(missing) - count} kungörelser återstår")

# ===========================
# Huvudfunktion
# ===========================
def main():
    """Huvudfunktion för scraping"""
    # Kolla om vi kör i headless-läge (Docker)
    # Om HEADLESS inte är satt, kör i synligt läge lokalt för att kunna lösa CAPTCHA
    headless_env = os.environ.get("HEADLESS", "").lower()
    if headless_env == "true":
        headless = True
    elif headless_env == "false":
        headless = False
    else:
        # Om HEADLESS inte är satt, kör synligt lokalt (för att lösa CAPTCHA första gången)
        headless = False
        print("[INFO] HEADLESS inte satt - kör i synligt läge för att kunna lösa CAPTCHA")
        print("[INFO] Sätt HEADLESS=true för att köra headless")
    
    ext_path = str(BASE_DIR / "ext_bolag")
    server_url = os.environ.get("SERVER_URL", "http://127.0.0.1:5000")
    
    print("=" * 50)
    print("BOLAGSVERKET SCRAPER - Selenium Version")
    print(f"Headless: {headless}")
    print(f"Extension: {ext_path}")
    print(f"Server URL: {server_url}")
    print("=" * 50)
    
    driver = None
    
    def cleanup():
        """Stäng driver vid avbrott"""
        if driver:
            try:
                print("\n[CLEANUP] Stänger browser...")
                driver.quit()
            except Exception:
                pass
    
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda s, f: (cleanup(), exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (cleanup(), exit(0)))
    
    try:
        # Skapa driver med extension och server URL
        driver = create_chrome_driver(headless=headless, extension_path=ext_path, server_url=server_url)
        print("[+] Chrome driver skapad med extension")
        
        # Öppna flera flikar för att verka mer mänsklig (som en riktig användare)
        print("[*] Öppnar flera flikar för att verka mer mänsklig...")
        background_tabs = [
            "https://www.google.com",
            "https://www.aftonbladet.se",
            "https://www.svt.se",
        ]
        for tab_url in background_tabs:
            try:
                driver.execute_script(f"window.open('{tab_url}', '_blank');")
                rsleep(0.3, 0.7)  # Kort paus mellan flikar
            except Exception as e:
                print(f"[VARNING] Kunde inte öppna flik {tab_url}: {e}")
        
        # Växla tillbaka till första fliken (index 0)
        driver.switch_to.window(driver.window_handles[0])
        rsleep(1.0, 2.0)
        print(f"[+] Öppnade {len(driver.window_handles)} flikar totalt")
        
        # Konfigurera extensionen med rätt server URL via JavaScript injection
        # Detta görs efter att Chrome startat men innan vi navigerar
        try:
            driver.execute_cdp_cmd('Runtime.evaluate', {
                'expression': f'''
                    chrome.storage.local.set({{server_url: "{server_url}"}}, function() {{
                        console.log("Server URL set to: {server_url}");
                    }});
                '''
            })
            print("[+] Extension konfigurerad med server URL:", server_url)
        except Exception as e:
            print(f"[VARNING] Kunde inte konfigurera extension: {e}")
            print("[INFO] Extension kommer använda default URL (kan ändå fungera)")
        
        # Navigera till Google först (mer mänskligt beteende)
        print("[*] Navigerar till Google för att söka...")
        driver.get("https://www.google.com")
        rsleep(2.0, 3.0)
        print(f"[+] Google laddad: {driver.title}")
        save_debug_screenshot(driver, "01_google")
        
        # Acceptera cookies om de kommer (Google) - viktigt!
        print("[*] Försöker acceptera Google cookies...")
        try:
            # Vänta lite för att cookie-popup ska visas
            rsleep(1.0, 2.0)
            
            # Vanliga selectors för Google cookie-accept (svenska och engelska)
            cookie_selectors = [
                ("button[id='L2AGLb']", By.CSS_SELECTOR),  # Google's accept button ID (vanligast)
                ("//button[contains(text(), 'Godkän alla')]", By.XPATH),
                ("//button[contains(text(), 'Acceptera alla')]", By.XPATH),
                ("//button[contains(text(), 'Acceptera')]", By.XPATH),
                ("//button[contains(text(), 'Accept all')]", By.XPATH),
                ("//button[contains(text(), 'Accept')]", By.XPATH),
                ("//button[contains(@aria-label, 'Godkänn')]", By.XPATH),
                ("//button[contains(@aria-label, 'Accept')]", By.XPATH),
                ("button[aria-label*='Godkänn']", By.CSS_SELECTOR),
                ("button[aria-label*='Accept']", By.CSS_SELECTOR),
            ]
            
            cookie_accepted = False
            for selector, by_type in cookie_selectors:
                try:
                    element = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((by_type, selector))
                    )
                    # Scrolla till elementet om det behövs
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
                    rsleep(0.3, 0.5)
                    element.click()
                    print(f"[+] Google cookies accepterade med selector: {selector}")
                    cookie_accepted = True
                    rsleep(1.0, 2.0)
                    break
                except Exception:
                    continue
            
            if not cookie_accepted:
                print("[VARNING] Kunde inte hitta cookie-knapp, fortsätter ändå...")
                # Ta screenshot för debugging
                save_debug_screenshot(driver, "01_google_no_cookie_button")
        except Exception as e:
            print(f"[VARNING] Fel vid cookie-accept: {e}")
            save_debug_screenshot(driver, "01_google_cookie_error")
        
        # Logga in på Google om credentials finns (valfritt - kan hoppa över om CAPTCHA kommer)
        # Standard: hoppa över Google-inloggning för att undvika CAPTCHA-problem
        google_email = os.environ.get("GOOGLE_EMAIL", "")
        google_password = os.environ.get("GOOGLE_PASSWORD", "")
        skip_google_login = os.environ.get("SKIP_GOOGLE_LOGIN", "true").lower() == "true"  # Default: true (hoppa över)
        
        if google_email and google_password and not skip_google_login:
            print(f"[*] Försöker logga in på Google med {google_email}...")
            try:
                # Klicka på "Logga in" knappen om den finns
                login_selectors = [
                    ("a[href*='accounts.google.com']", By.CSS_SELECTOR),
                    ("//a[contains(text(), 'Logga in')]", By.XPATH),
                    ("//a[contains(text(), 'Sign in')]", By.XPATH),
                    ("a[aria-label*='Logga in']", By.CSS_SELECTOR),
                    ("a[aria-label*='Sign in']", By.CSS_SELECTOR),
                ]
                
                login_clicked = False
                for selector, by_type in login_selectors:
                    try:
                        element = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((by_type, selector))
                        )
                        element.click()
                        print("[+] Klickade på logga in-länk")
                        login_clicked = True
                        rsleep(2.0, 3.0)
                        break
                    except Exception:
                        continue
                
                # Om ingen logga in-länk hittades, gå direkt till accounts.google.com
                if not login_clicked:
                    print("[*] Går direkt till Google Accounts...")
                    driver.get("https://accounts.google.com/signin")
                    rsleep(2.0, 3.0)
                
                # Fyll i email
                try:
                    email_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.ID, "identifierId"))
                    )
                    email_input.clear()
                    email_input.send_keys(google_email)
                    rsleep(0.5, 1.0)
                    
                    # Klicka på "Nästa"
                    next_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "identifierNext"))
                    )
                    next_button.click()
                    print("[+] Email angivet, klickade på Nästa")
                    rsleep(2.0, 3.0)
                    
                    # Fyll i lösenord
                    password_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.NAME, "password"))
                    )
                    password_input.clear()
                    password_input.send_keys(google_password)
                    rsleep(0.5, 1.0)
                    
                    # Klicka på "Nästa"
                    password_next = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "passwordNext"))
                    )
                    password_next.click()
                    print("[+] Lösenord angivet, klickade på Nästa")
                    rsleep(3.0, 5.0)
                    
                    # Kolla om CAPTCHA kommer
                    try:
                        # Vänta kort för att se om CAPTCHA kommer
                        WebDriverWait(driver, 5).until(
                            lambda d: "captcha" in d.page_source.lower() or "recaptcha" in d.page_source.lower()
                        )
                        print("[VARNING] CAPTCHA detekterad från Google!")
                        print("[INFO] Om du kör lokalt i synligt läge kan du lösa CAPTCHA:n manuellt")
                        print("[INFO] Sessionen sparas i profilen så Docker kan använda den senare")
                        save_debug_screenshot(driver, "01_google_captcha")
                        
                        # Om vi inte är i headless-läge, vänta längre så användaren kan lösa CAPTCHA
                        if not headless:
                            print("[*] Väntar 60 sekunder för manuell CAPTCHA-lösning...")
                            print("[*] Lös CAPTCHA:n i webbläsaren nu!")
                            rsleep(60.0, 90.0)
                        else:
                            print("[VARNING] Headless-läge - kan inte lösa CAPTCHA automatiskt")
                            print("[INFO] Kör lokalt i synligt läge för att lösa CAPTCHA första gången")
                            rsleep(10.0, 15.0)  # Vänta ändå lite
                    except Exception:
                        # Ingen CAPTCHA, fortsätt normalt
                        pass
                    
                    # Vänta på att inloggningen är klar
                    try:
                        WebDriverWait(driver, 15).until(
                            lambda d: "accounts.google.com" not in d.current_url or "myaccount.google.com" in d.current_url
                        )
                        print("[+] Inloggning lyckades!")
                        save_debug_screenshot(driver, "01_google_logged_in")
                    except Exception:
                        print("[VARNING] Kunde inte bekräfta inloggning, fortsätter ändå...")
                        save_debug_screenshot(driver, "01_google_login_uncertain")
                    
                except Exception as e:
                    print(f"[VARNING] Kunde inte logga in på Google: {e}")
                    save_debug_screenshot(driver, "01_google_login_error")
                    
            except Exception as e:
                print(f"[VARNING] Fel vid Google-inloggning: {e}")
        else:
            print("[INFO] Ingen Google-inloggning (GOOGLE_EMAIL/GOOGLE_PASSWORD inte satt)")
        
        # Gå tillbaka till Google om vi är på accounts-sidan
        try:
            if "accounts.google.com" in driver.current_url:
                print("[*] Går tillbaka till Google...")
                driver.get("https://www.google.com")
                rsleep(2.0, 3.0)
        except Exception as e:
            print(f"[VARNING] Kunde inte gå tillbaka till Google: {e}")
            # Om fönstret är stängt, försök öppna en ny
            try:
                driver.get("https://www.google.com")
                rsleep(2.0, 3.0)
            except Exception:
                print("[FEL] Chrome-fönstret verkar vara stängt")
                return
        
        # Sök efter "poit.bolagsverket" på Google
        print("[*] Söker efter 'poit.bolagsverket' på Google...")
        try:
            # Hitta sökfältet
            search_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            search_box.clear()
            search_box.send_keys("poit.bolagsverket")
            rsleep(0.5, 1.0)
            search_box.send_keys(Keys.RETURN)
            rsleep(2.0, 3.0)
            print("[+] Sökning utförd")
            save_debug_screenshot(driver, "02_google_search")
            
            # Hitta första sökresultatet och klicka på det
            print("[*] Hittar första sökresultatet...")
            try:
                # Vänta på sökresultat
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.g, div[data-ved]"))
                )
                
                # Försök olika selectors för första resultatet
                result_selectors = [
                    ("div.g:first-of-type h3 a", By.CSS_SELECTOR),
                    ("div.g:first-of-type a h3", By.CSS_SELECTOR),
                    ("div[data-ved]:first-of-type h3 a", By.CSS_SELECTOR),
                    ("//div[@class='g']//h3//a[1]", By.XPATH),
                    ("//div[contains(@class, 'g')]//h3//a[1]", By.XPATH),
                    ("//a[contains(@href, 'poit.bolagsverket')]", By.XPATH),
                ]
                
                first_result = None
                for selector, by_type in result_selectors:
                    try:
                        first_result = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((by_type, selector))
                        )
                        print(f"[+] Hittade sökresultat med selector: {selector}")
                        break
                    except Exception:
                        continue
                
                if first_result:
                    # Scrolla till elementet för att se det
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", first_result)
                    rsleep(0.5, 1.0)
                    
                    # Klicka på första resultatet
                    first_result.click()
                    print("[+] Klickade på första sökresultatet")
                    rsleep(3.0, 5.0)  # Vänta på att sidan laddas
                    print(f"[+] Sidan laddad: {driver.title}")
                    print(f"[+] Current URL: {driver.current_url}")
                    save_debug_screenshot(driver, "03_after_google_click")
                else:
                    raise Exception("Kunde inte hitta första sökresultatet")
                
            except Exception as e:
                print(f"[VARNING] Kunde inte hitta första sökresultatet: {e}")
                print("[*] Fallback: Navigerar direkt till URL...")
                driver.get(URL_SECOND)
                rsleep(2.0, 3.0)
                
        except Exception as e:
            print(f"[VARNING] Kunde inte söka på Google: {e}")
            print("[*] Fallback: Navigerar direkt till URL...")
            driver.get(URL_SECOND)
            rsleep(2.0, 3.0)
        
        # Växla mellan flikar lite för att verka mänsklig
        if len(driver.window_handles) > 1:
            print("[*] Simulerar flik-växling (mänskligt beteende)...")
            for _ in range(2):
                # Växla till en annan flik
                other_tab = driver.window_handles[random.randint(1, len(driver.window_handles) - 1)]
                driver.switch_to.window(other_tab)
                rsleep(0.5, 1.5)
                # Växla tillbaka
                driver.switch_to.window(driver.window_handles[0])
                rsleep(0.5, 1.5)
        
        # Om vi inte redan är på rätt sida, navigera dit
        # Om vi hamnade på Google Accounts (inloggning krävs), gå direkt till URL:en istället
        if "poit.bolagsverket" not in driver.current_url.lower():
            if "accounts.google.com" in driver.current_url.lower():
                print("[INFO] Google kräver inloggning för sökresultat")
                print("[INFO] Går direkt till poit.bolagsverket.se istället...")
            print(f"[*] Navigerar till: {URL_SECOND}")
            driver.get(URL_SECOND)
        rsleep(2.0, 3.0)
        print(f"[+] Sidan laddad: {driver.title}")
        print(f"[+] Current URL: {driver.current_url}")
        save_debug_screenshot(driver, "02_bolagsverket_initial")
        
        # Vänta på att sidan är redo (SPA behöver tid för JavaScript)
        print("[*] Väntar på att sidan laddas...")
        try:
            # Vänta på att dokumentet är komplett
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            print("[+] Dokumentet är komplett")
            
            # Ytterligare väntan för SPA att ladda innehåll
            rsleep(3.0, 5.0)
            
            # Försök vänta på att länkar eller knappar visas
            try:
                WebDriverWait(driver, 15).until(
                    lambda d: len(d.find_elements(By.TAG_NAME, "a")) > 5 or 
                              len(d.find_elements(By.TAG_NAME, "button")) > 0
                )
                print("[+] Innehåll verkar ha laddats (länkar/knappar hittade)")
            except TimeoutException:
                print("[VARNING] Inga länkar/knappar hittades efter väntan")
            
        except Exception as e:
            print(f"[VARNING] Kunde inte bekräfta att sidan är redo: {e}")
        
        save_debug_screenshot(driver, "03_after_page_ready")
        
        # Scrolla lite för att trigga lazy loading om det finns
        # Simulera mänskligt beteende med mjuka scrollningar
        print("[*] Simulerar mänskligt beteende (scrollning)...")
        for i in range(3):
            scroll_amount = random.randint(200, 500)
            driver.execute_script(f"window.scrollTo({{top: {scroll_amount}, behavior: 'smooth'}});")
            rsleep(0.8, 1.5)
        driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
        rsleep(1.5, 2.5)
        
        # Ytterligare väntan för att verka mänsklig
        rsleep(2.0, 3.0)
        
        # Hantera cookie-popup
        print("[*] Försöker hantera cookie-popup...")
        cookie_handled = handle_cookie_popup(driver)
        if cookie_handled:
            print("[+] Cookie-popup hanterad")
            save_debug_screenshot(driver, "04_after_cookie")
        else:
            print("[INFO] Ingen cookie-popup hittades (kan vara OK)")
        rsleep(2.0, 3.0)
        
        # Debug: Ta screenshot för att se vad som visas innan sök-länk
        save_debug_screenshot(driver, "05_before_search_link")
        
        # Försök hitta "Sök kungörelser" länk
        # Först med selector, sedan bildmatchning
        link_found = False
        
        # Vanliga selectors för sök-länk
        link_selectors = [
            ("a[href*='kungorelse']", By.CSS_SELECTOR),
            ("//a[contains(text(), 'Sök')]", By.XPATH),
            ("//a[contains(text(), 'kungörelse')]", By.XPATH),
            ("//a[contains(@href, 'kungorelse')]", By.XPATH),
            ("a[href*='kung']", By.CSS_SELECTOR),
            ("//a[contains(@href, 'kung')]", By.XPATH),
        ]
        
        print("[*] Försöker hitta sök-länk via selectors...")
        for selector, by_type in link_selectors:
            try:
                print(f"  → Testar: {selector}")
                if click_by_selector(driver, selector, by=by_type, timeout=3.0):
                    print(f"[+] Hittade sök-länk via selector: {selector}")
                    link_found = True
                    break
            except Exception as e:
                print(f"  → Misslyckades: {e}")
                continue
        
        # Fallback till bildmatchning
        if not link_found and IMG_LANK:
            print("[*] Försöker hitta sök-länk via bildmatchning...")
            if click_by_image(driver, IMG_LANK, CONF_LANK, timeout=LANK_TIMEOUT):
                print("[+] Hittade sök-länk via bildmatchning")
                link_found = True
        
        if not link_found:
            print("[FEL] Kunde inte hitta sök-länk")
            save_debug_screenshot(driver, "06_search_link_not_found")
            print("[DEBUG] Försöker lista alla länkar på sidan...")
            try:
                links = driver.find_elements(By.TAG_NAME, "a")
                print(f"[DEBUG] Hittade {len(links)} länkar:")
                for i, link in enumerate(links[:10]):  # Visa första 10
                    try:
                        href = link.get_attribute("href")
                        text = link.text[:50]
                        print(f"  {i+1}. {text} -> {href}")
                    except Exception:
                        pass
            except Exception as e:
                print(f"[DEBUG] Kunde inte lista länkar: {e}")
            return
        
        save_debug_screenshot(driver, "07_search_link_found")
        
        rsleep(3.5, 5.0)
        
        # Kör meny-sekvensen
        run_menu_sequence(driver)
        print("[✓] Sökformulär klar.")
        
        # Vänta på sökresultat
        rsleep(2.0, 3.0)
        
        # Öppna saknade kungörelser
        open_missing_kungorelser(driver)
        
        print("\n[✓] ALLT KLART!")
        
    except Exception as e:
        print(f"\n[FEL] Ett fel uppstod: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cleanup()

if __name__ == "__main__":
    main()

