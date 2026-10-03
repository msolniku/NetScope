import json
from datetime import datetime

from config.settings import SNAPSHOT_FILE, LEGACY_SNAPSHOT_FILE


def _migrate_legacy() -> None:
    if SNAPSHOT_FILE.exists() or not LEGACY_SNAPSHOT_FILE.exists():
        return

    with open(LEGACY_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        legacy = json.load(f)

    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        for snap in legacy:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")

    LEGACY_SNAPSHOT_FILE.rename(
        LEGACY_SNAPSHOT_FILE.with_suffix(".json.migrated")
    )
    print(f"Migrated {len(legacy)} snapshot(s) to {SNAPSHOT_FILE}")


def load_snapshots() -> list[dict]:
    """Load all snapshots. Returns [] if none. Skips corrupt lines."""
    _migrate_legacy()

    if not SNAPSHOT_FILE.exists():
        return []

    snapshots = []
    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                snapshots.append(json.loads(line))
            except json.JSONDecodeError:
                # e.g. a half-written last line after a crash: skip it
                # instead of losing the whole history.
                print(f"⚠ Skipping corrupt snapshot line {line_no}")
    return snapshots


def save_snapshot(records: list[dict]) -> None:
    """Append one OCR snapshot (with timestamp) as a single line."""
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _migrate_legacy()

    snapshot = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "users": records,
    }

    with open(SNAPSHOT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

    print(f"Snapshot saved: {SNAPSHOT_FILE} ({len(records)} user(s))")
