"""Check the ECDICT database: row count + sample lookups.

Usage: .venv/Scripts/python.exe tools/check_dict.py
"""
import sqlite3
import sys
from pathlib import Path

reconfigure = getattr(sys.stdout, "reconfigure", None)
if reconfigure:
    reconfigure(encoding="utf-8", errors="replace")

db = Path(__file__).resolve().parent.parent / "data" / "stardict.db"
print("db:", db)
c = sqlite3.connect(str(db))
print("rows:", c.execute("select count(*) from stardict").fetchone()[0])
for w in ("garden", "harvest", "compost", "seedling", "rotate",
          "seasonal", "sprout", "water"):
    r = c.execute("select word, phonetic, translation from stardict where word=? limit 1",
                  (w,)).fetchone()
    if r:
        first = (r[2] or "").split("\n")[0][:70]
        print(f"  {w:12s} /{r[1] or ''}/  {first}")
    else:
        print(f"  {w:12s} MISS")
