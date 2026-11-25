"""Spike 01 · passo 2: trascrizione con mlx-whisper, large-v3-turbo e large-v3, timestamp per parola.

    uv run python spikes/s02_transcribe.py [CLIP_DIR] [--reel PATH] [--models turbo large-v3] [--prompt]

Trascrive tutte le clip e anche l'audio del reel finito (serve al confronto, passo 3).
Ogni modello gira in un processo separato: tempi di caricamento e memoria di picco puliti.
Scrive transcripts/<variante>/<file>.json e results/transcribe-<variante>.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from common import (DEFAULT_CLIP_DIR, GLOSSARY, MODELS, default_reel, machine_info, out_path, run,
                    save_json, work_dir)
from handover.ingest.probe import find_videos


def extract_audio(src: Path, dst: Path) -> None:
    run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])


def wav_duration(path: Path) -> float:
    return (path.stat().st_size - 44) / (16000 * 2)


def worker(model_key: str, repo: str, audio_files: list[str], out_dir: str, prompt: str | None) -> dict:
    """Eseguito in un processo figlio: importa mlx solo qui."""
    import mlx.core as mx
    import mlx_whisper

    def peak() -> float | None:
        for fn in (getattr(mx, "get_peak_memory", None), getattr(getattr(mx, "metal", None), "get_peak_memory", None)):
            if fn:
                return round(fn() / 1e9, 2)
        return None

    opts = dict(path_or_hf_repo=repo, language="it", word_timestamps=True,
                condition_on_previous_text=False, initial_prompt=prompt)
    # Caricamento (e download al primo giro) misurato a parte su 1 s di silenzio.
    import numpy as np
    t0 = time.perf_counter()
    mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), **opts)
    load_s = time.perf_counter() - t0

    rows = []
    for f in audio_files:
        t0 = time.perf_counter()
        res = mlx_whisper.transcribe(f, **opts)
        el = time.perf_counter() - t0
        dur = wav_duration(Path(f))
        name = Path(f).stem
        segs = [{"start": s["start"], "end": s["end"], "text": s["text"].strip(),
                 "avg_logprob": s.get("avg_logprob"), "no_speech_prob": s.get("no_speech_prob"),
                 "words": [{"w": w["word"].strip(), "start": w["start"], "end": w["end"],
                            "p": round(w.get("probability", 0), 3)} for w in s.get("words", [])]}
                for s in res["segments"]]
        Path(out_dir, f"{name}.json").write_text(json.dumps(
            {"file": name, "model": model_key, "repo": repo, "text": res["text"].strip(), "segments": segs},
            indent=2, ensure_ascii=False))
        rows.append({"file": name, "audio_s": round(dur, 2), "transcribe_s": round(el, 2),
                     "rtf": round(el / dur, 3) if dur else None})
        print(f"[{model_key}] {name}: {dur:.1f} s audio in {el:.1f} s", flush=True)
    return {"model": model_key, "repo": repo, "prompt": prompt, "load_s": round(load_s, 2),
            "peak_mem_gb": peak(), "files": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--reel", type=Path)
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    ap.add_argument("--prompt", action="store_true", help="usa il glossario come initial_prompt (§6.5)")
    ap.add_argument("--_worker", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args._worker:  # processo figlio
        job = json.loads(args._worker)
        print("__RESULT__" + json.dumps(worker(**job)))
        return

    clip_dir: Path = args.clip_dir
    reel = args.reel or default_reel(clip_dir)
    wd = work_dir(clip_dir)
    audio_dir = wd / "audio"

    sources = [(p, p.stem) for p in find_videos(clip_dir)]
    if reel.exists():
        sources.append((reel, "REEL"))
    else:
        print(f"Attenzione: reel non trovato ({reel}); confronto possibile solo con OCR manuale.")

    t0 = time.perf_counter()
    wavs = []
    for src, name in sources:
        dst = out_path(audio_dir / f"{name}.wav", clip_dir)
        if not dst.exists():
            extract_audio(src, dst)
        wavs.append(str(dst))
    audio_extract_s = time.perf_counter() - t0

    prompt = ", ".join(GLOSSARY) + "." if args.prompt else None
    for key in args.models:
        variant = key + ("+prompt" if prompt else "")
        tdir = out_path(wd / "transcripts" / variant / "x", clip_dir).parent
        job = {"model_key": key, "repo": MODELS[key], "audio_files": wavs, "out_dir": str(tdir), "prompt": prompt}
        t1 = time.perf_counter()
        proc = subprocess.run([sys.executable, __file__, "--_worker", json.dumps(job)],
                              capture_output=True, text=True)
        wall = time.perf_counter() - t1
        sys.stderr.write(proc.stderr[-3000:])
        line = next((l for l in proc.stdout.splitlines() if l.startswith("__RESULT__")), None)
        if proc.returncode != 0 or line is None:
            raise SystemExit(f"Trascrizione con {key} fallita:\n{proc.stdout[-2000:]}")
        print("\n".join(l for l in proc.stdout.splitlines() if not l.startswith("__RESULT__")))
        res = json.loads(line[len("__RESULT__"):])
        clips = [r for r in res["files"] if r["file"] != "REEL"]
        a = sum(r["audio_s"] for r in clips)
        t = sum(r["transcribe_s"] for r in clips)
        res.update({
            "variant": variant, "process_wall_s": round(wall, 1), "audio_extract_s": round(audio_extract_s, 1),
            "clips_audio_s": round(a, 1), "clips_transcribe_s": round(t, 1),
            "clips_rtf": round(t / a, 3) if a else None, "machine": machine_info(),
        })
        save_json(out_path(wd / "results" / f"transcribe-{variant}.json", clip_dir), res)
        print(f"[{variant}] clip: {a:.1f} s audio in {t:.1f} s (RTF {res['clips_rtf']}), "
              f"caricamento {res['load_s']} s, picco {res['peak_mem_gb']} GB\n")


if __name__ == "__main__":
    main()
