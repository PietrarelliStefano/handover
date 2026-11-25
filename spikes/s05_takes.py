"""Spike 01 · passo 5: take ripetute tra file diversi (§6.2, punti 2–3), seconda versione.

    uv run python spikes/s05_takes.py [CLIP_DIR] [--variant turbo+vad] [--window-min 20]

1. Frasi: punteggiatura finale o pausa > 0,7 s.
2. Le frasi lunghe (≥ 12 parole, tipiche delle take dette d'un fiato senza punteggiatura) vengono
   spezzate dove ci si allineano le frasi delle altre take: le altre take fanno da guida.
3. Regola della specifica: similarità ≥ 0,7 sul testo normalizzato, entro la finestra temporale.
   Stesso attacco: take improvvisate della stessa battuta che iniziano uguali (prime 8 parole,
   ≤ 2 errori) anche se poi divergono.
   Take interrotte: una frase (≥ 4 parole) che coincide con l'inizio di un'altra (≤ 30% di errori)
   si aggancia alla battuta di quella, ma solo se non ha già altri legami: così una frase non può
   fare da ponte tra due battute diverse.
4. Take del reel: dalla mappa audio (s03b_reel_match), se c'è; altrimenti stima dal testo.
5. Per ogni battuta: le take candidate, quella del reel e quella dell'euristica "ultima take completa".
Scrive results/takes-<variante>.json.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from common import DEFAULT_CLIP_DIR, load_json, out_path, save_json, work_dir
from textnorm import align, normalize_tokens, normalize_words

SIM = 0.7          # §6.2.3
OPENING = 8
OPENING_ERR = 2
PREFIX_ERR = 0.30  # take interrotta: errori ammessi sull'inizio della frase più lunga
NEAR = 0.5
GAP_S = 0.7
LONG = 12
SPLIT_ERR = 0.30
SPLIT_SUPPORT = 2
SPLIT_PAUSE_S = 0.3
MIN_PIECE = 3
MIN_TOKENS = 3
IN_REEL_WER = 0.35


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def make_phrase(clip: str, words: list[dict], complete: bool | None = None) -> dict | None:
    toks = normalize_words([w["w"] for w in words])
    if not toks:
        return None
    text = " ".join(w["w"] for w in words).strip()
    return {"clip": clip, "words": words, "toks": [t for t, _ in toks], "tok_word": [i for _, i in toks],
            "start": words[0]["start"], "end": words[-1]["end"], "text": text,
            "complete": text.rstrip().endswith((".", "?", "!")) if complete is None else complete}


def segment(clip: str, tr: dict) -> list[dict]:
    words = [w for s in tr["segments"] for w in s["words"]]
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w["w"].rstrip().endswith((".", "?", "!")) or nxt["start"] - w["end"] > GAP_S:
            groups.append(cur)
            cur = []
    out: list[dict] = []
    for ws in groups:
        ph = make_phrase(clip, ws)
        if ph is None:
            continue
        # frammenti di 1–2 parole attaccati alla frase precedente se vicini
        if out and len(ph["toks"]) < MIN_TOKENS and ph["start"] - out[-1]["end"] < 1.5:
            out[-1] = make_phrase(clip, out[-1]["words"] + ws)
            continue
        out.append(ph)
    return out


def split_long(phrases: list[dict]) -> tuple[list[dict], list[dict]]:
    """Spezza le frasi lunghe nei punti in cui ci si allineano frasi più brevi di altre take."""
    out, log = [], []
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
            prev_w, next_w = p["words"][p["tok_word"][c - 1]], p["words"][p["tok_word"][c]]
            return next_w["start"] - prev_w["end"]

        # un taglio vale se ci cominciano o finiscono almeno due frasi diverse (±1 parola), oppure se
        # nella frase c'è una pausa vera: la fine di una sola take interrotta non basta
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
        pieces = []
        for k, (a, b) in enumerate(zip(bounds, bounds[1:])):
            wa = p["tok_word"][a]
            wb = p["tok_word"][b] if b < n else len(p["words"])
            if wb <= wa:
                continue
            last = k == len(bounds) - 2
            piece = make_phrase(p["clip"], p["words"][wa:wb], complete=None if last else True)
            if piece:
                pieces.append(piece)
        out += pieces
        log.append({"clip": p["clip"], "start": round(p["start"], 2), "text": p["text"],
                    "pieces": [x["text"] for x in pieces]})
    return out, log


def prefix_fit(short: list[str], long: list[str]) -> float | None:
    """Errori relativi se `short` coincide con l'inizio di `long`, altrimenti None."""
    if len(short) < 4 or len(long) <= len(short):
        return None
    al = align(short, long[: len(short) + 3], fit=True)
    if al.hyp_start > 1:
        return None
    return al.errors / len(short)


