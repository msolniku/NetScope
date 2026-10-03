import json
from collectors import storage


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "SNAPSHOT_FILE", tmp_path / "s.jsonl")
    monkeypatch.setattr(storage, "LEGACY_SNAPSHOT_FILE", tmp_path / "s.json")


def test_append_roundtrip(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    storage.save_snapshot([{"mac": "aa"}])
    storage.save_snapshot([{"mac": "bb"}])
    snaps = storage.load_snapshots()
    assert [s["users"][0]["mac"] for s in snaps] == ["aa", "bb"]


def test_corrupt_last_line_is_skipped(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    storage.save_snapshot([{"mac": "aa"}])
    with open(tmp_path / "s.jsonl", "a") as f:
        f.write('{"timestamp": "half-writ')
    assert len(storage.load_snapshots()) == 1


def test_legacy_json_is_migrated(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    (tmp_path / "s.json").write_text(json.dumps(
        [{"timestamp": "t1", "users": []}, {"timestamp": "t2", "users": []}]))
    assert len(storage.load_snapshots()) == 2
    assert (tmp_path / "s.json.migrated").exists()
