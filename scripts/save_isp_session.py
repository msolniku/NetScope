from playwright.sync_api import sync_playwright

from config.settings import (
    CHROME_PATH,
    ISP_LOGIN_URL,
    ISP_STATE_FILE,
    VIEWPORT,
)


def main() -> None:
    ISP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, executable_path=CHROME_PATH)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()

        page.goto(ISP_LOGIN_URL, wait_until="networkidle", timeout=60_000)

        print(">>> الان دستی لاگین کن (نام کاربری، رمز، CAPTCHA).")
        print(">>> بعد از اینکه وارد پنل شدی، در ترمینال Enter بزن.")
        input()

        ctx.storage_state(path=str(ISP_STATE_FILE))
        print(f"نشست ذخیره شد: {ISP_STATE_FILE}")
        browser.close()


if __name__ == "__main__":
    main()