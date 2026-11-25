"""Mezzanine 1440×2560 e audio per l'analisi (§6.1). Gli originali vengono solo letti."""

from __future__ import annotations

import subprocess
from pathlib import Path

MEZZ_W, MEZZ_H = 1440, 2560


def _run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg fallito ({res.returncode}): {' '.join(cmd)}\n{res.stderr[-2000:]}")


def mezzanine_cmd(src: Path, dst: Path, encoder: str = "h264_videotoolbox", bitrate: str = "40M",
                  hw_decode: bool = True) -> list[str]:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    if hw_decode:
        cmd += ["-hwaccel", "videotoolbox"]
    # La rotazione automatica di ffmpeg applica il display matrix (§6.1): nessun transpose a mano.
    cmd += ["-i", str(src), "-map", "0:v:0", "-map", "0:a?",
            "-vf", f"scale={MEZZ_W}:{MEZZ_H}:flags=lanczos,format=yuv420p",
            "-c:v", encoder, "-b:v", bitrate, "-profile:v", "high"]
    if encoder == "h264_videotoolbox":
        cmd += ["-allow_sw", "0", "-realtime", "0"]
    elif encoder == "libx264":
        cmd += ["-preset", "veryfast"]
    cmd += ["-c:a", "copy", "-movflags", "+faststart", str(dst)]
    return cmd


def make_mezzanine(src: Path, dst: Path, **kw) -> None:
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    _run(mezzanine_cmd(src, tmp, **kw))
    tmp.replace(dst)


def extract_audio16k(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    _run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vn",
          "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)])
    tmp.replace(dst)


def has_filter(name: str) -> bool:
    res = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in res.stdout.splitlines() if len(line.split()) > 1)


def stabilize(src: Path, dst: Path, encoder: str = "h264_videotoolbox", bitrate: str = "40M",
              smoothing: int = 12) -> None:
    """Stabilizzazione in due passate con vidstab (§6.1, rev. 8).
    smoothing=12 fotogrammi (~0,5 s): toglie il tremolio e lascia i movimenti voluti;
    optzoom=1: zoom fisso minimo per non vedere i bordi."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # percorso relativo al cwd: nei filtri di ffmpeg ':' e spazi vanno evitati
        _run_in(tmp, ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
                      "-vf", "vidstabdetect=shakiness=6:accuracy=15:result=t.trf", "-f", "null", "-"])
        tmp_out = dst.with_name(dst.stem + ".part" + dst.suffix)
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?",
               "-vf", f"vidstabtransform=input=t.trf:smoothing={smoothing}:optzoom=1:interpol=bicubic,"
                      f"unsharp=5:5:0.5:3:3:0,format=yuv420p",
               "-c:v", encoder, "-b:v", bitrate, "-profile:v", "high"]
        if encoder == "h264_videotoolbox":
            cmd += ["-allow_sw", "0", "-realtime", "0"]
        elif encoder == "libx264":
            cmd += ["-preset", "veryfast"]
        cmd += ["-c:a", "copy", "-movflags", "+faststart", str(tmp_out)]
        _run_in(tmp, cmd)
        tmp_out.replace(dst)


def _run_in(cwd: str, cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg fallito ({res.returncode}): {' '.join(cmd)}\n{res.stderr[-2000:]}")
