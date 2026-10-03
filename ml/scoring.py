from __future__ import annotations


def predict_sample_total(sample: dict, model: dict) -> float:
    """Predict total GB for this sample window (can be negative before use)."""
    tx = sample.get("total_delta_tx", 0) or 0
    rx = sample.get("total_delta_rx", 0) or 0
    dur_hours = (sample.get("isp_duration_seconds", 0) or 0) / 3600.0

    return (
        model["w_tx"] * tx
        + model["w_rx"] * rx
        + model["w_dur"] * dur_hours
        + model["bias"]
    )


def _raw_device_gb(device: dict, sample: dict, model: dict, share: float) -> float:
    dur_hours = (sample.get("isp_duration_seconds", 0) or 0) / 3600.0
    return (
        model["w_tx"] * device.get("delta_tx_sum", 0)
        + model["w_rx"] * device.get("delta_rx_sum", 0)
        + (model["w_dur"] * dur_hours + model["bias"]) * share
    )


def predict_devices(sample: dict, model: dict) -> dict[str, float]:
    """
    Predict GB for every device in `sample`, returned as {mac: gb}.

    Negative raw predictions (possible when `bias` < 0) are clipped to
    0, then the whole set is rescaled so it sums back to
    `predict_sample_total(sample, model)` — preserving "device shares
    add up to the window total" instead of silently losing GB to
    clipping.
    """
    devices = sample.get("devices", [])
    if not devices:
        return {}

    total_packets = (
        (sample.get("total_delta_tx", 0) or 0)
        + (sample.get("total_delta_rx", 0) or 0)
    )
    if total_packets <= 0:
        return {d["mac"]: 0.0 for d in devices}

    raw = {}
    for d in devices:
        device_packets = d.get("delta_tx_sum", 0) + d.get("delta_rx_sum", 0)
        share = device_packets / total_packets
        raw[d["mac"]] = _raw_device_gb(d, sample, model, share)

    clipped = {mac: max(0.0, g) for mac, g in raw.items()}
    clipped_sum = sum(clipped.values())

    total_pred = predict_sample_total(sample, model)

    if clipped_sum > 0 and total_pred > 0:
        scale = total_pred / clipped_sum
        return {mac: g * scale for mac, g in clipped.items()}

    return clipped


def predict_sample(sample: dict, model_usage: dict, model_deducted: dict):
    """
    Predict per-device usage AND deducted GB for one sample.

    Returns (per_device_list, total_usage_gb, total_deducted_gb).
    """
    usage_by_mac = predict_devices(sample, model_usage)
    deducted_by_mac = predict_devices(sample, model_deducted)

    per_device = []
    for d in sample.get("devices", []):
        mac = d["mac"]
        u = usage_by_mac.get(mac, 0.0)
        dd = deducted_by_mac.get(mac, 0.0)
        per_device.append({
            "mac": mac,
            "usage_gb": u,
            "deducted_gb": dd,
            "delta_tx": d.get("delta_tx_sum", 0),
            "delta_rx": d.get("delta_rx_sum", 0),
        })

    total_usage = sum(usage_by_mac.values())
    total_deducted = sum(deducted_by_mac.values())

    return per_device, total_usage, total_deducted
