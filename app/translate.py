"""Free online translation (Google gtx + MyMemory) with fallbacks and retries."""
import html
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"


class Translator:
    def __init__(self, proxy: str | None = None, contact: str = "", timeout: int = 20):
        self.proxy = proxy or None
        self.contact = (contact or "").strip()
        self.timeout = timeout
        self._cache = OrderedDict()
        self._cache_max = 1000
        self._lock = threading.Lock()

    def _fetch(self, url: str) -> str:
        errors = []
        order = [self.proxy, None] if self.proxy else [None]
        for proxy in order:
            handlers = []
            if proxy:
                handlers.append(urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy}))
            opener = urllib.request.build_opener(*handlers)
            req = urllib.request.Request(url, headers={
                "User-Agent": _UA,
                "Accept": "*/*",
                "Referer": "https://translate.google.com/",
            })
            try:
                with opener.open(req, timeout=self.timeout) as r:
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                errors.append("HTTP %s%s" % (e.code, (": " + body) if body else ""))
            except Exception as e:  # noqa: BLE001
                errors.append("%s: %s" % (type(e).__name__, e))
        uniq = []
        for msg in errors:
            if msg not in uniq:
                uniq.append(msg)
        raise RuntimeError(" / ".join(uniq))

    def google(self, text: str, tl: str = "zh-CN") -> str:
        q = urllib.parse.quote(text)
        errors = []
        for client in ("at", "gtx"):
            url = ("https://translate.googleapis.com/translate_a/single?"
                   + urllib.parse.urlencode(
                       {"client": client, "sl": "en", "tl": tl, "dt": "t", "q": text})
                   if client == "gtx" else
                   "https://translate.googleapis.com/translate_a/single?"
                   "client=at&sl=en&tl=%s&dt=t&q=%s" % (urllib.parse.quote(tl), q))
            try:
                data = json.loads(self._fetch(url))
                segments = data[0] if isinstance(data, list) and data else []
                out = "".join(
                    seg[0] for seg in segments
                    if isinstance(seg, list) and seg and isinstance(seg[0], str))
                if out.strip():
                    return html.unescape(out.strip())
            except Exception as e:  # noqa: BLE001
                errors.append("google/%s: %s" % (client, e))
        raise RuntimeError(" / ".join(errors))

    def mymemory(self, text: str, tl: str = "zh-CN") -> str:
        params = {"q": text, "langpair": "en|" + tl}
        if self.contact:
            params["de"] = self.contact
        url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(params)
        data = json.loads(self._fetch(url))
        out = (data.get("responseData") or {}).get("translatedText") or ""
        out = html.unescape(out.strip())
        upper = out.upper()
        if out and not any(bad in upper for bad in (
                "PLEASE SELECT TWO DISTINCT LANGUAGES",
                "MYMEMORY WARNING", "QUOTA")):
            return out
        raise RuntimeError("unusable MyMemory response")

    def translate(self, text: str, tl: str = "zh-CN") -> dict:
        text = (text or "").strip()
        key = (text, tl)
        if not text:
            return {"ok": False, "source": None, "text": None, "errors": ["empty text"]}
        with self._lock:
            cached = self._cache.get(key)
            if cached:
                self._cache.move_to_end(key)
                return dict(cached)
        errors = []
        for name, fn in (("google", self.google), ("mymemory", self.mymemory)):
            for attempt in range(2):
                try:
                    out = fn(text, tl)
                    if out and out.strip():
                        res = {"ok": True, "source": name, "text": out.strip()}
                        with self._lock:
                            self._cache[key] = res
                            while len(self._cache) > self._cache_max:
                                self._cache.popitem(last=False)
                        return res
                except Exception as e:  # noqa: BLE001
                    errors.append("%s: %s" % (name, e))
                    if attempt == 0:
                        time.sleep(0.4)
        uniq = []
        for msg in errors:
            if msg not in uniq:
                uniq.append(msg)
        return {"ok": False, "source": None, "text": None, "errors": uniq}
