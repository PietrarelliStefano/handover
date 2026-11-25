"""Frasi, battute e take ripetute tra file diversi (§6.2.2–3, rev. 7). Funzioni pure.

Regole validate nello spike 01 (docs/spike-01.md):
- frasi: punteggiatura finale o pausa > 0,7 s; frammenti di 1–2 parole uniti alla frase precedente;
- frasi lunghe dette d'un fiato spezzate dove ci si allineano frasi di altre take
  (almeno due frasi, oppure una pausa ≥ 0,3 s);
- stessa battuta se similarità ≥ 0,7 (anche sui caratteri per le frasi fino a 6 parole)
  oppure stesso attacco (prime 8 parole, ≤ 2 errori);
- take interrotta agganciata alla battuta con cui condivide l'inizio, senza fare da ponte;
- ordine delle take: numero progressivo del file.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

from handover.video.text import align, normalize_words

SIM = 0.7
OPENING, OPENING_ERR = 8, 2
PREFIX_ERR = 0.30
GAP_S = 0.7
LONG = 12
SPLIT_ERR = 0.30
SPLIT_SUPPORT = 2
SPLIT_PAUSE_S = 0.3
MIN_PIECE = 3
MIN_TOKENS = 3
WINDOW_MIN = 20.0
TERMINAL = (".", "?", "!")


def clip_number(name: str) -> int:
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else 10**9


def similarity(a: list[str], b: list[str]) -> float:
    r = SequenceMatcher(None, a, b, autojunk=False).ratio()
    if min(len(a), len(b)) <= 6:
        r = max(r, SequenceMatcher(None, " ".join(a), " ".join(b), autojunk=False).ratio())
    return r


def same_opening(a: list[str], b: list[str]) -> bool:
    if min(len(a), len(b)) < OPENING:
        return False
    al = align(a[:OPENING], b[: OPENING + 2], fit=True)
    return al.hyp_start <= 1 and al.errors <= OPENING_ERR


def prefix_fit(short: list[str], long: list[str]) -> float | None:
    if len(short) < 4 or len(long) <= len(short):
        return None
    al = align(short, long[: len(short) + 3], fit=True)
    if al.hyp_start > 1:
        return None
    return al.errors / len(short)


def make_phrase(clip: str, words: list[dict], complete: bool | None = None) -> dict | None:
    toks = normalize_words([w["w"] for w in words])
    if not toks:
        return None
    text = " ".join(w["w"] for w in words).strip()
    return {"clip": clip, "words": words, "toks": [t for t, _ in toks], "tok_word": [i for _, i in toks],
            "start": words[0]["start"], "end": words[-1]["end"], "text": text,
            "complete": text.rstrip().endswith(TERMINAL) if complete is None else complete}


def segment(clip: str, transcript: dict) -> list[dict]:
    words = [w for s in transcript["segments"] for w in s["words"]]
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w["w"].rstrip().endswith(TERMINAL) or nxt["start"] - w["end"] > GAP_S:
            groups.append(cur)
            cur = []
    out: list[dict] = []
    for ws in groups:
        ph = make_phrase(clip, ws)
        if ph is None:
            continue
        if out and len(ph["toks"]) < MIN_TOKENS and ph["start"] - out[-1]["end"] < 1.5:
            out[-1] = make_phrase(clip, out[-1]["words"] + ws)
            continue
        out.append(ph)
    return out


def split_long(phrases: list[dict]) -> list[dict]:
    out = []
    for p in phrases:
        n = len(p["toks"])
        if n < LONG:
            out.append(p)
            continue
        support: dict[int, set[int]] = {}
        for k, s in enumerate(phrases):
            if s is p or not (4 <= len(s["toks"]) <= 0.8 * n):
                continue
            al = align(s["toks"], p["toks"], fit=True)
            if al.errors / len(s["toks"]) <= SPLIT_ERR:
                for c in (al.hyp_start, al.hyp_end):
                    support.setdefault(c, set()).add(k)

        def pause_at(c: int) -> float:
            return p["words"][p["tok_word"][c]]["start"] - p["words"][p["tok_word"][c - 1]]["end"]

        kept: list[int] = []
        for c in sorted(support):
            if not (MIN_PIECE <= c <= n - MIN_PIECE):
                continue
            ids = set().union(*(support.get(x, set()) for x in (c - 1, c, c + 1)))
            if len(ids) < SPLIT_SUPPORT and pause_at(c) < SPLIT_PAUSE_S:
                continue
            if not kept or c - kept[-1] >= MIN_PIECE:
                kept.append(c)
        if not kept:
            out.append(p)
            continue
        bounds = [0] + kept + [n]
        for k, (a, b) in enumerate(zip(bounds, bounds[1:])):
            wa = p["tok_word"][a]
            wb = p["tok_word"][b] if b < n else len(p["words"])
            if wb <= wa:
                continue
            last = k == len(bounds) - 2
            piece = make_phrase(p["clip"], p["words"][wa:wb], complete=None if last else True)
            if piece:
                out.append(piece)
    return out


def find_battute(transcripts: dict[str, dict], clip_times: dict[str, datetime | None] | None = None,
                 window_min: float = WINDOW_MIN) -> list[dict]:
    """transcripts: clip → trascrizione (solo A-roll). Restituisce le battute in ordine di ripresa,
    ciascuna con le take in ordine di ripresa."""
    clip_times = clip_times or {}
    phrases: list[dict] = []
    for clip in sorted(transcripts, key=clip_number):
        phrases += segment(clip, transcripts[clip])
    for _ in range(2):
        phrases = split_long(phrases)
    for p in phrases:
        t0 = clip_times.get(p["clip"])
        p["abs"] = t0 + timedelta(seconds=p["start"]) if t0 else None
    phrases.sort(key=lambda p: (clip_number(p["clip"]), p["clip"], p["start"]))
    for i, p in enumerate(phrases):
        p["id"] = i

    parent = list(range(len(phrases)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    win = window_min * 60

    def close(a: dict, b: dict) -> bool:
        return not (a["abs"] and b["abs"] and abs((b["abs"] - a["abs"]).total_seconds()) > win)

    eligible = [p for p in phrases if len(p["toks"]) >= MIN_TOKENS]
    linked: set[int] = set()
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            if close(a, b) and (similarity(a["toks"], b["toks"]) >= SIM or same_opening(a["toks"], b["toks"])):
                parent[find(a["id"])] = find(b["id"])
                linked.update((a["id"], b["id"]))
    for s in eligible:
        if s["id"] in linked:
            continue
        best = None
        for l in eligible:
            if l is s or not close(s, l):
                continue
            e = prefix_fit(s["toks"], l["toks"])
            if e is None:
                e = prefix_fit(l["toks"], s["toks"])
            if e is not None and e <= PREFIX_ERR and (best is None or e < best[0]):
                best = (e, l)
        if best:
            parent[find(s["id"])] = find(best[1]["id"])

    groups: dict[int, list[dict]] = {}
    for p in phrases:
        groups.setdefault(find(p["id"]), []).append(p)
    battute = []
    for n, g in enumerate(sorted(groups.values(), key=lambda g: g[0]["id"]), 1):
        battute.append({"id": f"b{n}", "takes": [
            {"take": f"t{p['id'] + 1}", "clip": p["clip"], "start": round(p["start"], 3), "end": round(p["end"], 3),
             "text": p["text"], "complete": p["complete"], "n_words": len(p["toks"]), "words": p["words"]}
            for p in g]})
    return battute


def heuristic_pick(battuta: dict) -> str:
    """Ultima take completa e lunga almeno l'80% della più lunga (fallback senza LLM)."""
    takes = battuta["takes"]
    longest = max(t["n_words"] for t in takes)
    cands = [t for t in takes if t["complete"] and t["n_words"] >= 0.8 * longest] or takes
    return cands[-1]["take"]
