import pytest

pytest.importorskip("jdatetime")

from collectors.isp_collector import parse_usage_gb, _overlaps, merge_records


def test_parse_usage_units():
    assert parse_usage_gb("3.12 گیگابایت") == 3.12
    assert parse_usage_gb("512 مگابایت") == pytest.approx(0.5, abs=1e-3)


def test_overlap_is_strict():
    a = {"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00"}
    b = {"from": "2026-01-01T12:00:00", "to": "2026-01-03T00:00:00"}
    c = {"from": "2026-01-02T00:00:00", "to": "2026-01-03T00:00:00"}
    assert _overlaps(a, b)
    assert not _overlaps(a, c)


def test_merge_replaces_overlapping_old():
    old = [{"from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00", "usage_gb": 1}]
    new = [{"from": "2026-01-01T12:00:00", "to": "2026-01-03T00:00:00", "usage_gb": 5}]
    merged = merge_records(old, new)
    assert len(merged) == 1 and merged[0]["usage_gb"] == 5
