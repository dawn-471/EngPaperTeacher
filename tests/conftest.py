import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    lines = [
        ("A Practical Guide to", 24),
        ("Community Garden", 24),
        ("Planning", 24),
        ("First A. Author and Second B. Author", 11),
        ("Abstract: This guide explains seasonal garden planning.", 9),
        ("I. INTRODUCTION", 10),
        ("Community gardens give residents access to fresh produce.", 9),
        ("We describe a simple crop rotation plan for small urban plots.", 9),
    ]
    for text, size in lines:
        page.insert_text((50, y), text, fontsize=size)
        y += size + 12
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def sample_pdf() -> bytes:
    return build_pdf()


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.main as main

    docs = tmp_path / "docs"
    data = tmp_path / "data"
    docs.mkdir()
    data.mkdir()
    monkeypatch.setattr(main, "DOCS", docs)
    monkeypatch.setattr(main, "DATA", data)
    monkeypatch.setattr(main, "_dict", None)
    return TestClient(main.app)
