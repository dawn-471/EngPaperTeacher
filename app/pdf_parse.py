"""PDF -> structured blocks: title / meta / headings / paragraphs / sentences.

Verified against two-column LaTeX papers:
- PyMuPDF natural block order keeps two-column reading order for LaTeX papers.
- Font-size filter removes figure/table label fragments (captions/headings kept).
- Line-break hyphens are re-joined; abbreviations and decimals are protected
  during sentence splitting.
- Two-column paragraph continuations (blocks starting lowercase) merge back.
- Everything after the REFERENCES heading is marked as kind="ref".
"""
import re
from collections import Counter
from pathlib import Path

import pymupdf

_ABBREV = [
    "e.g", "i.e", "et al", "etc", "vs", "cf", "Fig", "Figs", "Eq", "Eqs",
    "Sec", "Sect", "Ref", "Refs", "No", "Vol", "pp", "p", "approx", "ca",
    "Dr", "Mr", "Ms", "Prof", "Inc", "Ltd", "al", "resp", "viz", "Ch",
    "Tab", "arXiv", "J", "Proc", "Conf", "Tech", "Rep", "Univ", "Dept",
]


def _protect(text: str) -> str:
    for a in _ABBREV:
        text = re.sub(r"(?<![A-Za-z])" + re.escape(a) + r"\.", a + "<D>", text)
    text = re.sub(r"(\d)\.(\d)", r"\1<D>\2", text)
    return text


def _restore(text: str) -> str:
    return text.replace("<D>", ".")


def split_sentences(text: str) -> list:
    t = _protect(text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])", t)
    out = []
    for p in parts:
        p = _restore(p).strip()
        if p:
            out.append(p)
    return out


