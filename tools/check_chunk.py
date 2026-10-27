"""Chunk sanity check.

Usage: .venv/Scripts/python.exe tools/check_chunk.py
"""
import sys
from pathlib import Path

reconfigure = getattr(sys.stdout, "reconfigure", None)
if reconfigure:
    reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import chunking

TESTS = [
    "The local library extended its weekend hours after a sharp rise in visitor numbers.",
    "Many small towns still struggle to fund basic services, even as nearby cities expand, and planners disagree about whether the solution is more money or better coordination.",
    "The committee meets on Thursday: the chair reviews the budget; the treasurer presents the revised figures; and the members vote before the end of the month.",
    "We tested three watering schedules on a fixed group of tomato plants, using two soil types and a different fertilizer brand, in trials designed to separate the effects of frequency, sunlight, and pest control.",
    "The extra fertilizer made little difference once temperature was held steady.",
    "Plants in the larger pot kept their lead after an extra week, though the gap became smaller.",
    "Community gardens offer one practical option.",
    "This project examines how a shared garden can improve neighborhood food access.",
]

for i, s in enumerate(TESTS):
    chunks = chunking.chunk_text(s)
    print(f"[{i+1}] {s[:110]}")
    print("    " + " | ".join(f"{c['text']} [{c['label']}]" for c in chunks))
    print()
