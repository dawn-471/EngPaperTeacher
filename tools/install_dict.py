"""Extract ECDICT sqlite zip -> data/stardict.db."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
zip_path = DATA / "ecdict-sqlite-28.zip"

if not zip_path.exists():
    sys.exit(f"zip not found: {zip_path}")

with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    print("contents:", names)
    target = None
    for n in names:
        if n.lower().endswith(".db"):
            target = n
            break
    if not target:
        sys.exit("no .db inside zip")
    z.extract(target, DATA)
    src = DATA / target
    dst = DATA / "stardict.db"
    if src != dst:
        src.replace(dst)
print("installed:", DATA / "stardict.db")
