"""Text-to-speech via edge-tts (Microsoft neural voices) + Google TTS fallback."""
import asyncio
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import edge_tts

_CITE_RE = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")
_WS_RE = re.compile(r"\s+")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
_GOOGLE_TTS = "https://translate.google.com/translate_tts"

_ZH_KEEP = {"zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"}

_FALLBACK_VOICES = [
    {"id": "en-US-AndrewMultilingualNeural", "label": "Andrew ML (en-US)", "locale": "en-US"},
    {"id": "en-US-AvaMultilingualNeural", "label": "Ava ML (en-US)", "locale": "en-US"},
    {"id": "en-US-AriaNeural", "label": "Aria (en-US)", "locale": "en-US"},
    {"id": "en-US-GuyNeural", "label": "Guy (en-US)", "locale": "en-US"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia (en-GB)", "locale": "en-GB"},
    {"id": "zh-CN-XiaoxiaoNeural", "label": "Xiaoxiao (zh-CN)", "locale": "zh-CN"},
    {"id": "zh-CN-YunxiNeural", "label": "Yunxi (zh-CN)", "locale": "zh-CN"},
]


def clean_text(text: str) -> str:
    t = _CITE_RE.sub(" ", text or "")
    t = _WS_RE.sub(" ", t).strip()
    return t


def _split_tts(text: str, limit: int = 180) -> list[str]:
    parts = re.split(r"(?<=[.!?;:])\s+", text)
    chunks = []
    cur = ""
    for part in parts:
        if not part:
            continue
        if not cur:
            cur = part
        elif len(cur) + 1 + len(part) <= limit:
            cur += " " + part
        else:
            chunks.append(cur)
            cur = part
        while len(cur) > limit:
            cut = cur.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(cur[:cut].strip())
            cur = cur[cut:].strip()
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


class TTS:
    def __init__(self, cache_dir, proxy: str | None = None, max_files=2000):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.proxy = proxy or None
        self.max_files = max(1, int(max_files or 2000))
        self._writes = 0
        self._prune()

    def _paths(self, text, voice, rate):
        key = hashlib.md5(("%s|%s|%s" % (voice, rate, text)).encode("utf-8")).hexdigest()
        return self.cache_dir / (key + ".mp3"), self.cache_dir / (key + ".json")

    def _read_meta(self, meta: Path):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(data, dict):
            data = data.get("boundaries") or []
        return data if isinstance(data, list) else []

    def synthesize(self, text, voice="en-US-AriaNeural", rate="+0%"):
        """Returns (mp3_path, boundaries, cached: bool)."""
        clean = clean_text(text)
        if not clean:
            raise ValueError("empty text")
        mp3, meta = self._paths(clean, voice, rate)
        if mp3.exists() and mp3.stat().st_size > 0:
            return mp3, self._read_meta(meta), True

        boundaries = []
        errors = []
        engine = "edge"
        proxies = [self.proxy, None] if self.proxy else [None]
        for proxy in proxies:
            try:
                boundaries = asyncio.run(self._synth_edge(clean, voice, rate, mp3, proxy))
                break
            except Exception as e:  # noqa: BLE001
                errors.append("edge-tts: %s" % e)
        else:
            engine = "google"
            try:
                self._synth_google(clean, voice, mp3)
                boundaries = []
            except Exception as e:  # noqa: BLE001
                errors.append("Google TTS: %s" % e)
                try:
                    mp3.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError(" / ".join(errors))

        try:
            meta.write_text(json.dumps(
                {"engine": engine, "boundaries": boundaries}, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass
        self._writes += 1
        if self._writes % 50 == 0:
            self._prune()
        return mp3, boundaries, False

    async def _synth_edge(self, text, voice, rate, out_path, proxy=None):
        comm = edge_tts.Communicate(text, voice, rate=rate, proxy=proxy)
        audio = bytearray()
        boundaries = []
        async for ch in comm.stream():
            ctype = ch.get("type")
            if ctype == "audio":
                audio += ch["data"]
            elif ctype in ("SentenceBoundary", "WordBoundary"):
                boundaries.append({"type": ctype, "offset": ch.get("offset"),
                                   "duration": ch.get("duration"),
                                   "text": ch.get("text")})
        if not audio:
            raise RuntimeError("edge-tts returned no audio")
        out_path.write_bytes(bytes(audio))
        return boundaries

    def _synth_google(self, text, voice, out_path):
        lang = "zh-CN" if (voice or "").lower().startswith("zh") else "en"
        audio = bytearray()
        errors = []
        proxies = [self.proxy, None] if self.proxy else [None]
        for chunk in _split_tts(text):
            params = urllib.parse.urlencode(
                {"ie": "UTF-8", "client": "tw-ob", "tl": lang, "q": chunk})
            url = _GOOGLE_TTS + "?" + params
            for proxy in proxies:
                handlers = []
                if proxy:
                    handlers.append(urllib.request.ProxyHandler(
                        {"http": proxy, "https": proxy}))
                opener = urllib.request.build_opener(*handlers)
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                try:
                    with opener.open(req, timeout=30) as r:
                        data = r.read()
                    if not data:
                        raise RuntimeError("empty audio")
                    if not (data[:3] == b"ID3" or
                            (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)):
                        raise RuntimeError("response is not MP3")
                    audio += data
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append("google-tts: %s" % e)
            else:
                raise RuntimeError(" / ".join(errors[-2:]))
        if not audio:
            raise RuntimeError("google-tts returned no audio")
        out_path.write_bytes(bytes(audio))

    def _prune(self):
        files = sorted(self.cache_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        if len(files) <= self.max_files:
            return
        for old in files[:len(files) - self.max_files]:
            try:
                old.unlink(missing_ok=True)
                old.with_suffix(".json").unlink(missing_ok=True)
            except Exception:
                pass


def list_voices():
    """Curated voice list for the UI: all en-*, plus two zh-CN voices."""
    try:
        voices = asyncio.run(edge_tts.list_voices())
    except Exception:
        return list(_FALLBACK_VOICES)
    out = []
    for v in voices:
        name = v.get("ShortName", "")
        loc = v.get("Locale", "")
        if loc.startswith("en-"):
            ok = True
        elif name in _ZH_KEEP:
            ok = True
        else:
            ok = False
        if not ok:
            continue
        short = name.split("-", 2)[-1].replace("Neural", "").replace("Multilingual", " ML")
        out.append({"id": name, "label": "%s (%s)" % (short, loc), "locale": loc})

    def sort_key(v):
        vid, loc = v["id"], v["locale"]
        if loc == "en-US" and "Multilingual" in vid:
            r = 0
        elif loc == "en-US":
            r = 1
        elif loc == "en-GB":
            r = 2
        elif loc.startswith("en"):
            r = 3
        else:
            r = 4
        return (r, vid)

    out.sort(key=sort_key)
    return out or list(_FALLBACK_VOICES)
