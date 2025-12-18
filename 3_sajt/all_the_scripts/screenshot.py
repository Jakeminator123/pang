"""
Screenshot functionality for capturing preview site images.
Uses Playwright for headless browser screenshots.
"""

from pathlib import Path


async def take_screenshot(
    url: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
    timeout: int = 30,
) -> bool:
    """
    Take a screenshot of a website URL.

    Args:
        url: URL to screenshot
        output_path: Path to save screenshot (PNG)
        width: Viewport width (default: 1280)
        height: Viewport height (default: 720)
        timeout: Timeout in seconds (default: 30)

    Returns:
        True if successful, False otherwise
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,  # Higher quality
            )
            page = await context.new_page()

            # Navigate to URL
            await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)

            # Wait longer for page to fully render (images, fonts, animations)
            await page.wait_for_timeout(8000)

            # Take screenshot
            await page.screenshot(path=str(output_path), full_page=False)

            await browser.close()
            return True

    except ImportError:
        # Fallback: Try using requests + PIL if Playwright not available
        try:
            import httpx

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    # This won't work for JS-rendered sites, but better than nothing
                    # For now, just return False and suggest Playwright
                    return False
        except:
            pass

        print(
            "⚠️  Playwright not installed. Install with: pip install playwright && playwright install chromium"
        )
        return False
    except Exception as e:
        print(f"⚠️  Screenshot failed: {e}")
        return False


async def take_screenshot_simple(url: str, output_path: Path) -> bool:
    """Simple wrapper for taking screenshots."""
    return await take_screenshot(url, output_path)
