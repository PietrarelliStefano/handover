"""Spike 01 · passo 4: WER e errori sui token critici rispetto ai sottotitoli del reel.

    uv run python spikes/s04_compare.py [CLIP_DIR]

Due misure per ogni variante di trascrizione:
  A. audio del reel → confronto diretto con i sottotitoli (stesso parlato, con musica sotto);
  B. clip originali → il riferimento viene allineato sulle clip concatenate, con salti permessi solo
     all'inizio di un gruppo di sottotitoli (dove cadono i tagli del montaggio); le take scartate
     non costano nulla. È il caso reale della pipeline, un po' ottimista perché tra più take
     sceglie quella che somiglia di più.
Token critici: numeri (§6.5) e nomi del glossario.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from pathlib import Path

from common import DEFAULT_CLIP_DIR, GLOSSARY, load_json, out_path, save_json, work_dir
from textnorm import Alignment, align, align_jump, is_number, normalize_tokens, number_errors

SEP = "<|clip|>"
JUMP_COST = 1.0


def load_reference(wd: Path) -> tuple[list[str], str]:
    for name in ("reference_manual.txt", "reference.txt"):
        p = wd / "reel" / name
        if p.exists():
            lines = [l.split("\t", 1)[-1].strip() for l in p.read_text().splitlines() if l.strip()]
            return lines, name
    raise SystemExit("Riferimento mancante: esegui prima s03_reel_subs.py")


def glossary_tokens() -> set[str]:
    return {t for g in GLOSSARY for t in normalize_tokens(g)}


def critical_report(al: Alignment, gloss: set[str]) -> dict:
    nums = [r for op, r, _ in al.ops if r is not None and is_number(r)]
    names = [r for op, r, _ in al.ops if r is not None and r in gloss]
    name_errs = [{"ref": r, "hyp": h, "op": op} for op, r, h in al.ops if r in gloss and op != "ok"]
    return {"numbers": len(nums), "number_errors": number_errors(al),
            "names": len(names), "name_errors": name_errs}


def subs_list(al: Alignment) -> list[str]:
    return [f"{r or '∅'} → {h or '∅'}" for op, r, h in al.ops if op != "ok"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    args = ap.parse_args()
    wd = work_dir(args.clip_dir)
    lines, ref_name = load_reference(wd)
    ref, group_starts = [], []
    for line in lines:
        group_starts.append(len(ref))
        ref += normalize_tokens(line)
    boundaries = set(group_starts)
    gloss = glossary_tokens()

    variants = sorted(p.name for p in (wd / "transcripts").iterdir() if p.is_dir())
    report = {"reference": ref_name, "ref_words": len(ref), "variants": {}}
    for v in variants:
        tdir = wd / "transcripts" / v
        files = {p.stem: load_json(p) for p in tdir.glob("*.json")}
        entry: dict = {}

        if "REEL" in files:
            hyp = normalize_tokens(files["REEL"]["text"])
            al = align(ref, hyp)
            entry["reel"] = {"wer": round(al.errors / len(ref), 4), "sub": al.subs, "del": al.dels, "ins": al.ins,
                             "n_ref": len(ref), **critical_report(al, gloss), "diff": subs_list(al)}

        # B. clip concatenate con separatore; mappa posizione → clip
        hyp, owner = [], []
        for name in sorted(k for k in files if k != "REEL"):
            for t in normalize_tokens(files[name]["text"]) + [SEP]:
                hyp.append(t)
                owner.append(name)
        al = align_jump(ref, hyp, boundaries, JUMP_COST, barrier=SEP)
        crit = critical_report(al, gloss)
        def clip_of(k: int) -> str | None:
            # per le cancellazioni (nessuna posizione in hyp) si usa la parola allineata più vicina prima
            for kk in range(k, -1, -1):
                if al.hyp_pos[kk] is not None:
                    return owner[al.hyp_pos[kk]]
            return None

        for key in ("number_errors", "name_errors"):
            idx = [k for k, (op, r, h) in enumerate(al.ops) if r is not None and op != "ok"
                   and (is_number(r) if key == "number_errors" else r in gloss)]
            crit[key] = [dict(e, clip=clip_of(k) or "?") for e, k in zip(crit[key], idx)]
        # errori per gruppo di sottotitoli (gli inserimenti vanno al gruppo della parola che segue)
        per_group: list[list[int]] = [[] for _ in lines]
        ri, pending = 0, []
        for k, (op, r, h) in enumerate(al.ops):
            if r is None:
                pending.append(k)
                continue
            g = bisect_right(group_starts, ri) - 1
            per_group[g] += pending + [k]
            pending, ri = [], ri + 1
        if pending:
            per_group[-1] += pending
        rows = []
        for g, ks in enumerate(per_group):
            ops = [al.ops[k] for k in ks]
            rows.append({"ref": lines[g],
                         "clips": sorted({c for k in ks if (c := clip_of(k)) and al.ops[k][2] != SEP}),
                         "errors": sum(1 for o in ops if o[0] != "ok"),
                         "hyp": " ".join(o[2] for o in ops if o[2] and o[2] != SEP),
                         "diff": [f"{o[1] or '∅'} → {o[2] or '∅'}" for o in ops if o[0] != "ok"]})
        entry["clips"] = {"wer": round(al.errors / len(ref), 4) if ref else None, "errors": al.errors,
                          "sub": al.subs, "del": al.dels, "ins": al.ins, "n_ref": len(ref), **crit,
                          "groups": rows}
        report["variants"][v] = entry

        r, c = entry.get("reel"), entry["clips"]
        print(f"\n== {v} ==")
        if r:
            print(f"A. reel : WER {r['wer']:.1%} (S{r['sub']} D{r['del']} I{r['ins']} su {r['n_ref']}), "
                  f"numeri errati {len(r['number_errors'])}/{r['numbers']}, nomi errati {len(r['name_errors'])}/{r['names']}")
        print(f"B. clip : WER {c['wer']:.1%} su {c['n_ref']} parole, "
              f"numeri errati {len(c['number_errors'])}/{c['numbers']}, nomi errati {len(c['name_errors'])}/{c['names']}")
        for e in c["number_errors"] + c["name_errors"]:
            print(f"   critico: {e['ref']} → {e['hyp']} ({e['op']}, {e['clip']})")

    save_json(out_path(wd / "results" / "compare.json", args.clip_dir), report)


if __name__ == "__main__":
    main()
