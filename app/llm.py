"""Minimal OpenAI-compatible LLM client (stdlib only).

Used for: sentence chunk refinement, model list fetching. API key is supplied
per request by the frontend and never persisted server-side.
"""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def _open(req, proxy=None, timeout=60):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def _call(url, api_key, payload=None, proxy=None, timeout=60):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": "Bearer " + (api_key or ""),
               "User-Agent": "EngPaperTeacher/0.1"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    return json.loads(_open(req, proxy=proxy, timeout=timeout))


def _call_fallback(url, api_key, payload=None, proxy=None, timeout=60):
    """Try proxy first (if configured), then direct; surface both errors."""
    errors = []
    order = [proxy, None] if proxy else [None]
    for p in order:
        try:
            return _call(url, api_key, payload, proxy=p, timeout=timeout)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            errors.append(f"HTTP {e.code}: {body}")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    uniq = []
    for msg in errors:
        if msg not in uniq:
            uniq.append(msg)
    raise LLMError(" / ".join(uniq))


def list_models(base_url, api_key, proxy=None):
    url = base_url.rstrip("/") + "/models"
    data = _call_fallback(url, api_key, proxy=proxy, timeout=30)
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def chat(base_url, api_key, model, messages, proxy=None,
         temperature=0.3, max_tokens=2500, timeout=120, effort="off"):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if "deepseek" in base_url.lower():
        # Thinking-mode switch (DeepSeek-specific). "off" is the safe default
        # for deterministic tasks (reasoning can eat the whole output budget
        # and return empty content); users can raise it in settings.
        if effort and effort != "off":
            payload["thinking"] = {"type": "enabled"}
            if effort in ("low", "high", "max"):
                payload["reasoning_effort"] = effort
        else:
            payload["thinking"] = {"type": "disabled"}
    last_err = None
    for _ in range(4):
        try:
            data = _call_fallback(url, api_key, payload=payload, proxy=proxy, timeout=timeout)
            break
        except LLMError as e:
            last_err = e
            text = str(e)
            if ("400" in text and ("thinking" in text or "reasoning_effort" in text)
                    and "thinking" in payload):
                payload.pop("thinking", None)
                payload.pop("reasoning_effort", None)
                continue
            if ("400" in text and "max_tokens" in text
                    and payload.get("max_tokens", 0) > 8192):
                payload["max_tokens"] = 8192
                continue
            if ("400" in text and "max_tokens" in text
                    and payload.get("max_tokens", 0) > 4096):
                payload["max_tokens"] = 4096
                continue
            raise
    else:
        raise last_err or LLMError("LLM request failed after retries")
    if not isinstance(data, dict):
        raise LLMError("unexpected response: " + json.dumps(data)[:300])
    try:
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        content = msg.get("content") or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected response: " + json.dumps(data)[:300])
    if not content.strip():
        usage = data.get("usage") or {}
        rlen = len(msg.get("reasoning_content") or "")
        raise LLMError(
            "LLM returned empty content (finish_reason=%s, reasoning_chars=%s, usage=%s)"
            % (choice.get("finish_reason"), rlen, json.dumps(usage)))
    return content


REFINE_PROMPT = """You are an English-learning assistant. Split the sentence below into \
teaching "sense groups" (\u8bed\u5757) for a Chinese learner of English (IELTS reading style).

Rules:
- Group words into coherent units: subject, predicate, object, adverbial, prepositional \
phrase, subordinate clause, connective.
- Keep original word order; every word must appear exactly once across all groups.
- Use 2-9 groups. Do not leave a single function word alone unless it is a connective.
- Labels must be one of: \u4e3b\u8bed, \u8c13\u8bed, \u5bbe\u8bed, \u8868\u8bed, \u72b6\u8bed, \u5b9a\u8bed, \u4ecb\u8bcd\u77ed\u8bed, \u4ece\u53e5, \u8fde\u63a5, \u5176\u4ed6.

Sentence: {sentence}

Return ONLY JSON (no markdown fence):
{{"chunks": [{{"text": "...", "label": "\u4e3b\u8bed", "note": "short Chinese grammar note, optional"}}], \
"summary": "one-sentence Chinese explanation of the main structure"}}"""


def chat_json(base_url, api_key, model, prompt, proxy=None,
              temperature=0.2, max_tokens=4000, timeout=180, effort="off"):
    """Send one user prompt; parse the reply as JSON (tolerates code fences)."""
    content = chat(base_url, api_key, model, [{"role": "user", "content": prompt}],
                   proxy=proxy, temperature=temperature, max_tokens=max_tokens,
                   timeout=timeout, effort=effort)
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        text = text[i:j + 1]
    try:
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"JSON parse failed: {e}; raw: {content[:200]}")
    if not isinstance(data, dict):
        raise LLMError("JSON root is not an object; raw: " + content[:200])
    return data


def refine_sentence(base_url, api_key, model, sentence, proxy=None,
                    effort="off", max_tokens=None):
    data = chat_json(base_url, api_key, model,
                     REFINE_PROMPT.format(sentence=sentence), proxy=proxy,
                     effort=effort, max_tokens=max_tokens if max_tokens else 4000)
    chunks = []
    raw_chunks = data.get("chunks")
    for c in raw_chunks if isinstance(raw_chunks, list) else []:
        if isinstance(c, dict) and c.get("text"):
            chunks.append({"text": str(c["text"]), "label": str(c.get("label", "")),
                           "note": str(c.get("note", ""))})
    return {"chunks": chunks, "summary": str(data.get("summary", ""))}
