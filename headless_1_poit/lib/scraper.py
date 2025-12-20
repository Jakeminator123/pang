"""Playwright-based browser scraping for kungörelser."""

import asyncio
import random
from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import Optional

from playwright.async_api import async_playwright

BASE_URL = "https://poit.bolagsverket.se"

# CAPTCHA backoff state (shared between calls)
_captcha_backoff_seconds = 0
_captcha_count = 0


class BlockReason(Enum):
    """Reasons why a page might be blocked or need intervention."""
    NONE = "none"
    COOKIE_BANNER = "cookie_banner"
    CAPTCHA = "captcha"
    RATE_LIMITED = "rate_limited"
    ENSKILD_PAGE = "enskild_page"
    ACCESS_DENIED = "access_denied"
    UNKNOWN = "unknown"


async def detect_block_reason(page) -> BlockReason:
    """
    Detect WHY a page is blocked or needs intervention.
    This is more specific than just detect_captcha().
    
    Returns:
        BlockReason enum indicating the type of block.
    """
    try:
        url = page.url.lower()
        
        # Check URL first (fastest)
        if "/enskild/" in url:
            return BlockReason.ENSKILD_PAGE
        
        # Get page text for content analysis
        text = await page.inner_text("body")
        text_lower = text.lower()
        
        # Check for cookie banner (highest priority - easy to fix)
        cookie_indicators = [
            "acceptera cookies",
            "vi använder cookies",
            "cookie policy",
            "godkänn cookies",
            "accept all cookies",
        ]
        if any(ind in text_lower for ind in cookie_indicators):
            # Verify banner is actually visible
            banner_selectors = [
                '[data-cf-action="accept"]',
                '.cookie-banner',
                '#cookie-banner',
                '.consent-banner',
                '[class*="cookie"]',
            ]
            for sel in banner_selectors:
                elem = await page.query_selector(sel)
                if elem and await elem.is_visible():
                    return BlockReason.COOKIE_BANNER
        
        # Check for rate limiting (second priority - need to wait)
        rate_limit_indicators = [
            "rate limit",
            "too many requests",
            "429",
            "för många förfrågningar",
            "vänta en stund",
            "try again later",
        ]
        if any(ind in text_lower for ind in rate_limit_indicators):
            return BlockReason.RATE_LIMITED
        
        # Check for CAPTCHA (third priority - need user intervention or wait)
        captcha_indicators = [
            "human visitor",
            "captcha",
            "verify you are human",
            "robot",
            "inte en robot",
            "bekräfta att du",
            "recaptcha",
            "hcaptcha",
        ]
        if any(ind in text_lower for ind in captcha_indicators):
            return BlockReason.CAPTCHA
        
        # Check for access denied (might need re-login)
        access_indicators = [
            "access denied",
            "åtkomst nekad",
            "forbidden",
            "403",
            "behörighet saknas",
            "inte behörig",
        ]
        if any(ind in text_lower for ind in access_indicators):
            return BlockReason.ACCESS_DENIED
        
        return BlockReason.NONE
        
    except Exception as e:
        print(f"    [DETECT ERROR] {e}")
        return BlockReason.UNKNOWN


async def handle_cookie_banner(page, wait_after: int = 3) -> bool:
    """
    Handle cookie banner if present.
    
    Args:
        page: Playwright page object.
        wait_after: Seconds to wait after clicking.
    
    Returns:
        True if banner was found and clicked, False otherwise.
    """
    cookie_selectors = [
        'button[data-cf-action="accept"]',
        'button:has-text("Acceptera")',
        'button:has-text("Godkänn")',
        'button:has-text("Accept")',
        '.cf-btn-accept',
        '#accept-cookies',
        'button:has-text("OK")',
        'button:has-text("Jag förstår")',
        '[data-action="accept"]',
    ]
    
    for selector in cookie_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                print(f"    🍪 Cookie-banner hittad, klickar...")
                await btn.click()
                await asyncio.sleep(wait_after)
                return True
        except Exception:
            continue
    
    return False


