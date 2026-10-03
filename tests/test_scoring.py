import pytest
from ml.scoring import predict_devices, predict_sample_total, predict_sample


def _sample(devs, dur_s=3600):
    tx = sum(d["delta_tx_sum"] for d in devs)
    rx = sum(d["delta_rx_sum"] for d in devs)
    return {"total_delta_tx": tx, "total_delta_rx": rx,
            "isp_duration_seconds": dur_s, "devices": devs}


def _dev(mac, tx, rx):
    return {"mac": mac, "delta_tx_sum": tx, "delta_rx_sum": rx}


def test_device_predictions_sum_to_window_total():
    model = {"w_tx": 1e-6, "w_rx": 2e-6, "w_dur": 0.01, "bias": 0.05}
    s = _sample([_dev("a", 1000, 5000), _dev("b", 200, 800), _dev("c", 10, 40)])
    per = predict_devices(s, model)
    assert sum(per.values()) == pytest.approx(predict_sample_total(s, model))


def test_negative_bias_does_not_lose_gb_to_clipping():
    # Tiny device would go negative (bias share) and be clipped to 0;
    # the total must still be conserved.
    model = {"w_tx": 1e-6, "w_rx": 1e-6, "w_dur": 0.0, "bias": -0.5}
    s = _sample([_dev("big", 900_000, 900_000), _dev("tiny", 1, 1)])
    per = predict_devices(s, model)
    assert all(v >= 0 for v in per.values())
    assert sum(per.values()) == pytest.approx(predict_sample_total(s, model))


def test_zero_traffic_returns_zeros():
    model = {"w_tx": 1, "w_rx": 1, "w_dur": 1, "bias": 1}
    s = _sample([_dev("a", 0, 0)])
    assert predict_devices(s, model) == {"a": 0.0}


def test_no_devices():
    assert predict_devices({"devices": []}, {"w_tx": 0, "w_rx": 0, "w_dur": 0, "bias": 0}) == {}


def test_predict_sample_shape():
    m = {"w_tx": 1e-6, "w_rx": 1e-6, "w_dur": 0.0, "bias": 0.0}
    s = _sample([_dev("a", 100, 100)])
    per, tu, td = predict_sample(s, m, m)
    assert per[0]["mac"] == "a"
    assert tu == pytest.approx(td)
