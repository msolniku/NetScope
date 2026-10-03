import json
from datetime import datetime
from pathlib import Path

import numpy as np

from config.settings import DATASET_FILE, PROJECT_ROOT


MODEL_FILE = PROJECT_ROOT / "data" / "model.json"

# A linear fit here has 4 free parameters (w_tx, w_rx, w_dur, bias).
# With fewer samples than that, `lstsq` doesn't learn anything — it
# just solves (or nearly solves) the system exactly, and the in-sample
# R² will look deceptively perfect. We require a healthy margin above
# 4 before trusting a linear fit over the plain ratio baseline.
MIN_SAMPLES_FOR_LINEAR = 8

# Minimum samples before leave-one-out CV is worth reporting at all.
MIN_SAMPLES_FOR_CV = 5


# --------------------------------------------------
# I/O
# --------------------------------------------------

def load_dataset() -> list[dict]:
    if not DATASET_FILE.exists():
        return []
    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_model(model: dict) -> None:
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=4)
    print(f"Model saved: {MODEL_FILE}")


# --------------------------------------------------
# Feature extraction
# --------------------------------------------------

def extract_xy(samples: list[dict], target_key: str):
    """
    Build X = [[Δtx, Δrx, duration_hours], ...] and y = [target, ...]
    using only samples where `target_key` (e.g. "isp_usage_gb" or
    "isp_deducted_gb") is actually present. This is what lets usage
    and deducted models have different (independent) sample counts
    instead of forcing deducted to borrow/guess from usage.
    """
    X, y = [], []

    for s in samples:
        if s["router_delta_count"] == 0:
            continue

        target = s.get(target_key)
        if target is None:
            continue

        tx = s.get("total_delta_tx", 0) or 0
        rx = s.get("total_delta_rx", 0) or 0
        if tx + rx <= 0:
            continue

        dur_sec = s.get("isp_duration_seconds", 0) or 0
        dur_hours = dur_sec / 3600.0
        if dur_hours <= 0:
            continue

        X.append([tx, rx, dur_hours])
        y.append(target)

    return np.array(X, dtype=float), np.array(y, dtype=float)


# --------------------------------------------------
# Fitting
# --------------------------------------------------

def fit_ratio_baseline(X: np.ndarray, y: np.ndarray) -> dict:
    """Simple ratio: every packet costs the same. w_dur = 0, bias = 0."""
    total_packets = X[:, 0].sum() + X[:, 1].sum()
    if total_packets <= 0:
        return {"w_tx": 0.0, "w_rx": 0.0, "w_dur": 0.0, "bias": 0.0,
                "method": "ratio"}
    w = float(y.sum() / total_packets)
    return {"w_tx": w, "w_rx": w, "w_dur": 0.0, "bias": 0.0,
            "method": "ratio"}


def fit_linear(X: np.ndarray, y: np.ndarray) -> dict:
    """
    OLS with intercept:
        y ≈ w_tx*X0 + w_rx*X1 + w_dur*X2 + bias
    """
    A = np.hstack([X, np.ones((X.shape[0], 1))])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)

    return {
        "w_tx": float(coef[0]),
        "w_rx": float(coef[1]),
        "w_dur": float(coef[2]),
        "bias": float(coef[3]),
        "method": "linear",
    }


def fit_for(X: np.ndarray, y: np.ndarray) -> dict:
    """Pick ratio baseline or linear fit depending on sample size."""
    if X.shape[0] < MIN_SAMPLES_FOR_LINEAR:
        return fit_ratio_baseline(X, y)
    return fit_linear(X, y)


# --------------------------------------------------
# Metrics
# --------------------------------------------------

def compute_metrics(X: np.ndarray, y: np.ndarray, model: dict) -> dict:
    """In-sample (fit) error. Optimistic — see module docstring."""
    coef = np.array([model["w_tx"], model["w_rx"], model["w_dur"], model["bias"]])
    A = np.hstack([X, np.ones((X.shape[0], 1))])
    y_pred = A @ coef
    return _regression_metrics(y, y_pred)


