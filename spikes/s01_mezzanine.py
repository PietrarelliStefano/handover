"""Spike 01 · passo 1: probe delle clip e mezzanine 1440×2560 con VideoToolbox (§6.1).

    uv run python spikes/s01_mezzanine.py [CLIP_DIR] [--encoder h264_videotoolbox]

Scrive in ~/handover-work/spike-01/<shooting>/: probe.json, mezzanine/*.mov, results/mezzanine.json.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from common import DEFAULT_CLIP_DIR, machine_info, out_path, run, save_json, work_dir
from handover.ingest.probe import parse_probe, probe_folder, run_ffprobe


def mezzanine_cmd(src: Path, dst: Path, encoder: str, bitrate: str, hw_decode: bool) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    if hw_decode:
        cmd += ["-hwaccel", "videotoolbox"]
    # La rotazione automatica di ffmpeg applica il display matrix (§6.1): nessun transpose a mano.
    cmd += ["-i", str(src), "-map", "0:v:0", "-map", "0:a?",
            "-vf", "scale=1440:2560:flags=lanczos,format=yuv420p",
            "-c:v", encoder, "-b:v", bitrate, "-profile:v", "high"]
    if encoder == "h264_videotoolbox":
        cmd += ["-allow_sw", "0", "-realtime", "0"]
    elif encoder == "libx264":
        cmd += ["-preset", "veryfast"]
    cmd += ["-c:a", "copy", "-movflags", "+faststart", str(dst)]
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--encoder", default="h264_videotoolbox", help="libx264 solo per provare fuori dal Mac")
    ap.add_argument("--bitrate", default="40M")
    ap.add_argument("--no-hw-decode", action="store_true")
    ap.add_argument("--force", action="store_true", help="rifà i mezzanine anche se esistono")
    args = ap.parse_args()

    clip_dir: Path = args.clip_dir
    wd = work_dir(clip_dir)
    if (wd / "results" / "mezzanine.json").exists() and not args.force:
        print("Mezzanine già fatti, salto (usa --force per rifarli)")
        return
    infos = probe_folder(clip_dir)
    if not infos:
        raise SystemExit(f"Nessuna clip in {clip_dir}")
    save_json(out_path(wd / "probe.json", clip_dir), [i.to_dict() for i in infos])

    results = []
    t_all = time.perf_counter()
    for info in infos:
        src = Path(info.file)
        dst = out_path(wd / "mezzanine" / f"{src.stem}.mov", clip_dir)
        row = {"clip": src.name, "duration_s": info.duration_s, "src": f"{info.width}x{info.height}",
               "rotation": info.rotation, "rotation_tag": info.rotation_tag, "flags": info.flags}
        if "hlg_o_pq" in info.flags:
            row["skipped"] = "HLG/PQ: clip segnalata e non usata (§6.1)"
            results.append(row)
            continue
        t0 = time.perf_counter()
        run(mezzanine_cmd(src, dst, args.encoder, args.bitrate, not args.no_hw_decode))
        elapsed = time.perf_counter() - t0
        out = parse_probe(dst, run_ffprobe(dst))
        row.update({
            "encode_s": round(elapsed, 2),
            "speed_x": round((info.duration_s or 0) / elapsed, 2) if elapsed else None,
            "out": f"{out.width}x{out.height}",
            "out_rotation_tag": out.rotation_tag,
            "out_ok": out.width == 1440 and out.height == 2560 and not (out.rotation_tag and out.rotation % 360),
            "out_mb": round(dst.stat().st_size / 1e6, 1),
        })
        results.append(row)
        print(f"{src.name}: {row['encode_s']} s ({row['speed_x']}× tempo reale) → {row['out']} ok={row['out_ok']}")

    total = time.perf_counter() - t_all
    dur = sum(r["duration_s"] or 0 for r in results if "encode_s" in r)
    summary = {
        "encoder": args.encoder, "bitrate": args.bitrate, "hw_decode": not args.no_hw_decode,
        "clips": len(results), "footage_s": round(dur, 1), "total_s": round(total, 1),
        "speed_x": round(dur / total, 2) if total else None,
        "all_ok": all(r.get("out_ok") for r in results if "encode_s" in r),
        "machine": machine_info(),
    }
    save_json(out_path(wd / "results" / "mezzanine.json", clip_dir), {"summary": summary, "clips": results})
    print(f"\nTotale: {summary['clips']} clip, {dur:.1f} s di girato in {total:.1f} s ({summary['speed_x']}×)")


if __name__ == "__main__":
    main()
