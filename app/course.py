"""Course mode: unit mapping + seven-panel lesson generation + vocab bank.

Lesson JSON structure (rendered by the frontend course view):
{
  "unit_id", "title", "overview": {"questions": [...]},
  "sentences": [{"text", "structure", "translation"}],
  "vocab": [{"word", "pos", "meaning_cn", "collocations", "word_family", "example"}],
  "grammar": [{"point", "explain", "example"}],
  "paraphrase": [{"original", "alternative", "note"}],
  "exercises": [{"type", "question", "answer", "explain"}],
  "output": [{"task"}]
}
"""
import datetime as _dt
import re
import threading

from . import llm

BANK_COLUMNS = ["date", "word", "phonetic", "pos", "meaning_cn",
                "collocations", "word_family", "example", "source", "note"]

_BANK_LOCK = threading.RLock()


# ---------------- units ----------------

def build_units(doc):
    units = []
    cur = {"blocks": [], "words": 0, "heading": None}
    part_counter = {}

    def flush():
        if not cur["blocks"]:
            return
        h = cur["heading"] or "Front matter"
        n = part_counter.get(h, 0) + 1
        part_counter[h] = n
        title = h if n == 1 else f"{h}（第 {n} 部分）"
        units.append({"id": len(units), "title": title[:80],
                      "blocks": cur["blocks"][:], "words": cur["words"]})
        cur["blocks"] = []
        cur["words"] = 0

    for b in doc.get("blocks", []):
        k = b.get("kind")
        if k == "heading":
            if cur["blocks"]:
                flush()
            cur["heading"] = re.sub(r"^[IVXL]+\.\s*", "", b["text"]).strip()
            continue
        if k != "para":
            continue
        w = len(b.get("text", "").split())
        if cur["blocks"] and cur["words"] >= 280 and cur["words"] + w > 360:
            flush()
        cur["blocks"].append(b["i"])
        cur["words"] += w
    flush()
    return units


def unit_text(doc, unit):
    blocks = {b["i"]: b for b in doc.get("blocks", [])}
    parts = [blocks[i]["text"] for i in unit.get("blocks", [])
             if i in blocks and blocks[i].get("kind") == "para"]
    return "\n\n".join(parts)


# ---------------- lesson generation ----------------

LESSON_PROMPT = """You are an expert English teacher for a Chinese CS student. Create an intensive-reading lesson (\u96c5\u601d\u9605\u8bfb\u5f0f\u7cbe\u8bfb) from ONE segment of an English research paper.

Segment title: {title}
Segment text:
---
{text}
---

Return STRICT JSON only (no markdown fence), exactly this structure:
{{
 "overview": {{"questions": ["2-3 pre-reading comprehension questions (in Chinese)"]}},
 "sentences": [{{"text": "<verbatim hard sentence from the segment>", "structure": "<Chinese breakdown: main clause / subordinate clauses / modifiers>", "translation": "<Chinese translation>"}}],
 "vocab": [{{"word": "<IELTS-useful academic word, not pure technical jargon>", "pos": "...", "meaning_cn": "...", "collocations": "...", "word_family": "...", "example": "<short example>"}}],
 "grammar": [{{"point": "<grammar point>", "explain": "<Chinese explanation, the mechanism not the jargon>", "example": "<quote from segment>"}}],
 "paraphrase": [{{"original": "<phrase from segment>", "alternative": "<common paraphrase>", "note": "<Chinese note>"}}],
 "exercises": [{{"type": "tfng|cloze|translate", "question": "...", "answer": "...", "explain": "<Chinese>"}}],
 "output": [{{"task": "<production task in Chinese, e.g. paraphrase / retell in your own words>"}}]
}}

Requirements:
- sentences: 2-4 items (the hardest sentences); vocab: 6-10 items; grammar: 2-3; paraphrase: 3-5; exercises: 4-6 (at least one tfng, one cloze, one translate, all based on the segment); output: 1-2.
- Quoted English text must come verbatim from the segment.
- Focus on academic vocabulary + collocations, not trivial words. Chinese for all explanations."""


