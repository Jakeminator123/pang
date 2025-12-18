"""Playwright-based browser scraping for kungörelser (Docker version)."""

import asyncio
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext

BASE_URL = "https://poit.bolagsverket.se"

# Detect Docker environment
IS_DOCKER = os.environ.get("IS_DOCKER", "").lower() == "true" or Path("/.dockerenv").exists()
CHROME_PROFILE_DIR = Path("/app/chrome_profile") if IS_DOCKER else Path(__file__).parent.parent / "chrome_profile"


async def get_browser_context(cookie_wait: int = 15):
    """
    Get a browser context - either by connecting to existing Chrome (local)
    or launching a new browser (Docker).
    
    Returns:
        Tuple of (playwright, browser/context, context, is_docker)
    """
    p = await async_playwright().start()
    
    if IS_DOCKER:
        print("    [DOCKER] Startar headless Chromium med persistent profil...")
        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Use persistent context for Docker
        context = await p.chromium.launch_persistent_context(
            str(CHROME_PROFILE_DIR),
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            timeout=60000
        )
        return p, context, context, True
    else:
        print("    Ansluter till lokal Chrome via CDP...")
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        return p, browser, context, False


async def get_cookies_from_browser(context: BrowserContext, cookie_wait: int = 15) -> dict:
    """
    Navigate to site and extract cookies.
    Handles cookie banner automatically.
    """
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        
        # Navigate to site
        if "poit.bolagsverket.se" not in page.url:
            print(f"    [NAV] Navigerar till {BASE_URL}/poit-app/...")
            await page.goto(f"{BASE_URL}/poit-app/", wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
        
        # Handle cookie banner
        try:
            cookie_selectors = [
                'button[data-cf-action="accept"]',
                'button:has-text("Acceptera")',
                'button:has-text("Godkänn")',
                'button:has-text("OK")',
            ]
            for selector in cookie_selectors:
                try:
                    btn = await page.query_selector(selector)
                    if btn and await btn.is_visible():
                        print(f"    [COOKIE] Banner hittad, klickar...")
                        await btn.click()
                        print(f"    [WAIT] Väntar {cookie_wait}s efter cookie-klick...")
                        await asyncio.sleep(cookie_wait)
                        break
                except Exception:
                    continue
        except Exception:
            pass
        
        # Scroll a bit to trigger any lazy-loading/WAF
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(2)
        
        # Get cookies
        cookies = await context.cookies()
        cookie_dict = {}
        ts_count = 0
        for c in cookies:
            if "bolagsverket" in c.get("domain", ""):
                cookie_dict[c["name"]] = c["value"]
                if "TS" in c["name"]:
                    ts_count += 1
        
        print(f"    [COOKIES] {len(cookie_dict)} cookies ({ts_count} TS-cookies)")
        return cookie_dict
        
    except Exception as e:
        print(f"    [COOKIE ERROR] {e}")
        return {}


async def scrape_single_page(
    context: BrowserContext, 
    kung_id: str, 
    output_folder: Path, 
    wait_range: tuple
) -> dict:
    """
    Scrape a single kungörelse page.
    """
    normalized_id = kung_id.replace("/", "-")
    url = f"{BASE_URL}/poit-app/kungorelse/{normalized_id}"
    result = {"id": kung_id, "success": False}
    
    page = await context.new_page()
    
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # Wait for JavaScript to render content
        wait_time = random.uniform(*wait_range)
        await asyncio.sleep(wait_time)
        
        # Handle "enskild" intermediate page (redirect page)
        max_retries = 3
        for retry in range(max_retries):
            if "/enskild/" in page.url:
                # Wait for potential auto-redirect
                await asyncio.sleep(random.uniform(2, 3))
                
                # If still on enskild, try clicking through
                if "/enskild/" in page.url:
                    # Try multiple selectors
                    link = await page.query_selector('a[href*="/kungorelse/K"]')
                    if not link:
                        link = await page.query_selector('a.btn-link[href*="/kungorelse"]')
                    if link:
                        await link.click()
                        await asyncio.sleep(random.uniform(*wait_range))
            else:
                break
        
        # Also handle case where we land on main page (not kungorelse)
        current_url = page.url
        if current_url.endswith("/poit-app/") or current_url.endswith("/poit-app"):
            # We got redirected to main page - try direct navigation again
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(*wait_range))
            current_url = page.url
        
        # Verify we're on the actual kungörelse page (not enskild)
        if "/kungorelse/" in current_url and "/enskild/" not in current_url:
            text_content = await page.inner_text("body")
            title = await page.title()
            
            # Check for actual kungörelse content
            has_content = any([
                "Kungörelsetext" in text_content,
                "Org nr:" in text_content,
                "Registreringsdatum" in text_content
            ])
            
            if has_content and len(text_content) > 500:
                # Save to output folder
                kung_folder = output_folder / normalized_id
                kung_folder.mkdir(parents=True, exist_ok=True)
                
                timestamp = datetime.now().isoformat()
                
                # Save only content.txt
                with open(kung_folder / "content.txt", "w", encoding="utf-8") as f:
                    f.write(f"URL: {current_url}\n")
                    f.write(f"Title: {title}\n")
                    f.write(f"Timestamp: {timestamp}\n")
                    f.write("=" * 60 + "\n\n")
                    f.write(text_content)
                
                result["success"] = True
                result["chars"] = len(text_content)
            else:
                result["error"] = "Inget innehåll"
        else:
            page_type = current_url.split("/")[-2] if "/" in current_url else "okänd"
            result["error"] = f"Fel sida: {page_type}"
            
    except Exception as e:
        result["error"] = str(e)[:50]
    finally:
        await page.close()
    
    return result


