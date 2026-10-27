import json

from app.translate import Translator


GOOGLE_PAYLOAD = json.dumps(
    [[["菜园供应新鲜蔬菜。", "The garden supplies fresh vegetables.", None, None, 3]],
     None, "en", None, None, None, None, []],
    ensure_ascii=False,
)


def test_google_at_client_parses(monkeypatch):
    calls = []

    def fake_fetch(self, url):
        calls.append(url)
        assert "client=at" in url
        return GOOGLE_PAYLOAD

    monkeypatch.setattr(Translator, "_fetch", fake_fetch)
    t = Translator(proxy=None)
    res = t.translate("The garden supplies fresh vegetables.")
    assert res == {"ok": True, "source": "google",
                   "text": "菜园供应新鲜蔬菜。"}
    assert len(calls) == 1


def test_mymemory_fallback_and_cache(monkeypatch):
    payload = json.dumps(
        {"responseData": {"translatedText": "回退译文"}},
        ensure_ascii=False,
    )

    def fake_fetch(self, url):
        return payload

    def fail_google(self, text, tl="zh-CN"):
        raise RuntimeError("google down")

    monkeypatch.setattr(Translator, "_fetch", fake_fetch)
    monkeypatch.setattr(Translator, "google", fail_google)
    t = Translator(proxy=None)
    res = t.translate("hello")
    assert res == {"ok": True, "source": "mymemory", "text": "回退译文"}
    again = t.translate("hello")
    assert again == res


def test_all_providers_fail(monkeypatch):
    def fail(self, *args, **kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr(Translator, "_fetch", lambda self, url: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr("app.translate.time.sleep", lambda _s: None)
    t = Translator(proxy=None)
    res = t.translate("hello")
    assert res["ok"] is False
    assert res["errors"]
