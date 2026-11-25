"""Spike 01 · passo 3: sottotitoli del reel finito via OCR sui fotogrammi (riferimento per il WER).

    uv run python spikes/s03_reel_subs.py [CLIP_DIR] [--reel PATH] [--fps 5]

OCR: Apple Vision (ocrmac, it-IT) sul Mac; tesseract `ita` come ripiego.
Scrive reel/subs_ocr.json e reel/reference.txt (un gruppo di parole per riga, con il tempo).

Il riferimento OCR va controllato a occhio guardando il reel: copiare reference.txt in
reference_manual.txt e correggere. Se reference_manual.txt esiste, il passo 4 usa quello.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from common import DEFAULT_CLIP_DIR, default_reel, out_path, run, save_json, work_dir
from handover.ingest.probe import probe_file
from textnorm import normalize_tokens

# Banda dei sottotitoli: §6.5 misura y 1838–2097 su 2560 (72–82%); margine per righe doppie e card.
BAND = (0.60, 0.90)


def extract_frames(reel: Path, out_dir: Path, fps: float) -> list[Path]:
    info = probe_file(reel)
    h = info.display_height or 2560
    y0, y1 = int(h * BAND[0]), int(h * BAND[1])
    for old in out_dir.glob("f_*.png"):
        old.unlink()
    run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(reel),
         "-vf", f"fps={fps},crop=iw:{y1 - y0}:0:{y0}", str(out_dir / "f_%05d.png")])
    return sorted(out_dir.glob("f_*.png"))


def ocr_vision(path: Path) -> str:
    from ocrmac import ocrmac
    items = ocrmac.OCR(str(path), language_preference=["it-IT"], recognition_level="accurate").recognize()
    # bbox normalizzato (x, y, w, h) con origine in basso a sinistra: righe dall'alto, poi da sinistra.
    items = [it for it in items if it[1] >= 0.3]
    items.sort(key=lambda it: (-round(it[2][1], 2), it[2][0]))
    return " ".join(it[0] for it in items)


def ocr_tesseract(path: Path) -> str:
    res = subprocess.run(["tesseract", str(path), "stdout", "-l", "ita", "--psm", "6"],
                         capture_output=True, text=True)
    return " ".join(res.stdout.split())


def pick_engine(name: str):
    if name in ("auto", "vision"):
        try:
            import ocrmac  # noqa: F401
            return "vision", ocr_vision
        except ImportError:
            if name == "vision":
                raise
    if shutil.which("tesseract"):
        return "tesseract", ocr_tesseract
    raise SystemExit("Nessun OCR disponibile: `uv sync --group spike` (ocrmac) oppure `brew install tesseract tesseract-lang`.")


def clean(text: str) -> str:
    text = re.sub(r"[^\w€%.,'’ ]", " ", text)
    return " ".join(text.split())


def group_frames(texts: list[tuple[float, str]], frame_dt: float) -> list[dict]:
    """Unisce fotogrammi consecutivi con lo stesso gruppo di parole (tollera rumore OCR)."""
    groups: list[dict] = []
    for t, txt in texts:
        toks = normalize_tokens(txt, drop_units=False)
        if not toks:
            continue
        if groups:
            g = groups[-1]
            sim = SequenceMatcher(None, g["_toks"], toks).ratio()
            if sim >= 0.75 and t - g["end"] <= frame_dt * 2.5:
                g["end"] = t + frame_dt
                g["_variants"][txt] += 1
                continue
        groups.append({"start": t, "end": t + frame_dt, "_toks": toks, "_variants": Counter({txt: 1})})
    out = []
    for g in groups:
        text, n = g["_variants"].most_common(1)[0]
        if sum(g["_variants"].values()) < 2:  # un solo fotogramma: probabile transizione o rumore
            continue
        out.append({"start": round(g["start"], 2), "end": round(g["end"], 2), "text": text,
                    "frames": sum(g["_variants"].values())})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--reel", type=Path)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--engine", default="auto", choices=["auto", "vision", "tesseract"])
    args = ap.parse_args()

    clip_dir: Path = args.clip_dir
    reel = args.reel or default_reel(clip_dir)
    if not reel.exists():
        raise SystemExit(f"Reel non trovato: {reel}")
    wd = work_dir(clip_dir)
    frames_dir = out_path(wd / "reel" / "frames" / "x", clip_dir).parent
    engine_name, engine = pick_engine(args.engine)

    t0 = time.perf_counter()
    frames = extract_frames(reel, frames_dir, args.fps)
    t_extract = time.perf_counter() - t0
    dt = 1.0 / args.fps
    t0 = time.perf_counter()
    texts = [(i * dt, clean(engine(f))) for i, f in enumerate(frames)]
    t_ocr = time.perf_counter() - t0

    groups = group_frames(texts, dt)
    save_json(out_path(wd / "reel" / "subs_ocr.json", clip_dir), {
        "reel": str(reel), "engine": engine_name, "fps": args.fps, "band": BAND,
        "frames": len(frames), "extract_s": round(t_extract, 1), "ocr_s": round(t_ocr, 1),
        "raw": [{"t": round(t, 2), "text": x} for t, x in texts], "groups": groups,
    })
    ref = out_path(wd / "reel" / "reference.txt", clip_dir)
    ref.write_text("".join(f"{g['start']:6.2f}\t{g['text']}\n" for g in groups))
    print(f"{len(groups)} gruppi di sottotitoli da {len(frames)} fotogrammi ({engine_name}, {t_ocr:.0f} s).")
    print(f"Riferimento: {ref}\nControllalo sul reel e salva la versione corretta come {ref.with_name('reference_manual.txt')}")


if __name__ == "__main__":
    main()
