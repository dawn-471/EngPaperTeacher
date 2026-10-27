"""Sentence chunking (语块划分) via spaCy dependency parsing.

Splits each sentence into pedagogically useful sense groups (语块/意群):
- clause segmentation first (subordinate clauses as their own pieces),
- then subject / predicate / object / adverbial / prepositional-phrase spans,
- glue handling (cc, mark, punct attach to neighbors),
- short pieces (<=5 tokens) are kept whole.

Output per sentence: [{"text", "label", "key", "start", "end"}], offsets are
character offsets into the input string.
"""
import os
from typing import List

import spacy

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


CLAUSE_DEPS = {"ROOT", "ccomp", "xcomp", "advcl", "acl", "relcl", "conj", "parataxis"}
VERBISH = ("VERB", "AUX")
COPULA_LEMMAS = {"be", "remain", "seem", "become", "appear", "stay", "look"}

_CATEGORY = {
    "nsubj": "subject", "nsubjpass": "subject", "csubj": "subject", "csubjpass": "subject",
    "dobj": "object", "dative": "object",
    "attr": "complement", "acomp": "complement", "oprd": "complement",
    "prep": "prep",
    "advmod": "adverbial", "npadvmod": "adverbial", "agent": "adverbial", "tmod": "adverbial",
    "ccomp": "clause", "xcomp": "clause", "advcl": "clause", "acl": "clause", "relcl": "clause",
    "aux": "verbaux", "auxpass": "verbaux", "neg": "verbaux", "prt": "verbaux", "expl": "verbaux",
    "cc": "glue", "mark": "glue",
    "punct": "punct",
}

CN_LABEL = {
    "subject": "主语", "verb": "谓语", "object": "宾语", "complement": "表语",
    "adverbial": "状语", "prep": "介词短语", "clause": "从句",
    "sentence_piece": "分句", "glue": "连接", "other": "其他",
}


def _paren_depth(toks) -> int:
    depth = 0
    for t in toks:
        if t.text in ("(", "["):
            depth += 1
        elif t.text in (")", "]"):
            depth -= 1
    return depth


def _is_clause_root(t) -> bool:
    return t.pos_ in VERBISH and t.dep_ in CLAUSE_DEPS


def _category(tok) -> str:
    cur = tok
    hops = 0
    while hops < 4:
        cat = _CATEGORY.get(cur.dep_)
        if cat:
            return cat
        if cur.head.i == cur.i:
            break
        cur = cur.head
        hops += 1
    return "other"


def chunk_text(text: str) -> List[dict]:
    nlp = _get_nlp()
    out = []
    for off, seg in _pre_split(text):
        doc = nlp(seg)
        for sent in doc.sents:
            for c in _chunk_sentence(sent, seg):
                c["start"] += off
                c["end"] += off
                out.append(c)
    out.sort(key=lambda c: c["start"])
    return out


def _pre_split(text: str):
    """Split at strong clause punctuation so each clause is parsed cleanly."""
    segs = []
    start = 0
    for i, ch in enumerate(text):
        if ch in (";", ":"):
            segs.append((start, text[start:i + 1]))
            start = i + 1
    if start < len(text):
        segs.append((start, text[start:]))
    return [(o, s) for o, s in segs if s.strip()]


def _mk(toks, kind, full_text):
    toks = sorted(toks, key=lambda t: t.i)
    start = toks[0].idx
    end = toks[-1].idx + len(toks[-1].text)
    return {"text": full_text[start:end], "label": CN_LABEL.get(kind, "其他"),
            "key": kind, "start": start, "end": end}


_DEBUG = bool(os.environ.get("EPT_CHUNK_DEBUG"))


def _trace(msg, spans):
    if not _DEBUG:
        return
    print("[stage]", msg)
    for s in spans:
        print("    ", s["kind"], "|", " ".join(t.text for t in s["toks"]))


