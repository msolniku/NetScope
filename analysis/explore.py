import json

from config.settings import DATASET_FILE


# --------------------------------------------------
# I/O
# --------------------------------------------------

def load_dataset() -> list[dict]:
    if not DATASET_FILE.exists():
        return []
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------
# Reporting
# --------------------------------------------------

def print_overview(samples: list[dict]) -> None:
    print("\n========== OVERVIEW ==========\n")
    print(f"Total samples:  {len(samples)}")

    usable = [s for s in samples if s["router_delta_count"] > 0]
    print(f"Usable samples: {len(usable)} (have router data)")
    print(f"Empty samples:  {len(samples) - len(usable)} (no router data)")

    if usable:
        total_gb = sum(s["isp_usage_gb"] or 0 for s in usable)
        total_tx = sum(s["total_delta_tx"] for s in usable)
        total_rx = sum(s["total_delta_rx"] for s in usable)
        print(f"\nTotal ISP usage: {total_gb:.2f} GB")
        print(f"Total Δtx:       {total_tx:,}")
        print(f"Total Δrx:       {total_rx:,}")


def print_table(samples: list[dict]) -> None:
    print("\n========== SAMPLES ==========\n")
    header = (
        f"{'From':<20} {'To':<20} "
        f"{'ISP GB':>8} {'Δtx':>12} {'Δrx':>12} "
        f"{'Deltas':>7} {'Devices':>8}"
    )
    print(header)
    print("-" * len(header))

    for s in samples:
        print(
            f"{s['isp_from'][:19]:<20} "
            f"{s['isp_to'][:19]:<20} "
            f"{s['isp_usage_gb'] or 0:>8.2f} "
            f"{s['total_delta_tx']:>12,} "
            f"{s['total_delta_rx']:>12,} "
            f"{s['router_delta_count']:>7} "
            f"{s['device_count']:>8}"
        )


def print_correlation(samples: list[dict]) -> None:
    usable = [s for s in samples if s["router_delta_count"] > 0]

    if len(usable) < 2:
        print("\n========== CORRELATION ==========")
        print("Need at least 2 usable samples for correlation.")
        return

    try:
        import numpy as np
    except ImportError:
        print("\n(install numpy for correlation: pip install numpy)")
        return

    y          = np.array([s["isp_usage_gb"] or 0 for s in usable])
    total_tx   = np.array([s["total_delta_tx"] for s in usable])
    total_rx   = np.array([s["total_delta_rx"] for s in usable])
    total_pkts = total_tx + total_rx

    print("\n========== CORRELATION ==========\n")
    print(f"Samples used: {len(usable)}")

    def corr(a, b):
        if a.std() == 0 or b.std() == 0:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

    print(f"  ISP_usage vs Δtx:       {corr(total_tx, y):+.4f}")
    print(f"  ISP_usage vs Δrx:       {corr(total_rx, y):+.4f}")
    print(f"  ISP_usage vs Δtx+Δrx:   {corr(total_pkts, y):+.4f}")
    print("\n  (1.0 = perfect positive, 0 = none, -1.0 = perfect negative)")


def print_device_summary(samples: list[dict]) -> None:
    usable = [s for s in samples if s["router_delta_count"] > 0]
    if not usable:
        return

    agg: dict[str, dict] = {}
    for s in usable:
        for d in s["devices"]:
            mac = d["mac"]
            if mac not in agg:
                agg[mac] = {"mac": mac, "samples": 0,
                            "total_tx": 0, "total_rx": 0}
            agg[mac]["samples"]  += d["samples"]
            agg[mac]["total_tx"] += d["delta_tx_sum"]
            agg[mac]["total_rx"] += d["delta_rx_sum"]

    print("\n========== PER-DEVICE TOTALS ==========\n")
    print(f"{'MAC':<20} {'Samples':>8} {'Total Δtx':>14} {'Total Δrx':>14}")
    print("-" * 60)

    for mac, a in sorted(agg.items(), key=lambda x: -x[1]["total_tx"]):
        print(
            f"{mac:<20} {a['samples']:>8} "
            f"{a['total_tx']:>14,} {a['total_rx']:>14,}"
        )


def print_diagnostics(samples: list[dict]) -> None:
    print("\n========== DIAGNOSTICS ==========\n")

    if not samples:
        print("No samples.")
        return

    no_data = [s for s in samples if s["router_delta_count"] == 0]
    if no_data:
        print(f"⚠ {len(no_data)} sample(s) have no router data:")
        for s in no_data:
            print(f"    {s['isp_from']} → {s['isp_to']}")
    else:
        print("✓ All samples have router data.")

    empty_devices = [
        s for s in samples
        if s["router_delta_count"] > 0 and s["device_count"] == 0
    ]
    if empty_devices:
        print(f"⚠ {len(empty_devices)} sample(s) have router data but no devices.")

    total_deltas = sum(s["router_delta_count"] for s in samples)
    if total_deltas < 10:
        print(f"⚠ Only {total_deltas} delta intervals total. "
              "Collect more data before training any model.")
    elif total_deltas < 50:
        print(f"⚠ {total_deltas} delta intervals. "
              "Enough for testing but not for real training.")
    else:
        print(f"✓ {total_deltas} delta intervals. Good for baseline training.")


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main() -> None:
    samples = load_dataset()

    if not samples:
        print(
            "→ No dataset available yet. "
            "Run `python -m analysis.dataset_builder` first."
        )
        raise SystemExit(2)

    print_overview(samples)
    print_table(samples)
    print_correlation(samples)
    print_device_summary(samples)
    print_diagnostics(samples)


if __name__ == "__main__":
    main()