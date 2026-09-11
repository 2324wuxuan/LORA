"""Back up the existing database, then seed/upgrade all control circuits."""
from pathlib import Path
from datetime import datetime
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import DATABASE_PATH, DEVICES
from database import db

if DATABASE_PATH.exists():
    backups = DATABASE_PATH.parent / "backups"
    backups.mkdir(exist_ok=True)
    (backups/".gitignore").write_text("*\n")
    target = backups / f"before-full-deployment-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    source = sqlite3.connect(str(DATABASE_PATH))
    backup = sqlite3.connect(str(target))
    try:
        source.backup(backup)
    finally:
        source.close(); backup.close()
    print("Backup:", target)
db.init_db()
rows = {row["device_id"] for row in db.get_all_devices()}
assert set(DEVICES) <= rows
print("Configured circuits present in database:", len(set(DEVICES) & rows))
