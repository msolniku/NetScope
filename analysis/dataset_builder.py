import json
from datetime import datetime
from pathlib import Path

from config.settings import (
    DELTA_FILE,
    ISP_FILE,
    DATASET_FILE,
    MAX_GAP_FACTOR,
)


# --------------------------------------------------
# I/O
# --------------------------------------------------

def load_json(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"Saved: {path}")


# --------------------------------------------------
# Time helpers
# --------------------------------------------------

def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# --------------------------------------------------
# Dataset building
# --------------------------------------------------

def build_samples(
    deltas: list[dict],
    isp_records: list[dict],
) -> list[dict]:
    samples = []

    for isp in isp_records:
        isp_from = parse_ts(isp["from"])
        isp_to   = parse_ts(isp["to"])

        matching_deltas = []
        for d in deltas:
            if not d.get("reliable", True):
                continue
            d_to = parse_ts(d["to"])
            if isp_from <= d_to <= isp_to:
                matching_deltas.append(d)

        per_mac: dict[str, dict] = {}

        for d in matching_deltas:
            interval = d.get("interval_seconds", 1)

            for dev in d["deltas"]:
                mac = dev["mac"]

                # NOTE: counter_reset deltas are ESTIMATED (see
                # analysis/snapshot_differ.py) rather than measured
                # exactly, but they're no longer dropped — dropping them
                # silently undercounted every device that ever rebooted
                # its wifi radio. They're still tracked separately below
                # (was_counter_reset_count) so this can be audited later.

                gap = dev.get("gap_seconds", interval)
                if gap > interval * MAX_GAP_FACTOR:
                    continue

                if mac not in per_mac:
                    per_mac[mac] = {
                        "mac": mac,
                        "delta_tx_sum": 0,
                        "delta_rx_sum": 0,
                        "samples": 0,
                        "tx_rate_values": [],
                        "power_saving_values": [],
                        "was_absent_count": 0,
                        "counter_reset_count": 0,
                    }

                per_mac[mac]["delta_tx_sum"] += dev["tx_packet_delta"]
                per_mac[mac]["delta_rx_sum"] += dev["rx_packet_delta"]
                per_mac[mac]["samples"] += 1

                if dev.get("was_absent"):
                    per_mac[mac]["was_absent_count"] += 1

                if dev.get("counter_reset"):
                    per_mac[mac]["counter_reset_count"] += 1

                if dev["tx_rate"] is not None:
                    per_mac[mac]["tx_rate_values"].append(dev["tx_rate"])

                per_mac[mac]["power_saving_values"].append(dev["power_saving"])

        devices = []
        for mac, agg in per_mac.items():
            rates = agg["tx_rate_values"]
            avg_rate = round(sum(rates) / len(rates), 2) if rates else None

            ps = agg["power_saving_values"]
            ps_yes = sum(1 for x in ps if x == "yes")
            ps_ratio = round(ps_yes / len(ps), 2) if ps else None

            presence_ratio = (
                round(agg["samples"] / len(matching_deltas), 2)
                if matching_deltas else None
            )

            devices.append({
                "mac": mac,
                "delta_tx_sum": agg["delta_tx_sum"],
                "delta_rx_sum": agg["delta_rx_sum"],
                "delta_total": agg["delta_tx_sum"] + agg["delta_rx_sum"],
                "samples": agg["samples"],
                "presence_ratio": presence_ratio,
                "avg_tx_rate": avg_rate,
                "power_saving_ratio": ps_ratio,
                "was_absent_count": agg["was_absent_count"],
                "counter_reset_count": agg["counter_reset_count"],
            })

        devices.sort(key=lambda x: x["delta_total"], reverse=True)

        # --- ISP fields ---
        # `deducted_gb` is left as None when the ISP record doesn't have
        # one (older records). We used to fabricate it as `usage_gb * 2`
        # here, which was an undocumented, unverified guess that could
        # quietly poison the "deducted" model. Better to be honest about
        # missing data: ml/train.py now trains usage and deducted on
        # their own independent sample sets, so a missing deducted_gb
        # here simply excludes that window from the deducted fit instead
        # of injecting a made-up number.
        usage_gb = isp["usage_gb"]
        deducted_gb = isp.get("deducted_gb")

        samples.append({
            "isp_from": isp["from"],
            "isp_to": isp["to"],
            "isp_usage_gb": usage_gb,
            "isp_deducted_gb": deducted_gb,
            "isp_duration_seconds": isp["duration_seconds"],
            "router_delta_count": len(matching_deltas),
            "device_count": len(devices),
            "total_delta_tx": sum(d["delta_tx_sum"] for d in devices),
            "total_delta_rx": sum(d["delta_rx_sum"] for d in devices),
            "devices": devices,
        })

    return samples


# --------------------------------------------------
# Reporting
# --------------------------------------------------

def print_report(samples: list[dict]) -> None:
    print("\n========== DATASET SUMMARY ==========\n")
    print(f"Total samples: {len(samples)}\n")

    for s in samples:
        coverage = "FULL" if s["router_delta_count"] > 0 else "NO DATA"
        print(f"--- {s['isp_from']}  →  {s['isp_to']} ---")
        print(f"    ISP usage:    {s['isp_usage_gb']} GB")
        print(f"    ISP deducted: {s['isp_deducted_gb']} GB")
        print(f"    Duration:     {s['isp_duration_seconds']}s")
        print(f"    Router delta: {s['router_delta_count']} ({coverage})")
        print(f"    Devices seen: {s['device_count']}")
        print(f"    Total Δtx:    {s['total_delta_tx']:,}")
        print(f"    Total Δrx:    {s['total_delta_rx']:,}")
        print()

        for d in s["devices"]:
            absent = (
                f"  [absent×{d['was_absent_count']}]"
                if d["was_absent_count"] > 0 else ""
            )
            reset = (
                f"  [reset×{d['counter_reset_count']}, estimated]"
                if d.get("counter_reset_count", 0) > 0 else ""
            )
            print(
                f"      {d['mac']}  "
                f"Δtx={d['delta_tx_sum']:>10,}  "
                f"Δrx={d['delta_rx_sum']:>10,}  "
                f"samples={d['samples']:>3}  "
                f"presence={d['presence_ratio']}  "
                f"rate={d['avg_tx_rate']}"
                f"{absent}{reset}"
            )
        print()


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main() -> None:
    deltas = load_json(DELTA_FILE)
    isp_records = load_json(ISP_FILE)

    print(f"Loaded {len(deltas)} delta interval(s)")
    print(f"Loaded {len(isp_records)} ISP record(s)")

    if not deltas:
        print(
            "→ No deltas available yet. "
            "Run `python -m analysis.snapshot_differ` first."
        )
        raise SystemExit(2)

    if not isp_records:
        print(
            "→ No ISP records available yet. "
            "Run `python -m collectors.isp_collector` first."
        )
        raise SystemExit(2)

    samples = build_samples(deltas, isp_records)

    print_report(samples)

    save_json(DATASET_FILE, samples)


if __name__ == "__main__":
    main()