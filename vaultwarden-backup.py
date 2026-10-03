import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent / ".env"
REQUIRED = ("SRC", "DEST", "KEEP_DAYS", "OWNER")
SKIP = {"db.sqlite3", "db.sqlite3-wal", "db.sqlite3-shm", "icon_cache", "tmp"}

if not ENV_FILE.exists():
    print(f"ERROR: no .env file at {ENV_FILE}", file=sys.stderr)
    sys.exit(1)

config = dotenv_values(ENV_FILE)
for key in REQUIRED:
    if not config.get(key):
        print(f"ERROR: {key} is missing or empty in {ENV_FILE}", file=sys.stderr)
        sys.exit(1)

SRC = Path(config["SRC"])
DEST = Path(config["DEST"])
OWNER = config["OWNER"]


def snapshot_db(src, dst):
    with closing(sqlite3.connect(src)) as live, closing(sqlite3.connect(dst)) as copy:
        live.backup(copy)
        result = copy.execute("PRAGMA integrity_check").fetchone()[0]

    if result != "ok":
        raise RuntimeError(f"Snapshot failed integrity check: {result}")


def make_archive(snapshot, archive):
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(snapshot, arcname="db.sqlite3")
        for item in SRC.iterdir():
            if item.name not in SKIP:
                tar.add(item, arcname=item.name)


def prune_old(dest, keep_days, newest):
    cutoff = time.time() - keep_days * 24 * 60 * 60
    removed = 0
    for old in dest.glob("vw-*.tar.gz"):
        if old != newest and old.stat().st_mtime < cutoff:
            old.unlink()
            removed += 1
    return removed


def main():
    db = SRC / "db.sqlite3"

    if not db.exists():
        print(f"ERROR: no database at {db}", file=sys.stderr)
        return 1

    DEST.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive = DEST / f"vw-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "db.sqlite3"
        snapshot_db(db, snapshot)
        make_archive(snapshot, archive)

    shutil.chown(DEST, user=OWNER, group=OWNER)
    shutil.chown(archive, user=OWNER, group=OWNER)

    print(f"{datetime.now():%Y-%m-%d %H:%M} Backup saved to {archive}")

    removed = prune_old(DEST, int(config["KEEP_DAYS"]), archive)
    print(f"{datetime.now():%Y-%m-%d %H:%M} Pruned {removed} old backup(s)")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"{datetime.now():%Y-%m-%d %H:%M} FAILED  {e}", file=sys.stderr)
        sys.exit(1)
