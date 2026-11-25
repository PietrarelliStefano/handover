"""Verifica di M2: piano automatico contro il reel montato a mano.

    uv run python spikes/s07_eval_plan.py "<cartella shooting>" [--plan <piano.json>] [--reel <reel.mp4>]

1. Mappa audio del reel finito sulle clip (stesso metodo di s03b_reel_match), usando l'audio
   16 kHz che `handover run` ha già estratto nella cartella di lavoro.
2. Confronto con l'ultimo piano (o quello indicato):
   - accordo: quota del parlato del piano che viene dagli stessi tratti di clip usati nel reel;
   - copertura: quota del parlato del reel presente anche nel piano;
   - frasi ripetute nel piano (criterio §12: nessuna frase ripetuta);
   - durate.
Scrive eval/<piano>.json nella cartella di lavoro. Solo lettura sullo shooting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from handover.pipeline import open_workspace  # noqa: E402
from handover.video.media import extract_audio16k  # noqa: E402
from handover.video.takes import similarity  # noqa: E402
from handover.video.text import normalize_tokens  # noqa: E402
from handover.video.vad import read_wav16k  # noqa: E402
from handover.workdir import read_json, write_json  # noqa: E402
from s03b_reel_match import match, prep, to_segments  # noqa: E402


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shooting", type=Path)
    ap.add_argument("--plan", type=Path)
    ap.add_argument("--reel", type=Path)
    args = ap.parse_args()

    ws, _ = open_workspace(args.shooting)
    plan_path = args.plan or (ws.plan_versions() or [None])[-1]
    if plan_path is None:
        raise SystemExit("Nessun piano: esegui prima `handover run`.")
    plan = read_json(plan_path)
    reel = args.reel or args.shooting / f"{args.shooting.name}.mp4"
    if not reel.exists():
        raise SystemExit(f"Reel finito non trovato: {reel}")

    reel_wav = ws.path("eval", "REEL.wav")
    if not reel_wav.exists():
        extract_audio16k(reel, reel_wav)
    map_path = ws.path("eval", "reel_map.json")
    if map_path.exists():
        rmap = read_json(map_path)
    else:
        clips = {p.stem: prep(read_wav16k(p)) for p in sorted((ws.root / "audio").glob("*.wav"))}
        rmap = to_segments(match(prep(read_wav16k(reel_wav)), clips))
        write_json(map_path, rmap)

    segs = [s for s in plan["segments"] if s["type"] == "aroll"]
    plan_s = sum(s["out_ms"] - s["in_ms"] for s in segs) / 1000
    reel_s = sum(r["clip_end"] - r["clip_start"] for r in rmap)
    agree = 0.0
    for s in segs:
        stem = Path(s["clip"]).stem
        a, b = s["in_ms"] / 1000, s["out_ms"] / 1000
        agree += sum(overlap(a, b, r["clip_start"], r["clip_end"]) for r in rmap if r["clip"] == stem)

    texts = [(s["id"], normalize_tokens(" ".join(w["t"] for w in s["words"]))) for s in segs]
    repeated = []
    for i, (ia, ta) in enumerate(texts):
        for ib, tb in texts[i + 1:]:
            if min(len(ta), len(tb)) >= 3 and similarity(ta, tb) >= 0.7:
                repeated.append([ia, ib])

    plan_clips = sorted({Path(s["clip"]).stem for s in segs})
    reel_clips = sorted({r["clip"] for r in rmap})
    result = {
        "plan": plan_path.name, "plan_s": round(plan_s, 2), "reel_speech_s": round(reel_s, 2),
        "agreement": round(agree / plan_s, 3) if plan_s else None,
        "coverage": round(agree / reel_s, 3) if reel_s else None,
        "repeated_phrases": repeated, "plan_clips": plan_clips, "reel_clips": reel_clips, "reel_map": rmap,
    }
    write_json(ws.path("eval", f"{plan_path.stem}.json"), result)
    print(f"Piano {plan_path.name}: {plan_s:.1f} s di parlato; reel montato a mano: {reel_s:.1f} s ricondotti alle clip.")
    print(f"Accordo (parlato del piano preso dagli stessi tratti del reel): {result['agreement']:.0%}")
    print(f"Copertura (parlato del reel presente nel piano): {result['coverage']:.0%}")
    print(f"Frasi ripetute nel piano: {len(repeated)}" + (f" {repeated}" if repeated else ""))
    print(f"Clip del piano: {' '.join(plan_clips)}\nClip del reel:  {' '.join(reel_clips)}")


if __name__ == "__main__":
    main()