async def scrape_kungorelse_pages(
    kung_ids: list, 
    output_folder: Path, 
    parallel: int = 1,
    wait_range: tuple = (4, 6),
    between_range: tuple = (2, 4),
    context: Optional[BrowserContext] = None
) -> list:
    """
    Scrape multiple kungörelse pages.
    """
    results = []
    total = len(kung_ids)
    
    # Use provided context or create new one
    own_context = context is None
    p = None
    browser = None
    
    try:
        if own_context:
            p, browser, context, _ = await get_browser_context()
        
        for i in range(0, total, parallel):
            batch = kung_ids[i:i + parallel]
            batch_num = i // parallel + 1
            total_batches = (total + parallel - 1) // parallel
            print(f"\n    Batch {batch_num}/{total_batches}: {len(batch)} sida(or)...")
            
            # Process batch
            for kid in batch:
                r = await scrape_single_page(context, kid, output_folder, wait_range)
                status = "✓" if r["success"] else "✗"
                if r["success"]:
                    info = f"{r.get('chars', 0)} tecken"
                else:
                    info = r.get("error", "Okänt fel")
                print(f"      {status} {kid}: {info}")
                results.append(r)
            
            # Wait between batches
            if i + parallel < total:
                wait = random.uniform(*between_range)
                print(f"    Väntar {wait:.1f}s...")
                await asyncio.sleep(wait)
                
    except Exception as e:
        print(f"    [SCRAPER ERROR] {e}")
    finally:
        if own_context and browser:
            await browser.close()
        if p:
            await p.stop()
    
    return results


# Legacy function for backward compatibility
async def get_cookies_from_chrome(cookie_wait: int = 15) -> dict:
    """Legacy wrapper - connects to Chrome and gets cookies."""
    try:
        p, browser, context, _ = await get_browser_context(cookie_wait)
        cookies = await get_cookies_from_browser(context, cookie_wait)
        await browser.close()
        await p.stop()
        return cookies
    except Exception as e:
        print(f"    [COOKIE ERROR] {e}")
        return {}
