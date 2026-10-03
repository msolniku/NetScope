import json
import re
from datetime import datetime
from pathlib import Path

import jdatetime
from playwright.sync_api import sync_playwright, Error as PlaywrightError

from config.settings import (
    CHROME_PATH,
    ISP_CDR_URL,
    ISP_STATE_FILE,
    ISP_FILE,
    VIEWPORT,
)


# --------------------------------------------------
# Persian number helpers
# --------------------------------------------------

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS  = "٠١٢٣٤٥٦٧٨٩"


def to_latin_digits(text: str) -> str:
    result = []
    for ch in text:
        if ch in PERSIAN_DIGITS:
            result.append(str(PERSIAN_DIGITS.index(ch)))
        elif ch in ARABIC_DIGITS:
            result.append(str(ARABIC_DIGITS.index(ch)))
        else:
            result.append(ch)
    return "".join(result)


def parse_usage_gb(text: str) -> float | None:
    """Parse '3.12 گیگابایت' → 3.12 (GB float)."""
    text = to_latin_digits(text).strip()
    m = re.match(r"([\d.]+)\s*(\S+)", text)
    if not m:
        return None

    value = float(m.group(1))
    unit = m.group(2)

    if "گیگا" in unit:
        return round(value, 4)
    if "مگا" in unit:
        return round(value / 1024, 4)
    if "کیلو" in unit:
        return round(value / (1024 * 1024), 4)
    return round(value, 4)


def parse_duration_seconds(text: str) -> int | None:
    """Parse '2 ساعت, 32 دقیقه, 52 ثانیه' → total seconds."""
    text = to_latin_digits(text)

    days = hours = minutes = seconds = 0

    m = re.search(r"(\d+)\s*روز", text)
    if m:
        days = int(m.group(1))
    m = re.search(r"(\d+)\s*ساعت", text)
    if m:
        hours = int(m.group(1))
    m = re.search(r"(\d+)\s*دقیقه", text)
    if m:
        minutes = int(m.group(1))
    m = re.search(r"(\d+)\s*ثانیه", text)
    if m:
        seconds = int(m.group(1))

    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def parse_jalali_datetime(text: str) -> str | None:
    """'1405/7/1 06:18:39' → '2026-09-22T06:18:39'."""
    text = to_latin_digits(text).strip()

    m = re.match(
        r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})",
        text,
    )
    if not m:
        return None

    jy, jm, jd, h, mi, s = map(int, m.groups())

    try:
        g = jdatetime.date(jy, jm, jd).togregorian()
    except ValueError:
        return None

    return (
        f"{g.year:04d}-{g.month:02d}-{g.day:02d}"
        f"T{h:02d}:{mi:02d}:{s:02d}"
    )


# --------------------------------------------------
# Storage
# --------------------------------------------------

def load_existing() -> list[dict]:
    if not ISP_FILE.exists():
        return []
    with open(ISP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_all(records: list[dict]) -> None:
    ISP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ISP_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=4)
    print(f"ISP usage saved: {ISP_FILE} ({len(records)} record(s))")


def _overlaps(a: dict, b: dict) -> bool:
    return a["from"] < b["to"] and b["from"] < a["to"]


def merge_records(old: list[dict], new: list[dict]) -> list[dict]:
    if not new:
        return sorted(old, key=lambda r: r["from"])

    deduped_new = {}
    for r in new:
        deduped_new[(r["from"], r["to"])] = r
    new = list(deduped_new.values())
    new_keys = {(r["from"], r["to"]) for r in new}

    kept = []
    dropped_stale = 0

    for old_rec in old:
        key = (old_rec["from"], old_rec["to"])
        if key in new_keys:
            continue
        if any(_overlaps(old_rec, nr) for nr in new):
            dropped_stale += 1
            continue
        kept.append(old_rec)

    kept.extend(new)

    if dropped_stale:
        print(f"Dropped {dropped_stale} stale/overlapping ISP record(s).")

    return sorted(kept, key=lambda r: r["from"])


# --------------------------------------------------
# Scrape
# --------------------------------------------------

