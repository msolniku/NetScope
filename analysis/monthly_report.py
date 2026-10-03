import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from config.settings import DATASET_FILE, PROJECT_ROOT
from ml.scoring import predict_devices


MODEL_FILE = PROJECT_ROOT / "data" / "model.json"
REPORT_FILE = PROJECT_ROOT / "data" / "monthly_report.json"


# --------------------------------------------------
# I/O
# --------------------------------------------------

def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"Saved: {path}")


# --------------------------------------------------
# Report
# --------------------------------------------------

def build_report(dataset, model):
    """
    Only uses windows with router data.
    Builds:
      - per_mac_daily:  {mac: {date: usage_gb}}
      - per_mac_total:  cumulative per MAC
      - daily_totals:   totals per day
      - all_dates:      sorted list of dates
      - all_macs:       sorted list of macs
    """

    model_usage = model["usage"]
    model_ded   = model["deducted"]

    usable = [s for s in dataset if s.get("router_delta_count", 0) > 0]

    if not usable:
        return {"error": "No usable samples (all ISP windows lack router data)."}

    usable.sort(key=lambda s: s["isp_to"])

    # {mac: {date: {"usage": x, "deducted": y}}}
    per_mac_daily = defaultdict(lambda: defaultdict(lambda: {"usage": 0.0, "deducted": 0.0}))

    # {date: {"usage": x, "deducted": y}}
    daily_totals = defaultdict(lambda: {"usage": 0.0, "deducted": 0.0})

    # {mac: {"usage": total, "deducted": total}}
    per_mac_total = defaultdict(lambda: {"usage": 0.0, "deducted": 0.0, "windows": 0})

    total_usage = 0.0
    total_ded = 0.0

    for s in usable:
        usage = s.get("isp_usage_gb") or 0.0
        deducted = s.get("isp_deducted_gb") or 0.0

        total_usage += usage
        total_ded += deducted

        date_key = s["isp_from"][:10]

        daily_totals[date_key]["usage"] += usage
        daily_totals[date_key]["deducted"] += deducted

        # One call per window so per-device shares add up to the window total.
        usage_by_mac = predict_devices(s, model_usage)
        ded_by_mac = predict_devices(s, model_ded)

        for d in s["devices"]:
            mac = d["mac"]
            u = usage_by_mac.get(mac, 0.0)
            dd = ded_by_mac.get(mac, 0.0)

            per_mac_daily[mac][date_key]["usage"] += u
            per_mac_daily[mac][date_key]["deducted"] += dd

            per_mac_total[mac]["usage"] += u
            per_mac_total[mac]["deducted"] += dd
            per_mac_total[mac]["windows"] += 1

    all_dates = sorted(daily_totals.keys())
    all_macs = sorted(per_mac_total.keys(), key=lambda m: -per_mac_total[m]["usage"])

    # Build serializable structures
    per_mac_list = []
    for mac in all_macs:
        t = per_mac_total[mac]
        share = (t["usage"] / total_usage) if total_usage > 0 else 0.0
        per_mac_list.append({
            "mac": mac,
            "usage_gb": round(t["usage"], 4),
            "deducted_gb": round(t["deducted"], 4),
            "share": round(share, 4),
            "windows": t["windows"],
            "daily": {
                date: {
                    "usage_gb": round(per_mac_daily[mac][date]["usage"], 4),
                    "deducted_gb": round(per_mac_daily[mac][date]["deducted"], 4),
                }
                for date in all_dates
            },
        })

    daily_totals_list = [
        {
            "date": date,
            "usage_gb": round(daily_totals[date]["usage"], 4),
            "deducted_gb": round(daily_totals[date]["deducted"], 4),
        }
        for date in all_dates
    ]

    return {
        "from": usable[0]["isp_from"],
        "to": usable[-1]["isp_to"],
        "total_windows": len(usable),
        "total_usage_gb": round(total_usage, 4),
        "total_deducted_gb": round(total_ded, 4),
        "all_dates": all_dates,
        "per_mac": per_mac_list,
        "daily_totals": daily_totals_list,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# --------------------------------------------------
# Printing
# --------------------------------------------------

def print_report(r):
    if "error" in r:
        print(f"\n→ {r['error']}\n")
        return

    dates = r["all_dates"]
    per_mac = r["per_mac"]

    print("\n" + "=" * 100)
    print("📊 گزارش مصرف — فقط بر اساس پنجره‌های دارای داده روتر")
    print("=" * 100)
    print(f"از:      {r['from']}")
    print(f"تا:      {r['to']}")
    print(f"پنجره‌ها: {r['total_windows']}  (همه دارای داده روتر)")
    print(f"روزها:   {len(dates)}")
    print()

    # ==================================================
    # Table 1: DAILY per MAC (matrix)
    # ==================================================
    print("─" * 100)
    print("📅 جدول ۱ — مصرف روزانهٔ هر MAC")
    print("─" * 100)

    # Header: MAC | date1 | date2 | ... | total
    short_dates = [d[5:] for d in dates]  # MM-DD

    header = f"{'MAC':<20}"
    for sd in short_dates:
        header += f" {sd:>9}"
    header += f" {'TOTAL':>10} {'Share':>7}"
    print(header)
    print("-" * len(header))

    for item in per_mac:
        row = f"{item['mac']:<20}"
        for d in dates:
            val = item["daily"].get(d, {}).get("usage_gb", 0.0)
            row += f" {val:>9.3f}"
        row += f" {item['usage_gb']:>10.3f} {item['share']*100:>6.1f}%"
        print(row)

    # Totals row
    totals_row = f"{'جمع کل':<20}"
    for d in dates:
        day_total = next((x["usage_gb"] for x in r["daily_totals"] if x["date"] == d), 0)
        totals_row += f" {day_total:>9.3f}"
    totals_row += f" {r['total_usage_gb']:>10.3f} {'100%':>7}"
    print("-" * len(header))
    print(totals_row)
    print()

    # ==================================================
    # Table 2: CUMULATIVE per MAC (running total)
    # ==================================================
    print("─" * 100)
    print("📈 جدول ۲ — مصرف انباشته (جمع تا هر روز)")
    print("─" * 100)

    header = f"{'MAC':<20}"
    for sd in short_dates:
        header += f" {sd:>9}"
    header += f" {'TOTAL':>10} {'Share':>7}"
    print(header)
    print("-" * len(header))

    for item in per_mac:
        row = f"{item['mac']:<20}"
        running = 0.0
        for d in dates:
            running += item["daily"].get(d, {}).get("usage_gb", 0.0)
            row += f" {running:>9.3f}"
        row += f" {item['usage_gb']:>10.3f} {item['share']*100:>6.1f}%"
        print(row)

    # Totals row (cumulative)
    totals_row = f"{'جمع کل':<20}"
    running_total = 0.0
    for d in dates:
        day_total = next((x["usage_gb"] for x in r["daily_totals"] if x["date"] == d), 0)
        running_total += day_total
        totals_row += f" {running_total:>9.3f}"
    totals_row += f" {r['total_usage_gb']:>10.3f} {'100%':>7}"
    print("-" * len(header))
    print(totals_row)
    print()

    # ==================================================
    # Table 3: Daily totals (usage + deducted)
    # ==================================================
    print("─" * 100)
    print("📋 جدول ۳ — جمع روزانه (usage / deducted)")
    print("─" * 100)
    header3 = f"{'تاریخ':<14} {'Usage (GB)':>12} {'Deducted (GB)':>15}"
    print(header3)
    print("-" * len(header3))
    for d in r["daily_totals"]:
        print(
            f"{d['date']:<14} "
            f"{d['usage_gb']:>12.3f} "
            f"{d['deducted_gb']:>15.3f}"
        )
    print("-" * len(header3))
    print(
        f"{'جمع کل':<14} "
        f"{r['total_usage_gb']:>12.3f} "
        f"{r['total_deducted_gb']:>15.3f}"
    )
    print()


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="monthly_report")
    parser.parse_args()

    dataset = load_json(DATASET_FILE) or []
    model = load_json(MODEL_FILE)

    if not model:
        print("→ No model. Run `python -m ml.train` first.")
        raise SystemExit(2)
    if not dataset:
        print("→ No dataset. Run `python -m analysis.dataset_builder` first.")
        raise SystemExit(2)

    report = build_report(dataset, model)
    print_report(report)
    save_json(REPORT_FILE, report)


if __name__ == "__main__":
    main()