"""Dev server: run without auto-opening the browser (for tests).

Usage: .venv/Scripts/python.exe tools/dev_server.py [port]
"""
import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")