async def get_cookies_from_chrome(cookie_wait: int = 10) -> dict:
    """
    Connect to Chrome via CDP and extract cookies.
    Handles cookie banner, CAPTCHA, and rate limiting automatically.
    
    Args:
        cookie_wait: Seconds to wait after clicking cookie banner.
    
    Returns:
        Dictionary of cookies for bolagsverket.se domain.
    """
    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            except Exception as e:
                print(f"    ❌ Kunde inte ansluta till Chrome på port 9222!")
                print(f"    Kontrollera att:")
                print(f"      1. Chrome körs med --remote-debugging-port=9222")
                print(f"      2. Ingen annan process använder port 9222")
                print(f"      3. Du inte har flera Chrome-instanser igång")
                raise ConnectionError(f"Chrome CDP connection failed: {e}")
            
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
            
            # Make sure we're on the right site
            if "poit.bolagsverket.se" not in page.url:
                await page.goto(f"{BASE_URL}/poit-app/", wait_until="domcontentloaded")
                await asyncio.sleep(3)
            
            # Detect what's blocking us (if anything)
            block_reason = await detect_block_reason(page)
            
            if block_reason == BlockReason.COOKIE_BANNER:
                print(f"    🍪 Cookie-banner upptäckt")
                if await handle_cookie_banner(page, wait_after=cookie_wait):
                    print(f"    ✓ Cookie-banner hanterad")
                    # Re-check after handling
                    block_reason = await detect_block_reason(page)
            
            if block_reason == BlockReason.RATE_LIMITED:
                print(f"    ⏱️  RATE LIMITED - Väntar 60s...")
                await asyncio.sleep(60)
                await page.reload()
                await asyncio.sleep(5)
                block_reason = await detect_block_reason(page)
            
            if block_reason == BlockReason.CAPTCHA:
                print(f"    🤖 CAPTCHA upptäckt")
                await handle_captcha_backoff(page, context)
            
            if block_reason == BlockReason.ACCESS_DENIED:
                print(f"    🚫 ÅTKOMST NEKAD - Du kan behöva logga in igen")
                print(f"    Öppna Chrome och navigera till sajten manuellt.")
            
            # Get all cookies
            cookies = await context.cookies()
            cookie_dict = {}
            for c in cookies:
                if "bolagsverket" in c.get("domain", ""):
                    cookie_dict[c["name"]] = c["value"]
            
            return cookie_dict
            
    except ConnectionError:
        raise
    except Exception as e:
        print(f"    [COOKIE ERROR] {e}")
        return {}


async def detect_captcha(page) -> bool:
    """Check if page shows a CAPTCHA challenge."""
    try:
        text = await page.inner_text("body")
        text_lower = text.lower()
        captcha_indicators = [
            "human visitor",
            "captcha",
            "verify you are human",
            "robot",
            "blocked",
            "access denied",
            "rate limit",
        ]
        return any(indicator in text_lower for indicator in captcha_indicators)
    except Exception:
        return False