def loo_cv_metrics(X: np.ndarray, y: np.ndarray) -> dict | None:
    """
    Leave-one-out cross-validation: for each sample, refit on all the
    OTHER samples (using the same ratio-vs-linear rule as the real
    model) and predict the held-out one. This is a much more honest
    estimate of real-world error than in-sample metrics, at the cost
    of needing a handful more samples to be meaningful at all.
    """
    n = X.shape[0]
    if n < MIN_SAMPLES_FOR_CV:
        return None

    preds = np.zeros(n)
    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        model_i = fit_for(X[mask], y[mask])
        coef = np.array([model_i["w_tx"], model_i["w_rx"], model_i["w_dur"], model_i["bias"]])
        xi = np.append(X[i], 1.0)
        preds[i] = xi @ coef

    metrics = _regression_metrics(y, preds)
    metrics["method"] = "leave-one-out CV"
    metrics["n_folds"] = n
    return metrics


def _regression_metrics(y: np.ndarray, y_pred: np.ndarray) -> dict:
    mae  = float(np.mean(np.abs(y - y_pred)))
    rmse = float(np.sqrt(np.mean((y - y_pred) ** 2)))

    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None

    return {
        "mae_gb":  round(mae, 4),
        "rmse_gb": round(rmse, 4),
        "r2":      round(r2, 4) if r2 is not None else None,
    }


# --------------------------------------------------
# Reporting
# --------------------------------------------------

def print_model(name: str, model: dict) -> None:
    print(f"\n--- {name} ---")
    print(f"  method: {model['method']}  (n_samples={model['n_samples']})")
    print(f"  w_tx  = {model['w_tx']:.6e} GB/packet")
    print(f"  w_rx  = {model['w_rx']:.6e} GB/packet")
    print(f"  w_dur = {model['w_dur']:.6e} GB/hour")
    print(f"  bias  = {model['bias']:.6e} GB")


def print_metrics(name: str, metrics: dict, cv_metrics: dict | None) -> None:
    print(f"  {name} [in-sample, optimistic]: "
          f"MAE={metrics['mae_gb']} GB  RMSE={metrics['rmse_gb']} GB  R²={metrics['r2']}")
    if cv_metrics is None:
        print(f"  {name} [leave-one-out CV]:    not enough samples yet "
              f"(need ≥{MIN_SAMPLES_FOR_CV})")
    else:
        print(f"  {name} [leave-one-out CV]:    "
              f"MAE={cv_metrics['mae_gb']} GB  RMSE={cv_metrics['rmse_gb']} GB  "
              f"R²={cv_metrics['r2']}  (n_folds={cv_metrics['n_folds']})")


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main() -> None:
    samples = load_dataset()
    print(f"Loaded {len(samples)} sample(s)")

    results = {}
    any_trained = False

    for target_name, target_key in [
        ("usage", "isp_usage_gb"),
        ("deducted", "isp_deducted_gb"),
    ]:
        X, y = extract_xy(samples, target_key)
        n = X.shape[0]
        print(f"\n→ {target_name}: {n} usable sample(s) "
              f"(target field: {target_key}).")

        if n == 0:
            print(f"  Skipping {target_name} — no usable samples.")
            continue

        any_trained = True

        if n < MIN_SAMPLES_FOR_LINEAR:
            print(f"  Only {n} sample(s) (<{MIN_SAMPLES_FOR_LINEAR}) "
                  "— using ratio baseline.")
        else:
            print(f"  Fitting linear model on {n} sample(s).")

        model = fit_for(X, y)
        metrics = compute_metrics(X, y, model)
        cv_metrics = loo_cv_metrics(X, y)

        model["n_samples"]  = n
        model["trained_at"] = datetime.now().isoformat(timespec="seconds")
        model["metrics"]    = metrics
        model["cv_metrics"] = cv_metrics

        print_model(target_name, model)
        print_metrics(target_name, metrics, cv_metrics)

        results[target_name] = model

    if not any_trained:
        print("\n→ Not enough usable samples yet.")
        raise SystemExit(2)

    if "deducted" not in results:
        print("\n⚠ No samples had a `deducted_gb` value — "
              "falling back to the usage model for deducted predictions.")
        results["deducted"] = dict(results["usage"])
        results["deducted"]["note"] = "fallback: no deducted_gb samples were available"

    model = {
        "features":     ["delta_tx", "delta_rx", "duration_hours"],
        "target_unit":  "GB per window",
        "usage":        results["usage"],
        "deducted":     results["deducted"],
        "trained_at":   datetime.now().isoformat(timespec="seconds"),
    }

    save_model(model)


if __name__ == "__main__":
    main()
