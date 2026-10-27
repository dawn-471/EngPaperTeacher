"""Sanity-check the parser on a PDF.

Usage: .venv/Scripts/python.exe tools/check_parse.py [path/to.pdf]
"""
import collections
import sys
from pathlib import Path

reconfigure = getattr(sys.stdout, "reconfigure", None)
if reconfigure:
    reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pdf_parse

default = Path(__file__).resolve().parent.parent / "data" / "docs" / "main" / "source.pdf"
path = sys.argv[1] if len(sys.argv) > 1 else str(default)
if not Path(path).exists():
    sys.exit(f"pdf not found: {path}")
d = pdf_parse.parse_pdf(path)
print("title:", d["title"][:100])
print("pages:", d["page_count"], "| blocks:", len(d["blocks"]))
print("kinds:", dict(collections.Counter(b["kind"] for b in d["blocks"])))
for b in d["blocks"][:6]:
    print(" ", b["i"], "p" + str(b["page"]), b["kind"], "|", b["text"][:90])
print("sections:", [s["title"][:50] for s in d["sections"]])