def normalize_block(text: str) -> str:
    t = text.replace("\u00ad", "")
    t = re.sub(r"(?<=[A-Za-z])-\n(?=[a-z])", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


_HEAD_ROMAN = re.compile(r"^(?:[IVXL]+)\.\s+[A-Z]")
_HEAD_LETTER = re.compile(r"^[A-Z]\.\s+[A-Z][a-zA-Z\-]")
_CAPTION_RE = re.compile(r"^(?:Fig\.|Figure\s*\d|TABLE|Table\s+[IVX0-9]|Algorithm\s+\d)")
_REF_LINE_RE = re.compile(r"^\[\d+\]")
_SPECIAL_HEADINGS = ("ABSTRACT", "Abstract", "REFERENCES", "References",
                     "Acknowledgment", "ACKNOWLEDGMENT", "Index Terms")


def _looks_heading(t: str) -> bool:
    if not t or len(t) > 72:
        return False
    if _HEAD_ROMAN.match(t) or _HEAD_LETTER.match(t):
        return True
    if t in _SPECIAL_HEADINGS:
        return True
    return False


def _alpha_ratio(t: str) -> float:
    letters = sum(1 for c in t if c.isalpha() or c.isspace())
    return letters / max(1, len(t))


def _keep_text(t: str) -> bool:
    """Reject short non-prose fragments (figure labels, table cells, axes)."""
    if _looks_heading(t) or _CAPTION_RE.match(t) or _REF_LINE_RE.match(t):
        return True
    if t.startswith("Abstract") or t.startswith("Index Terms"):
        return True
    if len(t) >= 70:
        return True
    words = re.findall(r"[A-Za-z]{3,}", t)
    if len(words) >= 5:
        return True
    if t.endswith(":") and len(words) >= 2:
        return True
    return False


def parse_pdf(path) -> dict:
    doc = pymupdf.open(str(path))
    weighted = Counter()
    pages = []
    for pi in range(doc.page_count):
        page = doc[pi]
        ph = page.rect.height
        d = page.get_text("dict")
        blocks = []
        for blk in d["blocks"]:
            if blk.get("type") != 0:
                continue
            lines = []
            sz = Counter()
            for line in blk["lines"]:
                parts = []
                for span in line["spans"]:
                    parts.append(span["text"])
                    n = len(span["text"].strip())
                    if n >= 2:
                        key = round(span["size"], 1)
                        sz[key] += n
                        weighted[key] += n
                lines.append("".join(parts))
            text = normalize_block("\n".join(lines))
            if not text:
                continue
            dom = sz.most_common(1)[0][0] if sz else 0.0
            x0, y0, x1, y1 = blk["bbox"]
            blocks.append({"page": pi + 1, "y0": y0, "x0": x0, "y1": y1,
                           "ph": ph, "text": text, "size": dom})
        pages.append(blocks)

    body_size = weighted.most_common(1)[0][0] if weighted else 0.0

    raw = []
    refs_mode = False
    for blocks in pages:
        for b in blocks:
            t = b["text"]
            # edge noise: page numbers / running heads (also after REFERENCES)
            if len(t) <= 4 and (b["y0"] < b["ph"] * 0.07 or b["y1"] > b["ph"] * 0.93):
                continue
            if re.fullmatch(r"\d{1,3}", t) and (b["y0"] < b["ph"] * 0.08
                                                or b["y1"] > b["ph"] * 0.92):
                continue
            if refs_mode:
                raw.append(b)
                continue
            # font-size filter: keep body text or larger; exceptions: captions/headings/refs/abstract
            if body_size and b["size"] and b["size"] < body_size * 0.92:
                tl = t.lower()
                if not (_looks_heading(t) or _CAPTION_RE.match(t) or _REF_LINE_RE.match(t)
                        or tl.startswith("abstract") or tl.startswith("index terms")):
                    continue
            # reject short junk fragments regardless of size; keep display-size
            # front-matter lines even when they are a short title fragment
            display_front = (b["page"] == 1 and b["y0"] < b["ph"] * 0.32
                             and body_size and b["size"] >= body_size * 1.05)
            if not _keep_text(t) and not (display_front and _alpha_ratio(t) > 0.6):
                continue
            # reject equation-garbage blocks (very low letter ratio)
            if len(t) > 8 and _alpha_ratio(t) < 0.5:
                continue
            raw.append(b)
            if t.strip().lower() == "references":
                refs_mode = True

    # page-1 title / meta detection: use relative font size instead of fixed
    # offsets so templates other than IEEE two-column still work
    page1 = [b for b in raw if b["page"] == 1]
    if page1:
        candidates = [b for b in page1
                      if b["size"] and b["y0"] < b["ph"] * 0.35
                      and 8 <= len(b["text"]) <= 300
                      and not _CAPTION_RE.match(b["text"])
                      and _alpha_ratio(b["text"]) > 0.6]
        max_size = max((b["size"] for b in candidates), default=0.0)
        title_found = False
        if max_size and (not body_size or max_size >= body_size * 1.05):
            threshold = max_size * 0.92
            for blk in page1:
                tl = blk["text"].strip().lower()
                if tl.startswith("abstract") or tl.startswith("index terms"):
                    break
                if blk["size"] >= threshold and not _CAPTION_RE.match(blk["text"]):
                    blk["kind"] = "title"
                    title_found = True
                elif title_found and blk["y0"] < blk["ph"] * 0.50 and len(blk["text"]) < 400:
                    blk["kind"] = "meta"
        if not title_found:
            first = next((b for b in page1
                          if b["y0"] < b["ph"] * 0.30
                          and not b["text"].strip().lower().startswith(("abstract", "index terms"))),
                         None)
            if first is not None:
                first["kind"] = "title"
    merged = []
    for blk in raw:
        k = blk.get("kind")
        if merged and k and merged[-1].get("kind") == k and k in ("title", "meta"):
            merged[-1]["text"] = merged[-1]["text"] + " " + blk["text"]
        else:
            merged.append(blk)
    raw = merged

    # merge two-column paragraph continuations (blocks starting lowercase)
    merged2 = []
    for blk in raw:
        t = blk["text"]
        if (merged2 and "kind" not in blk and re.match(r"^[a-z]", t)
                and merged2[-1].get("kind") not in ("title", "meta")):
            merged2[-1]["text"] = merged2[-1]["text"].rstrip() + " " + t
        else:
            merged2.append(blk)
    raw = merged2

    blocks = []
    in_refs = False
    for blk in raw:
        t = blk["text"]
        kind = blk.get("kind")
        if not kind:
            if _looks_heading(t):
                kind = "heading"
                if t.strip().lower() == "references":
                    in_refs = True
            elif in_refs:
                kind = "ref"
            else:
                kind = "para"
        item = {"i": len(blocks), "page": blk["page"], "kind": kind, "text": t}
        if kind == "para":
            item["sentences"] = split_sentences(t)
        blocks.append(item)

    sections = [{"block_index": b["i"], "title": b["text"]}
                for b in blocks if b["kind"] == "heading"]
    title = next((b["text"] for b in blocks if b["kind"] == "title"), Path(path).stem)
    out = {
        "page_count": doc.page_count,
        "title": title,
        "blocks": blocks,
        "sections": sections,
    }
    doc.close()
    return out
