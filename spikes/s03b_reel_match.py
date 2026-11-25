"""Spike 01 · passo 3b: da quali clip (e da che punto) viene l'audio del reel finito.

    uv run python spikes/s03b_reel_match.py [CLIP_DIR]

Per ogni finestra di 1 s dell'audio del reel cerca la clip e l'istante con la massima correlazione
normalizzata (NCC) della forma d'onda, a 8 kHz con pre-enfasi per ridurre il peso della musica.
Le finestre consecutive con la stessa clip e lo stesso scarto temporale diventano un segmento:
il risultato è la lista dei tagli del reel (reel [a, b] ← clip [c, d]).
Serve a sapere con certezza quale take hai usato, anche quando due take sono identiche nel testo.
Scrive results/reel_map.json.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from common import DEFAULT_CLIP_DIR, out_path, save_json, work_dir
from vad import read_wav16k

FS = 8000
WIN_S = 1.0
HOP_S = 0.25
MIN_NCC = 0.45
OFFSET_TOL_S = 0.06


def prep(audio16k: np.ndarray) -> np.ndarray:
    x = audio16k[: len(audio16k) // 2 * 2].reshape(-1, 2).mean(axis=1)  # 16 → 8 kHz
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])  # pre-enfasi: meno bassi della musica
    return (x - x.mean()).astype(np.float64)


def ncc_all_lags(w: np.ndarray, wn: float, w_fft: np.ndarray, clip: np.ndarray, clip_fft: np.ndarray, nfft: int,
                 clip_energy_cum: np.ndarray) -> tuple[int, float]:
    """w: finestra a media nulla, wn: sua norma, w_fft: rfft(w, nfft) coniugata."""
    n = len(w)
    if len(clip) < n:
        return 0, 0.0
    corr = np.fft.irfft(clip_fft * w_fft, nfft)[: len(clip) - n + 1]
    energy = clip_energy_cum[n:] - clip_energy_cum[:-n]
    denom = np.sqrt(np.maximum(energy[: len(corr)], 1e-12)) * wn
    ncc = corr / denom
    ncc[energy[: len(corr)] < 1e-6 * n] = 0.0  # silenzio nella clip: niente falsi picchi
    k = int(np.argmax(ncc))
    return k, float(ncc[k])


def match(reel: np.ndarray, clips: dict[str, np.ndarray]) -> list[dict]:
    n = int(WIN_S * FS)
    hop = int(HOP_S * FS)
    prepared = {}
    for name, c in clips.items():
        nfft = 1 << int(np.ceil(np.log2(len(c) + n)))
        prepared[name] = (c, np.fft.rfft(c, nfft), nfft, np.concatenate([[0.0], np.cumsum(c * c)]))
    rows = []
    for start in range(0, max(1, len(reel) - n + 1), hop):
        w = reel[start:start + n]
        w = w - w.mean()
        wn = float(np.linalg.norm(w))
        best = ("", 0, 0.0)
        second = 0.0
        if wn < 1e-8:  # silenzio nel reel
            rows.append({"reel_t": start / FS, "clip": "", "clip_t": 0.0, "ncc": 0.0, "margin": 0.0})
            continue
        w_ffts: dict[int, np.ndarray] = {}
        for name, (c, cf, nfft, cum) in prepared.items():
            if nfft not in w_ffts:
                w_ffts[nfft] = np.conj(np.fft.rfft(w, nfft))
            lag, v = ncc_all_lags(w, wn, w_ffts[nfft], c, cf, nfft, cum)
            if v > best[2]:
                second = max(second, best[2])
                best = (name, lag, v)
            else:
                second = max(second, v)
        rows.append({"reel_t": start / FS, "clip": best[0], "clip_t": best[1] / FS,
                     "ncc": round(best[2], 3), "margin": round(best[2] - second, 3)})
    return rows


def to_segments(rows: list[dict]) -> list[dict]:
    segs: list[dict] = []
    for r in rows:
        if r["ncc"] < MIN_NCC:
            continue
        off = r["clip_t"] - r["reel_t"]
        if segs:
            s = segs[-1]
            if (s["clip"] == r["clip"] and abs(s["_off"] - off) <= OFFSET_TOL_S
                    and r["reel_t"] - s["reel_end"] <= WIN_S):
                s["reel_end"] = r["reel_t"] + WIN_S
                s["clip_end"] = r["clip_t"] + WIN_S
                s["_ncc"].append(r["ncc"])
                continue
        segs.append({"clip": r["clip"], "reel_start": r["reel_t"], "reel_end": r["reel_t"] + WIN_S,
                     "clip_start": r["clip_t"], "clip_end": r["clip_t"] + WIN_S, "_off": off, "_ncc": [r["ncc"]]})
    segs = [s for s in segs if len(s["_ncc"]) >= 2]  # una finestra sola: troppo poco per fidarsi
    # le finestre a cavallo di un taglio fanno sovrapporre segmenti vicini: si divide a metà
    for a, b in zip(segs, segs[1:]):
        if b["reel_start"] < a["reel_end"]:
            mid = (b["reel_start"] + a["reel_end"]) / 2
            a["clip_end"] -= a["reel_end"] - mid
            b["clip_start"] += mid - b["reel_start"]
            a["reel_end"] = b["reel_start"] = mid
    out = []
    for s in segs:
        out.append({k: round(v, 2) if isinstance(v, float) else v for k, v in s.items() if not k.startswith("_")}
                   | {"ncc_mean": round(float(np.mean(s["_ncc"])), 3), "windows": len(s["_ncc"])})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    args = ap.parse_args()
    wd = work_dir(args.clip_dir)
    audio = wd / "audio"
    if not (audio / "REEL.wav").exists():
        raise SystemExit("Manca audio/REEL.wav: esegui prima s02_transcribe.py con il reel.")

    t0 = time.perf_counter()
    reel = prep(read_wav16k(audio / "REEL.wav"))
    clips = {p.stem: prep(read_wav16k(p)) for p in sorted(audio.glob("*.wav")) if p.stem != "REEL"}
    rows = match(reel, clips)
    segs = to_segments(rows)
    elapsed = time.perf_counter() - t0

    reel_s = len(reel) / FS
    covered = sum(s["reel_end"] - s["reel_start"] for s in segs)
    save_json(out_path(wd / "results" / "reel_map.json", args.clip_dir), {
        "win_s": WIN_S, "hop_s": HOP_S, "min_ncc": MIN_NCC, "elapsed_s": round(elapsed, 1),
        "reel_s": round(reel_s, 2), "covered_s": round(covered, 2), "segments": segs, "windows": rows,
    })
    print(f"Reel {reel_s:.1f} s: {covered:.1f} s ricondotti a {len({s['clip'] for s in segs})} clip "
          f"in {len(segs)} segmenti ({elapsed:.0f} s).")
    for s in segs:
        print(f"   reel {s['reel_start']:6.2f}–{s['reel_end']:6.2f}  ←  {s['clip']} {s['clip_start']:6.2f}–{s['clip_end']:6.2f}"
              f"  (NCC {s['ncc_mean']:.2f})")


if __name__ == "__main__":
    main()
