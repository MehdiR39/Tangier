import os
import sqlite3

from intel.db.connection import Database
from intel.db.maintenance import backup_connection, ensure_healthy, latest_backup, quick_check, rotate_backups


def test_backup_restore_and_quarantine(tmp_path):
    live = str(tmp_path / "live.sqlite")
    bdir = str(tmp_path / "backups")
    db = Database(live, backup_dir=bdir)
    db.insert("sync_cursors", {"name": "x", "block_number": 42, "ts": 1, "updated_ts": 1})
    assert db.health["status"] == "ok"
    b1 = db.backup_to(os.path.join(bdir, "intel-0001.sqlite"))
    assert quick_check(b1) == (True, "ok")
    db.backup_to(os.path.join(bdir, "intel-0002.sqlite"))
    db.backup_to(os.path.join(bdir, "intel-0003.sqlite"))
    assert len(rotate_backups(bdir, keep=2)) == 1
    assert latest_backup(bdir).endswith("intel-0003.sqlite")
    db.close()
    # corrupt the live file on purpose
    with open(live, "r+b") as fh:
        fh.seek(0)
        fh.write(b"garbage" * 200)
    ok, msg = quick_check(live)
    assert not ok
    res = ensure_healthy(live, bdir)
    assert res["status"] == "restored" and res["restored_from"].endswith("intel-0003.sqlite")
    assert os.path.exists(res["quarantined"])
    db2 = Database(live, backup_dir=bdir)
    assert db2.cursor_get("x") == 42  # data came back from the backup
    db2.close()


def test_ensure_healthy_recreates_without_backup(tmp_path):
    live = str(tmp_path / "live.sqlite")
    with open(live, "wb") as fh:
        fh.write(b"not a database at all")
    res = ensure_healthy(live, str(tmp_path / "nobackups"))
    assert res["status"] == "recreated" and not os.path.exists(live)
    db = Database(live, backup_dir=None)
    assert db.health["status"] == "ok"
    db.close()


def test_backup_connection_is_consistent(tmp_path):
    src = sqlite3.connect(str(tmp_path / "s.sqlite"))
    src.execute("CREATE TABLE t(x)")
    src.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1000)])
    src.commit()
    dest = backup_connection(src, str(tmp_path / "out" / "b.sqlite"))
    assert sqlite3.connect(dest).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1000
