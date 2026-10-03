import numpy as np
from ml import train


def _samples(n, with_deducted=True):
    rng = np.random.default_rng(0)
    out = []
    for i in range(n):
        tx, rx = int(rng.integers(1e5, 1e6)), int(rng.integers(1e5, 1e6))
        dur = float(rng.integers(3, 20))
        usage = 1e-6 * tx + 2e-6 * rx + 0.01 * dur + 0.05
        out.append({
            "router_delta_count": 5, "total_delta_tx": tx, "total_delta_rx": rx,
            "isp_duration_seconds": dur * 3600, "isp_usage_gb": usage,
            "isp_deducted_gb": usage * 1.5 if with_deducted else None,
        })
    return out


def test_missing_deducted_is_excluded_not_fabricated():
    s = _samples(6)
    s[0]["isp_deducted_gb"] = None
    Xu, _ = train.extract_xy(s, "isp_usage_gb")
    Xd, _ = train.extract_xy(s, "isp_deducted_gb")
    assert len(Xu) == 6 and len(Xd) == 5


def test_few_samples_use_ratio_baseline():
    X, y = train.extract_xy(_samples(train.MIN_SAMPLES_FOR_LINEAR - 1), "isp_usage_gb")
    assert train.fit_for(X, y)["method"] == "ratio"


def test_enough_samples_use_linear_and_recover_weights():
    X, y = train.extract_xy(_samples(20), "isp_usage_gb")
    m = train.fit_for(X, y)
    assert m["method"] == "linear"
    assert abs(m["w_tx"] - 1e-6) < 1e-8 and abs(m["w_rx"] - 2e-6) < 1e-8


def test_cv_only_when_enough_samples():
    X, y = train.extract_xy(_samples(train.MIN_SAMPLES_FOR_CV - 1), "isp_usage_gb")
    assert train.loo_cv_metrics(X, y) is None
    X, y = train.extract_xy(_samples(15), "isp_usage_gb")
    cv = train.loo_cv_metrics(X, y)
    assert cv is not None and cv["n_folds"] == 15
