import json
from pathlib import Path

from config.settings import DATASET_FILE, PROJECT_ROOT
from ml.scoring import predict_sample


MODEL_FILE = PROJECT_ROOT / "data" / "model.json"


# --------------------------------------------------
# I/O
# --------------------------------------------------

def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------
# Reporting
# --------------------------------------------------

def print_sample_report(sample, per_device, pred_usage, pred_ded):
    actual_usage = sample.get("isp_usage_gb") or 0
    actual_ded   = sample.get("isp_deducted_gb")

    print(f"\n========== {sample['isp_from']}  →  {sample['isp_to']} ==========")
    print(f"  Usage    actual / predicted: {actual_usage:>8.4f} / {pred_usage:>8.4f} GB"
          f"   (diff {pred_usage - actual_usage:+.4f})")
    if actual_ded is None:
        print(f"  Deducted actual: n/a (old record)   predicted: {pred_ded:>8.4f} GB")
    else:
        print(f"  Deducted actual / predicted: {actual_ded:>8.4f} / {pred_ded:>8.4f} GB"
              f"   (diff {pred_ded - actual_ded:+.4f})")
    print()

    print(f"  {'MAC':<20} {'Δtx':>12} {'Δrx':>12} "
          f"{'Usage':>10} {'Deducted':>10} {'Share':>7}")
    print("  " + "-" * 75)

    total_share_base = sum(d["usage_gb"] for d in per_device) or 1.0
    for d in sorted(per_device, key=lambda x: -x["usage_gb"]):
        share = d["usage_gb"] / total_share_base
        print(
            f"  {d['mac']:<20} "
            f"{d['delta_tx']:>12,} {d['delta_rx']:>12,} "
            f"{d['usage_gb']:>10.4f} {d['deducted_gb']:>10.4f} "
            f"{share:>6.1%}"
        )


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main() -> None:
    model = load_json(MODEL_FILE)
    if not model:
        print("→ No model found. Run `python -m ml.train` first.")
        raise SystemExit(2)

    dataset = load_json(DATASET_FILE) or []
    usable = [s for s in dataset if s["router_delta_count"] > 0]

    if not usable:
        print("→ No usable samples in dataset.")
        raise SystemExit(2)

    m_usage = model["usage"]
    m_ded   = model["deducted"]

    print(f"Model: {m_usage['method']}  (n_samples={m_usage['n_samples']}, "
          f"trained_at={model.get('trained_at')})")
    print(f"  usage:    w_tx={m_usage['w_tx']:.3e} w_rx={m_usage['w_rx']:.3e} "
          f"w_dur={m_usage['w_dur']:.3e} bias={m_usage['bias']:.3e}")
    print(f"  deducted: w_tx={m_ded['w_tx']:.3e} w_rx={m_ded['w_rx']:.3e} "
          f"w_dur={m_ded['w_dur']:.3e} bias={m_ded['bias']:.3e}")

    for s in usable:
        per_device, pred_usage, pred_ded = predict_sample(s, m_usage, m_ded)
        print_sample_report(s, per_device, pred_usage, pred_ded)


if __name__ == "__main__":
    main()