def clip_number(name: str) -> int:
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else 10**9


def similarity(a: list[str], b: list[str]) -> float:
    """Similarità §6.2.3: sulle parole; per le frasi brevi anche sui caratteri, perché una lettera
    ("andiamolo" / "andiamola") vale una parola intera su tre."""
    r = SequenceMatcher(None, a, b, autojunk=False).ratio()
    if min(len(a), len(b)) <= 6:
        r = max(r, SequenceMatcher(None, " ".join(a), " ".join(b), autojunk=False).ratio())
    return r


def same_opening(a: list[str], b: list[str]) -> bool:
    """Take improvvisate della stessa battuta: stesso attacco (prime 8 parole, ≤ 2 errori)."""
    if min(len(a), len(b)) < OPENING:
        return False
    al = align(a[:OPENING], b[: OPENING + 2], fit=True)
    return al.hyp_start <= 1 and al.errors <= OPENING_ERR


def reel_overlap(take: dict, segs: list[dict]) -> float:
    dur = max(take["end"] - take["start"], 1e-3)
    ov = sum(max(0.0, min(take["end"], s["clip_end"]) - max(take["start"], s["clip_start"]))
             for s in segs if s["clip"] == take["clip"])
    return ov / dur


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--variant", default="turbo")
    ap.add_argument("--window-min", type=float, default=20.0)
    args = ap.parse_args()

    wd = work_dir(args.clip_dir)
    tdir = wd / "transcripts" / args.variant
    if not tdir.exists():
        raise SystemExit(f"Variante {args.variant} non trovata in {tdir.parent}")
    probe = {Path(p["file"]).stem: p for p in load_json(wd / "probe.json")}

    phrases: list[dict] = []
    for f in sorted(tdir.glob("*.json")):
        if f.stem != "REEL":
            phrases += segment(f.stem, load_json(f))
    split_log: list[dict] = []
    for _ in range(2):  # due passate: i pezzi nuovi possono guidare altri tagli
        phrases, log = split_long(phrases)
        split_log += log
    for p in phrases:
        t0 = parse_time(probe.get(p["clip"], {}).get("creation_time"))
        p["abs"] = t0 + timedelta(seconds=p["start"]) if t0 else None
    # ordine di ripresa: numero progressivo del file (Z50_6405 prima di Z50_6406). Il creation_time
    # dei MOV non segue l'ordine di ripresa (primo giro dello spike); serve solo per la finestra temporale.
    phrases.sort(key=lambda p: (clip_number(p["clip"]), p["clip"], p["start"]))
    for i, p in enumerate(phrases):
        p["id"] = i

    parent = list(range(len(phrases)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    win = args.window_min * 60
    eligible = [p for p in phrases if len(p["toks"]) >= MIN_TOKENS]

    def close(a: dict, b: dict) -> bool:
        return not (a["abs"] and b["abs"] and abs((b["abs"] - a["abs"]).total_seconds()) > win)

    links, near, has_link = [], [], set()
    ratios: dict[tuple[int, int], float] = {}
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            if not close(a, b):
                continue
            r = similarity(a["toks"], b["toks"])
            ratios[(a["id"], b["id"])] = r
            rule = "spec" if r >= SIM else "stesso attacco" if same_opening(a["toks"], b["toks"]) else None
            if rule:
                parent[find(a["id"])] = find(b["id"])
                links.append({"a": a["id"], "b": b["id"], "ratio": round(r, 3), "rule": rule})
                has_link.update((a["id"], b["id"]))

    # take interrotte (o con un pezzo in più): una frase senza legami si aggancia alla battuta della
    # frase con cui condivide l'inizio; non avendo altri legami, non può fare da ponte
    for s in eligible:
        if s["id"] in has_link:
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
            links.append({"a": s["id"], "b": best[1]["id"], "prefix_err": round(best[0], 3), "rule": "interrotta"})

    for (ia, ib), r in ratios.items():
        if find(ia) != find(ib) and r >= NEAR:
            near.append({"a": ia, "b": ib, "ratio": round(r, 3)})

    reel_map = None
    if (wd / "results" / "reel_map.json").exists():
        reel_map = load_json(wd / "results" / "reel_map.json")["segments"]
    ref_tokens: list[str] = []
    for name in ("reference_manual.txt", "reference.txt"):
        rp = wd / "reel" / name
        if rp.exists():
            ref_tokens = normalize_tokens(" ".join(l.split("\t", 1)[-1] for l in rp.read_text().splitlines()))
            break

    groups: dict[int, list[dict]] = {}
    for p in phrases:
        groups.setdefault(find(p["id"]), []).append(p)
    battute = sorted(groups.values(), key=lambda g: g[0]["id"])

    out_b = []
    source = "audio" if reel_map is not None else ("testo" if ref_tokens else None)
    print(f"Variante {args.variant}: {len(phrases)} frasi ({len(split_log)} frasi lunghe spezzate), "
          f"{len(battute)} battute, {sum(1 for g in battute if len(g) > 1)} con più take. "
          f"Take del reel da: {source or 'non disponibile'}.\n")
    for n, g in enumerate(battute, 1):
        takes = []
        for p in g:
            t = {"phrase": p["id"], "clip": p["clip"], "start": round(p["start"], 2), "end": round(p["end"], 2),
                 "text": p["text"], "words": len(p["toks"]), "complete": p["complete"]}
            if reel_map is not None:
                t["reel_overlap"] = round(reel_overlap(t, reel_map), 2)
            elif ref_tokens and len(p["toks"]) >= MIN_TOKENS:
                al = align(p["toks"], ref_tokens, fit=True)
                t["reel_wer"] = round(al.errors / len(p["toks"]), 3)
                t["reel_score"] = sum(1 for o in al.ops if o[0] == "ok") - al.errors
            takes.append(t)
        longest = max(t["words"] for t in takes)
        cands = [t for t in takes if t["complete"] and t["words"] >= 0.8 * longest] or takes
        heur = cands[-1]["phrase"]  # ultima take completa (§6.2.4, senza LLM)
        reel_pick = None
        if reel_map is not None:
            inr = [t for t in takes if t["reel_overlap"] >= 0.5]
            reel_pick = max(inr, key=lambda t: t["reel_overlap"])["phrase"] if inr else None
        elif ref_tokens:
            inr = [t for t in takes if t.get("reel_wer") is not None and t["reel_wer"] <= IN_REEL_WER]
            reel_pick = max(inr, key=lambda t: (t["reel_score"], t["words"]))["phrase"] if inr else None
        out_b.append({"n": n, "takes": takes, "heuristic_pick": heur, "reel_pick": reel_pick})

        print(f"Battuta {n} · {len(takes)} take" + (" · nel reel" if reel_pick is not None else ""))
        for t in takes:
            marks = []
            if t["phrase"] == heur and len(takes) > 1:
                marks.append("euristica")
            if t["phrase"] == reel_pick:
                marks.append("reel")
            if not t["complete"]:
                marks.append("incompleta")
            print(f"   {t['clip']} {t['start']:6.2f}–{t['end']:6.2f} [{', '.join(marks)}]\n      «{t['text']}»")

    multi = [b for b in out_b if len(b["takes"]) > 1]
    judged = [b for b in multi if b["reel_pick"] is not None]
    agree = sum(1 for b in judged if b["reel_pick"] == b["heuristic_pick"])
    print(f"\nTake ripetute: {len(multi)} battute. Euristica = take del reel ({source}) in {agree}/{len(judged)} casi.")
    if split_log:
        print("\nFrasi lunghe spezzate:")
        for s in split_log:
            print(f"   {s['clip']}@{s['start']:.1f}: " + " | ".join(s["pieces"]))
    if near:
        print("\nCoppie quasi simili in battute diverse (possibili take mancate, da controllare):")
        for p in near:
            a, b = phrases[p["a"]], phrases[p["b"]]
            print(f"   {p['ratio']:.2f}  {a['clip']}@{a['start']:.1f} «{a['text']}»\n"
                  f"         {b['clip']}@{b['start']:.1f} «{b['text']}»")

    save_json(out_path(wd / "results" / f"takes-{args.variant}.json", args.clip_dir), {
        "variant": args.variant, "window_min": args.window_min, "phrases": len(phrases),
        "reel_source": source, "split": split_log, "battute": out_b, "links": links, "near_misses": near,
        "multi_take": len(multi), "heuristic_agree": agree, "heuristic_judged": len(judged),
    })


if __name__ == "__main__":
    main()