def _chunk_sentence(sent, full_text):
    toks = [t for t in sent if not t.is_space]
    if not toks:
        return []
    sent_root = next((t for t in toks if t.dep_ == "ROOT"), None)
    roots = [t for t in toks if _is_clause_root(t)]
    if not roots or sent_root is None or sent_root.pos_ not in VERBISH:
        return _comma_split(toks, full_text)
    root_ids = {t.i for t in roots}

    def owner(t):
        cur = t
        while True:
            if cur.i in root_ids:
                return cur.i
            if cur.head.i == cur.i:
                return roots[0].i
            cur = cur.head

    groups = {}
    for t in toks:
        groups.setdefault(owner(t), []).append(t)

    spans = []
    for rid in sorted(groups, key=lambda k: groups[k][0].i):
        piece = groups[rid]
        root = next(t for t in piece if t.i == rid)
        spans.extend(_piece_spans(root, piece))
    spans = [s for s in spans if s["toks"]]
    for s in spans:
        s["toks"] = sorted(s["toks"], key=lambda t: t.i)
    _trace("piece spans", spans)

    # fold pure glue / punct / single-other spans into neighbors (as units)
    changed = True
    while changed:
        changed = False
        spans.sort(key=lambda s: s["toks"][0].i)
        for i, s in enumerate(spans):
            merge_to = None
            if s["kind"] == "glue":
                merge_to = spans[i + 1] if i + 1 < len(spans) else (spans[i - 1] if i > 0 else None)
            elif s["kind"] == "punct" or (len(s["toks"]) == 1 and s["kind"] == "other"):
                merge_to = spans[i - 1] if i > 0 else (spans[i + 1] if i + 1 < len(spans) else None)
            if merge_to is not None and merge_to is not s:
                merge_to["toks"] = sorted(merge_to["toks"] + s["toks"], key=lambda t: t.i)
                spans.pop(i)
                changed = True
                break

    # residual single tokens attach to the nearest span
    covered = {t.i for s in spans for t in s["toks"]}

    def attach(tok):
        prev = nxt = None
        for s in spans:
            if s["toks"][-1].i < tok.i:
                prev = s
            elif s["toks"][0].i > tok.i and nxt is None:
                nxt = s
        if tok.is_punct:
            target = prev or nxt
        elif tok.dep_ in ("cc", "mark"):
            target = nxt or prev
        else:
            target = nxt or prev
        if target is None:
            spans.append({"toks": [tok], "kind": _category(tok)})
        else:
            target["toks"] = sorted(target["toks"] + [tok], key=lambda t: t.i)

    for t in toks:
        if t.i not in covered:
            attach(t)

    # safety de-dup
    seen = set()
    for s in spans:
        keep = []
        for t in s["toks"]:
            if t.i not in seen:
                seen.add(t.i)
                keep.append(t)
        s["toks"] = keep
    spans = [s for s in spans if s["toks"]]
    _trace("after fold+attach", spans)

    def sorted_spans():
        spans.sort(key=lambda s: s["toks"][0].i)

    def adj(a, b):
        return a["toks"][-1].i + 1 == b["toks"][0].i

    # absorb single-token adverbials adjacent to any predicate
    changed = True
    while changed:
        changed = False
        sorted_spans()
        for vspan in [s for s in spans if s["kind"] == "verb"]:
            for i, s in enumerate(spans):
                if s is vspan or s["kind"] != "adverbial" or len(s["toks"]) != 1:
                    continue
                if (s["toks"][-1].i + 1 == vspan["toks"][0].i
                        or vspan["toks"][-1].i + 1 == s["toks"][0].i):
                    vspan["toks"] = sorted(vspan["toks"] + s["toks"], key=lambda t: t.i)
                    spans.pop(i)
                    changed = True
                    break
            if changed:
                break

    # copula: single be-like verb merges into an adjacent complement
    sorted_spans()
    for vspan in [s for s in spans if s["kind"] == "verb"]:
        if len(vspan["toks"]) == 1 and vspan["toks"][0].lemma_ in COPULA_LEMMAS:
            idx = spans.index(vspan)
            if (idx + 1 < len(spans) and adj(vspan, spans[idx + 1])
                    and spans[idx + 1]["kind"] in ("complement", "object", "prep", "adverbial")):
                nxt = spans[idx + 1]
                nxt["toks"] = sorted(nxt["toks"] + vspan["toks"], key=lambda t: t.i)
                spans.pop(idx)
                break

    # subject + predicate (+ object) merge when all short and adjacent
    changed = True
    while changed:
        changed = False
        sorted_spans()
        for i in range(len(spans) - 2):
            a, b, c = spans[i], spans[i + 1], spans[i + 2]
            if (a["kind"] == "subject" and b["kind"] == "verb" and c["kind"] == "object"
                    and len(a["toks"]) + len(b["toks"]) + len(c["toks"]) <= 6
                    and adj(a, b) and adj(b, c)):
                a["toks"] = sorted(a["toks"] + b["toks"] + c["toks"], key=lambda t: t.i)
                a["kind"] = "sentence_piece"
                spans.pop(i + 2)
                spans.pop(i + 1)
                changed = True
                break
        if changed:
            continue
        for i in range(len(spans) - 1):
            a, b = spans[i], spans[i + 1]
            if (a["kind"] == "subject" and b["kind"] == "verb"
                    and len(a["toks"]) <= 2 and len(b["toks"]) <= 2 and adj(a, b)):
                a["toks"] = sorted(a["toks"] + b["toks"], key=lambda t: t.i)
                a["kind"] = "sentence_piece"
                spans.pop(i + 1)
                changed = True
                break

    # coordination merge (adjacent, same category)
    changed = True
    while changed:
        changed = False
        sorted_spans()
        for i in range(len(spans) - 1):
            a, b = spans[i], spans[i + 1]
            if (a["kind"] == b["kind"] and a["kind"] in ("object", "complement", "prep")
                    and adj(a, b)):
                a["toks"] = sorted(a["toks"] + b["toks"], key=lambda t: t.i)
                spans.pop(i + 1)
                changed = True
                break

    _trace("after merges", spans)

    # continuation fragments that begin with a coordinating conjunction
    changed = True
    while changed:
        changed = False
        sorted_spans()
        for i in range(1, len(spans)):
            a, b = spans[i - 1], spans[i]
            first = b["toks"][0]
            if (first.dep_ == "cc" and first.text.lower() in ("and", "or", "nor")
                    and b["kind"] in ("other", "prep", "object", "complement", "adverbial")
                    and a["kind"] in ("prep", "object", "complement", "adverbial")
                    and adj(a, b)):
                a["toks"] = sorted(a["toks"] + b["toks"], key=lambda t: t.i)
                spans.pop(i)
                changed = True
                break

    # keep parenthetical "( ... )" / "[ ... ]" runs within one chunk
    changed = True
    while changed:
        changed = False
        sorted_spans()
        for i, s in enumerate(spans):
            if _paren_depth(s["toks"]) <= 0:
                continue
            j = i + 1
            while _paren_depth(s["toks"]) > 0 and j < len(spans) and adj(s, spans[j]):
                s["toks"] = sorted(s["toks"] + spans[j]["toks"], key=lambda t: t.i)
                spans.pop(j)
                changed = True
            if changed:
                break

    # long spans: split at internal preposition boundaries
    final = []
    for s in spans:
        tks = s["toks"]
        if len(tks) >= 8:
            ids = {t.i for t in tks}
            cuts = []
            depth = 0
            for t in tks[1:]:
                if t.text in (")", "]"):
                    depth -= 1
                if depth == 0 and t.dep_ == "prep" and all(x.i in ids for x in t.subtree):
                    cuts.append(t.i)
                if t.text in ("(", "["):
                    depth += 1
            if cuts:
                cur, first = [], True
                for t in tks:
                    if t.i in cuts and cur:
                        final.append({"toks": cur, "kind": s["kind"] if first else "prep"})
                        first = False
                        cur = []
                    cur.append(t)
                if cur:
                    final.append({"toks": cur, "kind": s["kind"] if first else "prep"})
                continue
        final.append(s)

    # contiguous-run split, then build chunks
    out = []
    for s in final:
        run = [s["toks"][0]]
        for t in s["toks"][1:]:
            if t.i == run[-1].i + 1:
                run.append(t)
            else:
                out.append({"toks": run, "kind": s["kind"]})
                run = [t]
        out.append({"toks": run, "kind": s["kind"]})
    chunks = [_mk(s["toks"], s["kind"], full_text) for s in out if s["toks"]]
    chunks.sort(key=lambda c: c["start"])
    return chunks


