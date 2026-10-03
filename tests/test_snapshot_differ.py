from analysis.snapshot_differ import compute_deltas


def snap(ts, **macs):
    return {"timestamp": ts,
            "users": [{"mac": m, "tx_packet": tx, "rx_packet": rx,
                       "tx_rate": 54.0, "power_saving": "no"}
                      for m, (tx, rx) in macs.items()]}


def _dev(deltas, mac):
    return next(d for d in deltas[0]["deltas"] if d["mac"] == mac)


def test_simple_delta():
    d = compute_deltas([
        snap("2026-01-01T00:00:00", aa=(100, 200)),
        snap("2026-01-01T00:10:00", aa=(150, 260)),
    ])
    dev = _dev(d, "aa")
    assert dev["tx_packet_delta"] == 50
    assert dev["rx_packet_delta"] == 60
    assert dev["counter_reset"] is False


def test_counter_reset_is_estimated_not_zeroed():
    d = compute_deltas([
        snap("2026-01-01T00:00:00", aa=(100_000, 200_000)),
        snap("2026-01-01T00:10:00", aa=(700, 900)),   # rebooted
    ])
    dev = _dev(d, "aa")
    assert dev["counter_reset"] is True
    # Old behavior: 0. New behavior: traffic since reset (counter value).
    assert dev["tx_packet_delta"] == 700
    assert dev["rx_packet_delta"] == 900


def test_duplicate_timestamp_skipped():
    d = compute_deltas([
        snap("2026-01-01T00:00:00", aa=(1, 1)),
        snap("2026-01-01T00:00:00", aa=(2, 2)),
    ])
    assert d == []


def test_needs_two_snapshots():
    assert compute_deltas([snap("2026-01-01T00:00:00", aa=(1, 1))]) == []
