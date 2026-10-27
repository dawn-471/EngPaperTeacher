"""ECDICT offline dictionary lookup (stardict.db)."""
import re
import sqlite3
import threading


class ECDICT:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def lookup(self, word: str):
        w = (word or "").replace("\u2019", "'").lower()
        w = re.sub(r"^[^a-z']+|[^a-z']+$", "", w)
        if not w:
            return None
        with self._lock:
            for cand in self._candidates(w):
                row = self.conn.execute(
                    "SELECT word, phonetic, translation, definition, pos, collins, "
                    "oxford, tag, exchange FROM stardict WHERE word = ? LIMIT 1",
                    (cand,)).fetchone()
                if row:
                    return self._fmt(row)
            for cand in self._candidates(w):
                row = self.conn.execute(
                    "SELECT word, phonetic, translation, definition, pos, collins, "
                    "oxford, tag, exchange FROM stardict WHERE sw = ? LIMIT 1",
                    (cand,)).fetchone()
                if row:
                    return self._fmt(row)
        return None

    @staticmethod
    def _candidates(w):
        cands = [w]
        if w.endswith("'s"):
            cands.append(w[:-2])
        if w.endswith("ies") and len(w) > 3:
            cands.append(w[:-3] + "y")
        if w.endswith("es") and len(w) > 3:
            cands.append(w[:-2])
        if w.endswith("s") and not w.endswith("ss"):
            cands.append(w[:-1])
        if w.endswith("ed"):
            cands += [w[:-2], w[:-1]]
            if len(w) > 4 and w[-3] == w[-4]:
                cands.append(w[:-3])
        if w.endswith("ing"):
            b = w[:-3]
            cands += [b, b + "e"]
            if len(w) > 5 and w[-4] == w[-5]:
                cands.append(w[:-4])
        if w.endswith("est"):
            cands += [w[:-3], w[:-2]]
        if w.endswith("er"):
            cands += [w[:-2], w[:-1]]
        if w.endswith("ly"):
            cands.append(w[:-2])
        seen, out = set(), []
        for c in cands:
            if c and c not in seen and len(c) >= 2:
                seen.add(c)
                out.append(c)
        return out

    @staticmethod
    def _fmt(row):
        return {
            "word": row["word"],
            "phonetic": row["phonetic"] or "",
            "translation": [ln for ln in (row["translation"] or "").split("\n") if ln.strip()],
            "definition": (row["definition"] or "").strip() or None,
            "pos": row["pos"] or "",
            "collins": row["collins"] or 0,
            "oxford": row["oxford"] or 0,
            "tags": (row["tag"] or "").split(),
            "exchange": row["exchange"] or "",
        }
