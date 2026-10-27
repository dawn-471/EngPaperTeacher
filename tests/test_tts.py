import json

from app.tts import TTS


async def _fake_edge(self, text, voice, rate, out_path, proxy=None):
    out_path.write_bytes(b"ID3fake-mp3")
    return [{"type": "SentenceBoundary", "text": text}]


def test_edge_cache_and_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(TTS, "_synth_edge", _fake_edge)
    t = TTS(tmp_path, proxy=None, max_files=100)
    path, boundaries, cached = t.synthesize("Hello world.", "en-US-AriaNeural", "+0%")
    assert path.exists() and not cached
    assert boundaries
    path2, boundaries2, cached2 = t.synthesize("Hello world.", "en-US-AriaNeural", "+0%")
    assert path2 == path and cached2 is True
    assert boundaries2 == boundaries
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["engine"] == "edge"


def test_google_fallback(tmp_path, monkeypatch):
    async def fail_edge(self, text, voice, rate, out_path, proxy=None):
        raise RuntimeError("edge down")

    def fake_google(self, text, voice, out_path):
        out_path.write_bytes(b"ID3google")

    monkeypatch.setattr(TTS, "_synth_edge", fail_edge)
    monkeypatch.setattr(TTS, "_synth_google", fake_google)
    t = TTS(tmp_path, proxy=None, max_files=100)
    path, boundaries, cached = t.synthesize("Hello world.", "en-US-AriaNeural")
    assert path.exists() and not cached
    assert boundaries == []
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["engine"] == "google"


def test_prunes_old_cache(tmp_path):
    for i in range(5):
        mp3 = tmp_path / ("old%d.mp3" % i)
        mp3.write_bytes(b"x")
        mp3.with_suffix(".json").write_text("[]", encoding="utf-8")
    TTS(tmp_path, proxy=None, max_files=3)
    assert len(list(tmp_path.glob("*.mp3"))) == 3
