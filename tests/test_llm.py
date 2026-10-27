import pytest

from app import llm


def test_chat_json_tolerates_fence(monkeypatch):
    def fake_chat(*args, **kwargs):
        return '```json\n{"a": 1}\n```'

    monkeypatch.setattr(llm, "chat", fake_chat)
    assert llm.chat_json("u", "k", "m", "prompt") == {"a": 1}


def test_chat_json_raises_on_bad_json(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "not json")
    with pytest.raises(llm.LLMError):
        llm.chat_json("u", "k", "m", "prompt")


def test_chat_json_requires_object(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "[1, 2, 3]")
    with pytest.raises(llm.LLMError):
        llm.chat_json("u", "k", "m", "prompt")


def test_refine_sentence_shapes(monkeypatch):
    def fake_chat_json(*args, **kwargs):
        return {"chunks": [
            {"text": "We water", "label": "主语", "note": ""},
            {"text": "the plants", "label": "宾语"},
        ], "summary": "s"}

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    out = llm.refine_sentence("u", "k", "m", "We water the plants.")
    assert out["summary"] == "s"
    assert out["chunks"][1]["note"] == ""