def _comma_split(toks, full_text):
    """Fallback for sentences spaCy cannot parse reliably: split at punctuation."""
    groups, cur = [], []
    for t in toks:
        cur.append(t)
        if t.text in (",", ";", ":", "—"):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    merged = []
    for g in groups:
        if merged and len(merged[-1]) <= 2:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    return [_mk(g, "sentence_piece", full_text) for g in merged]


def _piece_spans(root, piece):
    piece_ids = {t.i for t in piece}
    toks = sorted(piece, key=lambda t: t.i)
    if len(piece) <= 5 or (root.dep_ == "relcl" and len(piece) <= 12):
        kind = "clause" if root.dep_ in ("ccomp", "xcomp", "advcl", "acl", "relcl") else "sentence_piece"
        keep, extras = [], []
        for t in toks:
            if t.head.i == root.i and t.dep_ in ("cc", "mark", "punct"):
                extras.append(t)
            else:
                keep.append(t)
        out = [{"toks": keep, "kind": kind}] if keep else []
        for t in extras:
            out.append({"toks": [t], "kind": "glue" if t.dep_ in ("cc", "mark") else "punct"})
        return out

    spans = []
    for c in root.children:
        if c.i not in piece_ids:
            continue
        sub = [t for t in c.subtree if t.i in piece_ids]
        if not sub:
            continue
        cat = _category(c)
        if cat in ("glue", "punct", "verbaux"):
            spans.append({"toks": sub, "kind": cat})
            continue
        last = sub[-1]
        if last.dep_ == "cc":
            tail = [t for t in sub if t.i >= last.i or t.head.i == last.i]
            tail_ids = {t.i for t in tail}
            base = [t for t in sub if t.i not in tail_ids]
            if base:
                spans.append({"toks": base, "kind": cat})
            spans.append({"toks": tail, "kind": "glue"})
        else:
            spans.append({"toks": sub, "kind": cat})

    aux = [t for s in spans if s["kind"] == "verbaux" for t in s["toks"]]
    spans = [s for s in spans if s["kind"] != "verbaux"]
    spans.append({"toks": sorted([root] + aux, key=lambda t: t.i), "kind": "verb"})
    return spans
