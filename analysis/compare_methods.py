import json
from pathlib import Path

from config.settings import PROJECT_ROOT


ML_FILE = PROJECT_ROOT / "data" / "monthly_report.json"
RATIO_FILE = PROJECT_ROOT / "data" / "monthly_report_ratio.json"


def load(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ml = load(ML_FILE)
    ratio = load(RATIO_FILE)

    if not ml:
        print("→ Run `python -m analysis.monthly_report` first.")
        raise SystemExit(2)
    if not ratio:
        print("→ Run `python -m analysis.monthly_report_ratio` first.")
        raise SystemExit(2)

    ml_by_mac = {x["mac"]: x for x in ml["per_mac"]}
    ratio_by_mac = {x["mac"]: x for x in ratio["per_mac"]}

    all_macs = sorted(
        set(ml_by_mac) | set(ratio_by_mac),
        key=lambda m: -ml_by_mac.get(m, {}).get("usage_gb", 0),
    )

    print("\n" + "=" * 100)
    print("🔬 مقایسه دو روش: ML vs نسبت پکت")
    print("=" * 100)
    print(f"بازه: {ml['from']} → {ml['to']}")
    print(f"پنجره‌ها: {ml['total_windows']}")
    print(f"جمع کل ISP usage: {ml['total_usage_gb']:.4f} GB")
    print()

    header = (
        f"{'MAC':<20} "
        f"{'ML (GB)':>12} "
        f"{'Ratio (GB)':>12} "
        f"{'Diff (GB)':>12} "
        f"{'Diff (%)':>10} "
        f"{'ML share':>10} "
        f"{'Ratio share':>12}"
    )
    print(header)
    print("-" * len(header))

    for mac in all_macs:
        m = ml_by_mac.get(mac, {})
        r = ratio_by_mac.get(mac, {})

        ml_gb = m.get("usage_gb", 0.0)
        r_gb = r.get("usage_gb", 0.0)

        diff = ml_gb - r_gb
        pct = (diff / r_gb * 100) if r_gb > 0 else float("inf")

        ml_share = m.get("share", 0.0)
        r_share = r.get("share", 0.0)

        print(
            f"{mac:<20} "
            f"{ml_gb:>12.4f} "
            f"{r_gb:>12.4f} "
            f"{diff:>+12.4f} "
            f"{pct:>+9.2f}% "
            f"{ml_share*100:>9.2f}% "
            f"{r_share*100:>11.2f}%"
        )

    print("-" * len(header))
    print(
        f"{'جمع کل':<20} "
        f"{ml['total_usage_gb']:>12.4f} "
        f"{ratio['total_usage_gb']:>12.4f}"
    )
    print()

    # Biggest differences
    print("─── بزرگ‌ترین اختلاف‌ها ───")
    diffs = []
    for mac in all_macs:
        m = ml_by_mac.get(mac, {}).get("usage_gb", 0.0)
        r = ratio_by_mac.get(mac, {}).get("usage_gb", 0.0)
        diffs.append((mac, m, r, m - r))
    diffs.sort(key=lambda x: -abs(x[3]))

    for mac, m, r, d in diffs[:5]:
        print(f"  {mac}: ML={m:.4f}  Ratio={r:.4f}  Diff={d:+.4f} GB")
    print()


if __name__ == "__main__":
    main()