async def handle_captcha_backoff(page, context) -> bool:
    """
    Handle CAPTCHA with exponential backoff.
    Returns True if user resolved CAPTCHA, False to abort.
    """
    global _captcha_backoff_seconds, _captcha_count
    
    _captcha_count += 1
    
    # Exponential backoff: 30s, 60s, 120s, 240s...
    if _captcha_backoff_seconds == 0:
        _captcha_backoff_seconds = 30
    else:
        _captcha_backoff_seconds = min(_captcha_backoff_seconds * 2, 300)  # Max 5 min
    
    print(f"\n    ⚠️  CAPTCHA UPPTÄCKT! (gång {_captcha_count})")
    print(f"    ╔════════════════════════════════════════════════════╗")
    print(f"    ║  Bolagsverket kräver verifiering.                  ║")
    print(f"    ║                                                    ║")
    print(f"    ║  Alternativ:                                       ║")
    print(f"    ║  1. Lös CAPTCHA i Chrome-fönstret                  ║")
    print(f"    ║  2. Vänta {_captcha_backoff_seconds:3}s (automatisk backoff)               ║")
    print(f"    ║                                                    ║")
    print(f"    ║  Tryck ENTER när du löst CAPTCHA, eller vänta...   ║")
    print(f"    ╚════════════════════════════════════════════════════╝")
    
    # Wait with countdown, but allow user to press Enter to continue
    import sys
    import select
    
    for remaining in range(_captcha_backoff_seconds, 0, -1):
        print(f"\r    Väntar... {remaining:3}s (tryck ENTER om löst) ", end="", flush=True)
        await asyncio.sleep(1)
        
        # Check if CAPTCHA is gone (user solved it)
        if not await detect_captcha(page):
            print(f"\n    ✅ CAPTCHA löst! Fortsätter...")
            _captcha_backoff_seconds = max(30, _captcha_backoff_seconds // 2)  # Reduce backoff
            return True
    
    print(f"\n    Backoff klar. Testar igen...")
    return True


async def scrape_single_page(
    context, 
    kung_id: str, 
    output_folder: Path, 
    wait_range: tuple
) -> dict:
    """
    Scrape a single kungörelse page.
    
    Args:
        context: Playwright browser context.
        kung_id: Kungörelse ID (e.g., "K966433/25").
        output_folder: Path to save output files.
        wait_range: Tuple of (min, max) seconds to wait for page load.
    
    Returns:
        Result dictionary with 'id', 'success', and optionally 'chars' or 'error'.
    """
    global _captcha_backoff_seconds
    
    normalized_id = kung_id.replace("/", "-")
    url = f"{BASE_URL}/poit-app/kungorelse/{normalized_id}"
    result = {"id": kung_id, "success": False, "block_reason": None}
    
    page = await context.new_page()
    
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # VIKTIGT: Vänta 4-5 sekunder FÖRST för att simulera mänskligt beteende
        # och låta Bolagsverkets JavaScript ladda klart
        initial_wait = random.uniform(4.0, 5.5)
        await asyncio.sleep(initial_wait)
        
        # Check what's blocking us (more specific than just CAPTCHA)
        block_reason = await detect_block_reason(page)
        
        # Handle different block types
        if block_reason == BlockReason.COOKIE_BANNER:
            if await handle_cookie_banner(page, wait_after=3):
                block_reason = await detect_block_reason(page)
        
        if block_reason == BlockReason.RATE_LIMITED:
            result["error"] = "⏱️ Rate limited"
            result["block_reason"] = "rate_limited"
            # Don't retry immediately - signal to caller to slow down
            return result
        
        if block_reason == BlockReason.CAPTCHA:
            await handle_captcha_backoff(page, context)
            # Retry the page after backoff
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(initial_wait)
            block_reason = await detect_block_reason(page)
        
        if block_reason == BlockReason.ACCESS_DENIED:
            result["error"] = "🚫 Åtkomst nekad"
            result["block_reason"] = "access_denied"
            return result
        
        # Extra wait for JavaScript to render content
        wait_time = random.uniform(*wait_range)
        await asyncio.sleep(wait_time)
        
        # Handle "enskild" intermediate page (redirect page)
        max_retries = 3
        for retry in range(max_retries):
            block_reason = await detect_block_reason(page)
            
            if block_reason == BlockReason.ENSKILD_PAGE:
                # Wait for potential auto-redirect
                await asyncio.sleep(random.uniform(2, 3))
                
                # Re-check if still on enskild
                if "/enskild/" in page.url:
                    # Try clicking through to actual kungörelse
                    link = await page.query_selector('a[href*="/kungorelse/K"]')
                    if not link:
                        link = await page.query_selector('a.btn-link[href*="/kungorelse"]')
                    if not link:
                        link = await page.query_selector('a[title="Visa kungörelse"]')
                    
                    if link:
                        await link.click()
                        await asyncio.sleep(random.uniform(*wait_range))
                    else:
                        # No link found - might be cookie banner blocking
                        inner_block = await detect_block_reason(page)
                        if inner_block == BlockReason.COOKIE_BANNER:
                            print(f"      🍪 Cookie-banner blockerar på enskild-sida")
                            await handle_cookie_banner(page, wait_after=3)
                            continue  # Retry finding link
                        else:
                            result["error"] = f"Enskild utan länk (block: {inner_block.value})"
                            result["block_reason"] = "enskild_no_link"
                            return result
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
    wait_range: tuple = (8, 12),
    between_range: tuple = (3, 6)
) -> list:
    """
    Scrape multiple kungörelse pages.
    
    Args:
        kung_ids: List of kungörelse IDs to scrape.
        output_folder: Path to save output files.
        parallel: Number of parallel tabs (1 = sequential, safest).
        wait_range: Tuple of (min, max) seconds to wait per page.
        between_range: Tuple of (min, max) seconds between batches.
    
    Returns:
        List of result dictionaries for each kungörelse.
    """
    results = []
    total = len(kung_ids)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]
            
            for i in range(0, total, parallel):
                batch = kung_ids[i:i + parallel]
                batch_num = i // parallel + 1
                total_batches = (total + parallel - 1) // parallel
                print(f"\n    Batch {batch_num}/{total_batches}: {len(batch)} sida(or)...")
                
                # Staggered start for parallel tabs
                async def scrape_delayed(kid, delay):
                    await asyncio.sleep(delay)
                    return await scrape_single_page(context, kid, output_folder, wait_range)
                
                tasks = [scrape_delayed(kid, j * 1.5) for j, kid in enumerate(batch)]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for kid, r in zip(batch, batch_results):
                    if isinstance(r, Exception):
                        print(f"      ✗ {kid}: Error - {str(r)[:30]}")
                        results.append({"id": kid, "success": False, "error": str(r)})
                    else:
                        status = "✓" if r["success"] else "✗"
                        if r["success"]:
                            info = f"{r.get('chars', 0)} tecken"
                        else:
                            info = r.get("error", "Okänt fel")
                        print(f"      {status} {kid}: {info}")
                        results.append(r)
                
                # Wait between batches (unless this is the last batch)
                if i + parallel < total:
                    wait = random.uniform(*between_range)
                    print(f"    Väntar {wait:.1f}s...")
                    await asyncio.sleep(wait)
                    
    except Exception as e:
        print(f"    [SCRAPER ERROR] {e}")
    
    return results

