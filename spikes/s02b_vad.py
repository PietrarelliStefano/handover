"""Spike 01 · passo 2b: VAD, classificazione A-roll / b-roll e filtro delle allucinazioni (§6.1).

    uv run python spikes/s02b_vad.py [CLIP_DIR]

1. Silero VAD sull'audio di ogni clip (audio/*.wav del passo 2): secondi di parlato e segmenti.
   A-roll se il parlato supera --min-speech secondi, altrimenti b-roll.
2. Per ogni variante di trascrizione già fatta (es. turbo) crea la variante "+vad" senza
   rifare Whisper: le clip b-roll vengono tolte, e nelle A-roll si tolgono le parole fuori dal
   parlato e i segmenti che Whisper stesso giudica non parlato (no_speech_prob > 0,6 e
   avg_logprob < −1, la regola di Whisper). L'audio del reel resta com'è (ha la musica sotto).
Scrive results/vad.json e transcripts/<variante>+vad/.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common import DEFAULT_CLIP_DIR, load_json, out_path, save_json, work_dir
from vad import SR, SileroVAD, VadParams, in_speech, read_wav16k, speech_segments


def whisper_says_silence(seg: dict) -> bool:
    nsp, lp = seg.get("no_speech_prob"), seg.get("avg_logprob")
    return nsp is not None and lp is not None and nsp > 0.6 and lp < -1.0


def filter_transcript(tr: dict, segs: list[tuple[float, float]]) -> tuple[dict, list[str]]:
    kept_segments, removed = [], []
    for s in tr["segments"]:
        if whisper_says_silence(s):
            removed.append(f"[{s['start']:.1f}s, no_speech] {s['text']}")
            continue
        words = [w for w in s["words"] if in_speech(w["start"], w["end"], segs)]
        dropped = [w for w in s["words"] if w not in words]
        if dropped:
            removed.append(f"[{dropped[0]['start']:.1f}s, fuori dal parlato] " + " ".join(w["w"] for w in dropped))
        if words:
            kept_segments.append(dict(s, words=words, text=" ".join(w["w"] for w in words)))
    out = dict(tr, segments=kept_segments, text=" ".join(s["text"] for s in kept_segments))
    return out, removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--min-speech", type=float, default=1.5, help="secondi di parlato per essere A-roll")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    wd = work_dir(args.clip_dir)
    params = VadParams(threshold=args.threshold)
    vad = SileroVAD()

    clips = {}
    t_all = time.perf_counter()
    for wav in sorted((wd / "audio").glob("*.wav")):
        if wav.stem == "REEL":
            continue
        audio = read_wav16k(wav)
        t0 = time.perf_counter()
        segs = speech_segments(vad.probs(audio), params, duration_s=len(audio) / SR)
        speech = sum(b - a for a, b in segs)
        clips[wav.stem] = {"duration_s": round(len(audio) / SR, 2), "speech_s": round(speech, 2),
                           "speech_ratio": round(speech / (len(audio) / SR), 3) if len(audio) else 0,
                           "kind": "aroll" if speech >= args.min_speech else "broll",
                           "segments": segs, "vad_s": round(time.perf_counter() - t0, 3)}
    vad_total = time.perf_counter() - t_all

    variants = {}
    for vdir in sorted(p for p in (wd / "transcripts").iterdir() if p.is_dir() and not p.name.endswith("+vad")):
        dst = out_path(wd / "transcripts" / f"{vdir.name}+vad" / "x", args.clip_dir).parent
        for old in dst.glob("*.json"):
            old.unlink()
        removed_all, dropped_clips = {}, []
        for f in sorted(vdir.glob("*.json")):
            tr = load_json(f)
            if f.stem == "REEL":
                (dst / f.name).write_text(json.dumps(tr, ensure_ascii=False, indent=2))
                continue
            info = clips.get(f.stem)
            if info is None:
                continue
            if info["kind"] == "broll":
                if tr["text"].strip():
                    removed_all[f.stem] = [f"[b-roll] {tr['text']}"]
                dropped_clips.append(f.stem)
                continue
            new, removed = filter_transcript(tr, info["segments"])
            if removed:
                removed_all[f.stem] = removed
            (dst / f.name).write_text(json.dumps(new, ensure_ascii=False, indent=2))
        variants[vdir.name] = {"broll_dropped": dropped_clips, "removed": removed_all}

    aroll = [k for k, c in clips.items() if c["kind"] == "aroll"]
    broll_s = sum(c["duration_s"] for c in clips.values() if c["kind"] == "broll")
    save_json(out_path(wd / "results" / "vad.json", args.clip_dir), {
        "params": vars(params) | {"min_speech_s": args.min_speech}, "vad_total_s": round(vad_total, 2),
        "aroll": aroll, "broll_audio_s": round(broll_s, 1), "clips": clips, "variants": variants,
    })
    print(f"VAD su {len(clips)} clip in {vad_total:.1f} s: {len(aroll)} A-roll, {len(clips) - len(aroll)} b-roll "
          f"({broll_s:.0f} s di audio che Whisper può saltare).")
    for k, c in clips.items():
        print(f"   {k}: {c['kind']:<5} parlato {c['speech_s']:5.1f}/{c['duration_s']:5.1f} s")
    for v, info in variants.items():
        print(f"\n[{v}] testo rimosso:")
        for clip, items in info["removed"].items():
            for it in items:
                print(f"   {clip}: {it}")


if __name__ == "__main__":
    main()
