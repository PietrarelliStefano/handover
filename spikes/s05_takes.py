"""Spike 01 · passo 5: take ripetute tra file diversi (§6.2, punti 2–3).

    uv run python spikes/s05_takes.py [CLIP_DIR] [--variant turbo] [--window-min 20]

1. Segmenta le trascrizioni in frasi (punteggiatura finale o pausa > 0,7 s).
2. Regola della specifica: frasi con similarità ≥ 0,7 sul testo normalizzato, entro una finestra
   temporale, sono take della stessa battuta. In più, regola estesa per le take interrotte:
   la frase più corta (≥ 4 parole) è contenuta nella più lunga con similarità ≥ 0,8.
3. Per ogni battuta stampa le take candidate, la take che compare nel reel (stima per
   allineamento con i sottotitoli) e quella che sceglierebbe l'euristica "ultima take completa".
4. Stampa le coppie quasi simili (0,5–0,7) da controllare a mano: sono le possibili take mancate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from common import DEFAULT_CLIP_DIR, load_json, out_path, save_json, work_dir
from textnorm import align, normalize_tokens

SIM = 0.7
PARTIAL = 0.8
NEAR = 0.5
GAP_S = 0.7
IN_REEL_WER = 0.35


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def segment(tr: dict) -> list[dict]:
    words = [w for s in tr["segments"] for w in s["words"]]
    phrases, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end = w["w"].rstrip().endswith((".", "?", "!"))
        if nxt is None or end or nxt["start"] - w["end"] > GAP_S:
            phrases.append(cur)
            cur = []
    out = []
    for ws in phrases:
        text = " ".join(w["w"] for w in ws).strip()
        toks = normalize_tokens(text)
        if not toks:
            continue
        # frammenti di 1–2 parole attaccati alla frase precedente se vicini
        if out and len(toks) < 3 and ws[0]["start"] - out[-1]["end"] < 1.5:
            out[-1]["text"] += " " + text
            out[-1]["toks"] += toks
            out[-1]["end"] = ws[-1]["end"]
            continue
        out.append({"start": ws[0]["start"], "end": ws[-1]["end"], "text": text, "toks": toks,
                    "complete": text.rstrip().endswith((".", "?", "!"))})
    return out


def partial_ratio(a: list[str], b: list[str]) -> float:
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) < 4:
        return 0.0
    best = 0.0
    for i in range(0, len(l) - len(s) + 1):
        best = max(best, SequenceMatcher(None, s, l[i:i + len(s)], autojunk=False).ratio())
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--variant", default="turbo")
    ap.add_argument("--window-min", type=float, default=20.0)
    args = ap.parse_args()

    wd = work_dir(args.clip_dir)
    tdir = wd / "transcripts" / args.variant
    probe = {Path(p["file"]).stem: p for p in load_json(wd / "probe.json")}

    phrases = []
    for f in sorted(tdir.glob("*.json")):
        if f.stem == "REEL":
            continue
        t0 = parse_time(probe.get(f.stem, {}).get("creation_time"))
        for ph in segment(load_json(f)):
            ph["clip"] = f.stem
            ph["abs"] = t0 + timedelta(seconds=ph["start"]) if t0 else None
            phrases.append(ph)
    # ordine cronologico assoluto; senza creation_time, per nome file
    phrases.sort(key=lambda p: (p["abs"].timestamp() if p["abs"] else float("inf"), p["clip"], p["start"]))
    for i, p in enumerate(phrases):
        p["id"] = i

    parent = list(range(len(phrases)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links, near = [], []
    win = args.window_min * 60
    for i, a in enumerate(phrases):
        for b in phrases[i + 1:]:
            if a["abs"] and b["abs"] and abs((b["abs"] - a["abs"]).total_seconds()) > win:
                continue
            if len(a["toks"]) < 3 or len(b["toks"]) < 3:
                continue
            r = SequenceMatcher(None, a["toks"], b["toks"], autojunk=False).ratio()
            pr = partial_ratio(a["toks"], b["toks"])
            rule = "spec" if r >= SIM else "interrotta" if pr >= PARTIAL else None
            pair = {"a": a["id"], "b": b["id"], "ratio": round(r, 3), "partial": round(pr, 3)}
            if rule:
                parent[find(a["id"])] = find(b["id"])
                links.append(dict(pair, rule=rule))
            elif max(r, pr) >= NEAR:
                near.append(pair)

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
    print(f"Variante {args.variant}: {len(phrases)} frasi, {len(battute)} battute, "
          f"{sum(1 for g in battute if len(g) > 1)} con più take.\n")
    for n, g in enumerate(battute, 1):
        takes = []
        for p in g:
            reel_wer = reel_score = None
            if ref_tokens:
                al = align(p["toks"], ref_tokens, fit=True)
                reel_wer = round(al.errors / len(p["toks"]), 3)
                reel_score = sum(1 for o in al.ops if o[0] == "ok") - al.errors  # copertura del reel
            takes.append({"phrase": p["id"], "clip": p["clip"], "start": round(p["start"], 2),
                          "end": round(p["end"], 2), "text": p["text"], "words": len(p["toks"]),
                          "complete": p["complete"], "reel_wer": reel_wer, "reel_score": reel_score})
        longest = max(t["words"] for t in takes)
        eligible = [t for t in takes if t["complete"] and t["words"] >= 0.8 * longest] or takes
        heur = eligible[-1]["phrase"]  # ultima take completa (§6.2.4, senza LLM)
        in_reel = [t for t in takes if t["reel_wer"] is not None and t["reel_wer"] <= IN_REEL_WER]
        # take del reel: quella che copre più parlato del reel (non la più corta senza errori)
        reel_pick = max(in_reel, key=lambda t: (t["reel_score"], t["words"]))["phrase"] if in_reel else None
        out_b.append({"n": n, "takes": takes, "heuristic_pick": heur, "reel_pick": reel_pick})

        print(f"Battuta {n} · {len(takes)} take" + ("" if reel_pick is None else " · nel reel"))
        for t in takes:
            marks = []
            if t["phrase"] == heur and len(takes) > 1:
                marks.append("euristica")
            if t["phrase"] == reel_pick:
                marks.append("reel")
            if not t["complete"]:
                marks.append("incompleta")
            rw = "" if t["reel_wer"] is None else f" reelWER {t['reel_wer']:.2f}"
            print(f"   {t['clip']} {t['start']:6.2f}–{t['end']:6.2f}{rw} [{', '.join(marks)}]\n      «{t['text']}»")

    multi = [b for b in out_b if len(b["takes"]) > 1]
    judged = [b for b in multi if b["reel_pick"] is not None]
    agree = sum(1 for b in judged if b["reel_pick"] == b["heuristic_pick"])
    print(f"\nTake ripetute: {len(multi)} battute. Euristica = take del reel in {agree}/{len(judged)} casi valutabili.")
    if near:
        print("\nCoppie quasi simili (possibili take mancate, da controllare):")
        for p in near:
            a, b = phrases[p["a"]], phrases[p["b"]]
            print(f"   {p['ratio']:.2f}/{p['partial']:.2f}  {a['clip']}@{a['start']:.1f} «{a['text']}»\n"
                  f"             {b['clip']}@{b['start']:.1f} «{b['text']}»")

    save_json(out_path(wd / "results" / f"takes-{args.variant}.json", args.clip_dir), {
        "variant": args.variant, "window_min": args.window_min, "phrases": len(phrases),
        "battute": out_b, "links": links, "near_misses": near,
        "multi_take": len(multi), "heuristic_agree": agree, "heuristic_judged": len(judged),
    })


if __name__ == "__main__":
    main()
