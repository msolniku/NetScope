import json
from datetime import datetime
from pathlib import Path

from collectors.storage import load_snapshots
from config.settings import (
    DELTA_FILE,
    MAX_INTERVAL_SECONDS,
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
# Baseline initialization
# --------------------------------------------------

def build_initial_last_seen(snapshot: dict) -> dict[str, dict]:
    """
    Seed `last_seen` from the very first snapshot, so that the
    first delta interval is computed against a real baseline
    instead of being thrown away as "brand-new device".

    Returns: mac -> {"ts": datetime, "tx": int, "rx": int}
    """
    ts = parse_ts(snapshot["timestamp"])
    last_seen: dict[str, dict] = {}

    for user in snapshot["users"]:
        mac = user.get("mac")
        tx = user.get("tx_packet")
        rx = user.get("rx_packet")

        if mac is None or tx is None or rx is None:
            continue

        last_seen[mac] = {
            "ts": ts,
            "tx": tx,
            "rx": rx,
        }

    return last_seen


# --------------------------------------------------
# Diffing
# --------------------------------------------------

def compute_deltas(snapshots: list[dict]) -> list[dict]:
    """
    Walk through consecutive snapshots and produce delta intervals.

    For each device (MAC), track the last time we saw it and its
    tx/rx counters. On each new snapshot, compute the differences
    from that last-seen point. Handles:
      - counter resets (device rebooted)
      - device absence (gap_seconds > normal interval)
      - new devices (no previous record)
    """
    deltas: list[dict] = []

    if len(snapshots) < 2:
        return deltas

    # Seed baseline from the first snapshot so the first delta
    # interval has real numbers instead of zeros.
    last_seen = build_initial_last_seen(snapshots[0])

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        prev_ts = parse_ts(prev["timestamp"])
        curr_ts = parse_ts(curr["timestamp"])
        interval = (curr_ts - prev_ts).total_seconds()

        if interval <= 0:
            # Out-of-order or duplicate timestamp — skip
            continue

        prev_users = {u["mac"]: u for u in prev["users"]}
        curr_users = {u["mac"]: u for u in curr["users"]}

        device_deltas: list[dict] = []

        for mac, user in curr_users.items():
            tx_now = user.get("tx_packet")
            rx_now = user.get("rx_packet")

            if tx_now is None or rx_now is None:
                continue

            # First time we ever see this MAC (appeared after snapshot 0)
            if mac not in last_seen:
                last_seen[mac] = {
                    "ts": curr_ts,
                    "tx": tx_now,
                    "rx": rx_now,
                }
                device_deltas.append({
                    "mac": mac,
                    "tx_packet_delta": 0,
                    "rx_packet_delta": 0,
                    "counter_reset": False,
                    "gap_seconds": 0,
                    "was_absent": True,
                    "tx_rate": user.get("tx_rate"),
                    "power_saving": user.get("power_saving", "no"),
                })
                continue

            last = last_seen[mac]
            gap = (curr_ts - last["ts"]).total_seconds()

            tx_delta = tx_now - last["tx"]
            rx_delta = rx_now - last["rx"]

            # Counter reset (device rebooted or counter wrapped).
            counter_reset = tx_delta < 0 or rx_delta < 0

            if counter_reset:
                # The old behavior here was to record a delta of 0 and
                # let downstream code skip the interval entirely — which
                # silently threw away all traffic in that window instead
                # of estimating it. Router packet counters restart at 0
                # after a reboot, so the current reading IS (approximately)
                # the traffic since the reset — use it directly instead of
                # discarding it. This is still an approximation (we don't
                # know exactly when between `last["ts"]` and `curr_ts` the
                # reset happened), which is why `counter_reset` stays True
                # so callers can see it was estimated rather than measured.
                tx_delta_final = max(tx_now, 0)
                rx_delta_final = max(rx_now, 0)
            else:
                tx_delta_final = max(tx_delta, 0)
                rx_delta_final = max(rx_delta, 0)

            # was_absent: device was missing in the immediately preceding snapshot
            was_absent = mac not in prev_users

            device_deltas.append({
                "mac": mac,
                "tx_packet_delta": tx_delta_final,
                "rx_packet_delta": rx_delta_final,
                "counter_reset": counter_reset,
                "gap_seconds": int(gap),
                "was_absent": was_absent,
                "tx_rate": user.get("tx_rate"),
                "power_saving": user.get("power_saving", "no"),
            })

            # Update last-seen
            last_seen[mac] = {
                "ts": curr_ts,
                "tx": tx_now,
                "rx": rx_now,
            }

        if not device_deltas:
            continue

        reliable = interval <= MAX_INTERVAL_SECONDS

        deltas.append({
            "from": prev["timestamp"],
            "to": curr["timestamp"],
            "interval_seconds": int(interval),
            "reliable": reliable,
            "deltas": device_deltas,
        })

    return deltas


# --------------------------------------------------
# Reporting
# --------------------------------------------------

def print_report(deltas: list[dict]) -> None:
    print("\n========== DELTA SUMMARY ==========\n")
    print(f"Total intervals: {len(deltas)}")

    if not deltas:
        return

    reliable = sum(1 for d in deltas if d["reliable"])
    print(f"Reliable:        {reliable}")
    print(f"Unreliable:      {len(deltas) - reliable}")

    total_resets = sum(
        1 for d in deltas for dev in d["deltas"] if dev["counter_reset"]
    )
    total_absent = sum(
        1 for d in deltas for dev in d["deltas"] if dev["was_absent"]
    )
    print(f"Counter resets:  {total_resets}")
    print(f"Was-absent:      {total_absent}")


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main() -> None:
    snapshots = load_snapshots()

    print(f"Loaded {len(snapshots)} snapshot(s)")

    if len(snapshots) < 2:
        print(
            "→ Not enough snapshots yet (need at least 2). "
            "Run the router collector first."
        )
        raise SystemExit(2)   # exit code 2 = "no data yet"

    deltas = compute_deltas(snapshots)

    print_report(deltas)

    save_json(DELTA_FILE, deltas)


if __name__ == "__main__":
    main()