def scrape_cdr_report(page) -> list[dict]:
    print(f"Opening CDR report: {ISP_CDR_URL}")

    try:
        page.goto(ISP_CDR_URL, wait_until="domcontentloaded", timeout=60_000)
    except PlaywrightError as e:
        raise RuntimeError(
            "صفحهٔ CDR باز نشد (احتمالاً نشست منقضی شده).\n"
            "لطفاً دوباره `python -m scripts.save_isp_session` را اجرا کن.\n"
            f"جزئیات: {e}"
        )

    if "login" in page.url.lower() or "atsso" in page.url.lower():
        raise RuntimeError(
            "نشست منقضی شده. لطفاً دوباره "
            "`python -m scripts.save_isp_session` را اجرا کن."
        )

    try:
        page.wait_for_selector(
            "table:has-text('میزان حجم مصرفی')",
            timeout=15_000,
        )
    except PlaywrightError:
        raise RuntimeError(
            "جدول 'ریز مصرف' ظاهر نشد. "
            "مطمئن شو وارد پنل شده‌ای و صفحه کامل لود شده."
        )

    tables = page.locator("table")
    n = tables.count()
    print(f"Found {n} table(s).")

    target = None
    for i in range(n):
        tbl = tables.nth(i)
        text = tbl.inner_text()
        if "میزان حجم مصرفی" in text and "مدت زمان" in text:
            target = tbl
            print(f"Using table #{i}.")
            break

    if target is None:
        raise RuntimeError("جدول 'ریز مصرف' پیدا نشد.")

    rows = target.locator("tr")
    row_count = rows.count()
    print(f"Table has {row_count} row(s).")

    records = []
    for i in range(row_count):
        cells = rows.nth(i).locator("td")
        if cells.count() < 5:
            continue

        raw_from      = cells.nth(0).inner_text().strip()
        raw_to        = cells.nth(1).inner_text().strip()
        raw_usage     = cells.nth(2).inner_text().strip()   # مصرفی
        raw_deducted  = cells.nth(3).inner_text().strip()   # کسر شده
        raw_duration  = cells.nth(4).inner_text().strip()

        parsed_from = parse_jalali_datetime(raw_from)
        parsed_to   = parse_jalali_datetime(raw_to)

        if not parsed_from or not parsed_to:
            continue

        records.append({
            "from": parsed_from,
            "to": parsed_to,
            "usage_gb": parse_usage_gb(raw_usage),
            "deducted_gb": parse_usage_gb(raw_deducted),
            "duration_seconds": parse_duration_seconds(raw_duration),
            "raw_usage": raw_usage,
            "raw_deducted": raw_deducted,
            "raw_duration": raw_duration,
            "collected_at": datetime.now().isoformat(timespec="seconds"),
        })

    return records


# --------------------------------------------------
# Main
# --------------------------------------------------

def run() -> None:
    if not ISP_STATE_FILE.exists():
        raise SystemExit(
            f"فایل نشست پیدا نشد: {ISP_STATE_FILE}\n"
            "اول `python -m scripts.save_isp_session` را اجرا کن."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            executable_path=CHROME_PATH,
        )
        try:
            context = browser.new_context(
                storage_state=str(ISP_STATE_FILE),
                viewport=VIEWPORT,
                locale="fa-IR",
            )
            page = context.new_page()

            new_records = scrape_cdr_report(page)

            print(f"\nExtracted {len(new_records)} record(s).")
            for r in new_records:
                print(
                    f"  {r['from']}  →  {r['to']}  "
                    f"used={r['usage_gb']} GB  "
                    f"deducted={r['deducted_gb']} GB  "
                    f"({r['duration_seconds']}s)"
                )

            old_records = load_existing()
            print(f"\nExisting records before merge: {len(old_records)}")

            merged = merge_records(old_records, new_records)

            print(f"Records after merge: {len(merged)}")

            save_all(merged)

        except PlaywrightError as e:
            print(f"Playwright error: {e}")
        except RuntimeError as e:
            print(f"Error: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    run()