def generate_lesson(doc, unit, base_url, api_key, model, proxy=None,
                    effort="off", max_tokens=None):
    text = unit_text(doc, unit)
    if len(text) > 9000:
        text = text[:9000]
    data = llm.chat_json(base_url, api_key, model,
                         LESSON_PROMPT.format(title=unit["title"], text=text),
                         proxy=proxy, temperature=0.4,
                         max_tokens=max_tokens if max_tokens else 8192,
                         timeout=240, effort=effort)
    def as_list(key):
        value = data.get(key)
        return value if isinstance(value, list) else []

    overview = data.get("overview")
    lesson = {
        "unit_id": unit["id"],
        "title": str(data.get("title") or unit["title"]),
        "overview": overview if isinstance(overview, dict) else {},
        "sentences": as_list("sentences"),
        "vocab": as_list("vocab"),
        "grammar": as_list("grammar"),
        "paraphrase": as_list("paraphrase"),
        "exercises": as_list("exercises"),
        "output": as_list("output"),
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    return lesson


# ---------------- vocab bank ----------------

def _clean_cell(value) -> str:
    return str(value if value is not None else "").replace("\t", " ").replace("\n", " ").strip()


def _write_bank(path, rows):
    lines = ["\t".join(BANK_COLUMNS)]
    for row in rows:
        lines.append("\t".join(_clean_cell(row.get(c, "")) for c in BANK_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_bank(path):
    with _BANK_LOCK:
        rows = []
        if not path.exists():
            return rows
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2 or not parts[1].strip():
                continue
            row = {}
            for i, col in enumerate(BANK_COLUMNS):
                row[col] = parts[i] if i < len(parts) else ""
            rows.append(row)
        return rows


def add_bank_rows(path, rows):
    with _BANK_LOCK:
        existing = {r["word"].lower() for r in read_bank(path)}
        added = 0
        if not path.exists():
            path.write_text("\t".join(BANK_COLUMNS) + "\n", encoding="utf-8")
        elif path.stat().st_size and not path.read_bytes().endswith(b"\n"):
            with path.open("a", encoding="utf-8") as f:
                f.write("\n")
        with path.open("a", encoding="utf-8") as f:
            for r in rows:
                w = _clean_cell(r.get("word"))
                if not w or w.lower() in existing:
                    continue
                existing.add(w.lower())
                f.write("\t".join(_clean_cell(r.get(c, "")) for c in BANK_COLUMNS) + "\n")
                added += 1
        return added


def remove_bank_rows(path, words):
    wanted = {str(w).strip().lower() for w in words if str(w).strip()}
    with _BANK_LOCK:
        rows = read_bank(path)
        kept = [r for r in rows if r["word"].strip().lower() not in wanted]
        removed = len(rows) - len(kept)
        if removed:
            _write_bank(path, kept)
        return removed


def update_bank_row(path, word, patch):
    target = str(word or "").strip().lower()
    allowed = {"phonetic", "pos", "meaning_cn", "collocations",
               "word_family", "example", "source", "note"}
    if not isinstance(patch, dict):
        patch = {}
    with _BANK_LOCK:
        rows = read_bank(path)
        updated = None
        for row in rows:
            if row["word"].strip().lower() != target:
                continue
            for key, value in (patch or {}).items():
                if key in allowed:
                    row[key] = _clean_cell(value)
            updated = row
            break
        if updated is not None:
            _write_bank(path, rows)
        return updated


def lesson_rows(lesson, source):
    stamp = _dt.date.today().isoformat()
    rows = []
    for v in lesson.get("vocab", []):
        if not isinstance(v, dict) or not str(v.get("word") or "").strip():
            continue
        rows.append({"date": stamp, "word": v.get("word", ""),
                     "phonetic": v.get("phonetic", ""), "pos": v.get("pos", ""),
                     "meaning_cn": v.get("meaning_cn", ""),
                     "collocations": v.get("collocations", ""),
                     "word_family": v.get("word_family", ""),
                     "example": v.get("example", ""),
                     "source": source, "note": ""})
    return rows
