"""Launch EngPaperTeacher locally and open the browser."""
import json
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

cfg = {}
if (ROOT / "config.json").exists():
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

HOST = cfg.get("host", "127.0.0.1")
PORT = int(cfg.get("port", 8765))
URL = f"http://{HOST}:{PORT}/"


def _already_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return s.connect_ex((HOST, PORT)) == 0
    finally:
        s.close()


if _already_running():
    print(f"EngPaperTeacher 已在运行：{URL}")
    if not os.environ.get("EPT_NO_BROWSER"):
        webbrowser.open(URL)
    sys.exit(0)

if not os.environ.get("EPT_NO_BROWSER"):
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")
