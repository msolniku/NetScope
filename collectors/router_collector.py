import time
from datetime import datetime

from playwright.sync_api import sync_playwright, Error as PlaywrightError

from config.settings import (
    ROUTER_URL,
    ROUTER_USERNAME,
    ROUTER_PASSWORD,
    CHROME_PATH,
    VIEWPORT,
    PAGE_SETTLE_MS,
    SCREENSHOT_DIR,
    DEFAULT_INTERVAL_SEC,
)
from collectors.ocr import process_image
from collectors.storage import save_snapshot


# --------------------------------------------------
# Validation
# --------------------------------------------------

def validate_config() -> None:
    missing = []
    if not ROUTER_USERNAME:
        missing.append("ROUTER_USERNAME")
    if not ROUTER_PASSWORD:
        missing.append("ROUTER_PASSWORD")

    if missing:
        raise SystemExit(
            f"Missing environment variables in .env: {', '.join(missing)}"
        )


# --------------------------------------------------
# Page helpers
# --------------------------------------------------

def load_router_page(page) -> None:
    page.goto(ROUTER_URL, wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(PAGE_SETTLE_MS)


def reload_router_page(page) -> None:
    page.reload(wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(PAGE_SETTLE_MS)


# --------------------------------------------------
# One scan cycle
# --------------------------------------------------

def capture_once(page) -> None:
    """Take one screenshot, run OCR, save snapshot."""
    timestamp = datetime.now()
    screenshot_path = SCREENSHOT_DIR / f"{timestamp:%Y-%m-%d_%H-%M-%S}.png"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"\nScreenshot saved: {screenshot_path}")
    except PlaywrightError as e:
        print(f"Screenshot failed: {e}")
        return

    try:
        records = process_image(screenshot_path)
    except Exception as e:
        print(f"OCR failed: {e}")
        return

    if records:
        save_snapshot(records)
    else:
        print("No valid users detected. Snapshot was not saved.")


# --------------------------------------------------
# Public API — bounded collection loop
# --------------------------------------------------

def collect_for_duration(hours: float, interval: int, stop_event=None) -> None:
    """
    Collect router snapshots for `hours` hours, taking one
    snapshot every `interval` seconds.

    If `stop_event` (a threading.Event) is provided and becomes set,
    the loop exits cleanly at the next check.
    """
    validate_config()
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + hours * 3600

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            executable_path=CHROME_PATH,
        )
        try:
            context = browser.new_context(
                http_credentials={
                    "username": ROUTER_USERNAME,
                    "password": ROUTER_PASSWORD,
                },
                viewport=VIEWPORT,
            )
            page = context.new_page()

            print(f"Connecting to router: {ROUTER_URL}")
            load_router_page(page)
            print("Connected to router.")

            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    print("Stop requested before scan.")
                    break

                capture_once(page)

                remaining = deadline - time.time()
                if remaining <= 0:
                    break

                wait = min(interval, remaining)
                print(f"\nWaiting {int(wait)}s until next scan...")

                # Sleep in small chunks so stop_event is honored quickly
                wait_until = time.time() + wait
                while time.time() < wait_until:
                    if stop_event is not None and stop_event.is_set():
                        print("Stop requested during wait.")
                        break
                    time.sleep(min(1.0, wait_until - time.time()))

                if stop_event is not None and stop_event.is_set():
                    break

                if time.time() >= deadline:
                    break

                try:
                    print("Reloading router page for fresh data...")
                    reload_router_page(page)
                except PlaywrightError as e:
                    print(f"Reload failed: {e}")

        except KeyboardInterrupt:
            print("\nStopped by user.")
        except PlaywrightError as e:
            print(f"Playwright error: {e}")
        finally:
            browser.close()
            print("Browser closed.")


# --------------------------------------------------
# Standalone entry point
# --------------------------------------------------

if __name__ == "__main__":
    collect_for_duration(hours=1.0, interval=DEFAULT_INTERVAL_SEC)