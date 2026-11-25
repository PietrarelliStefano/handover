"""Lettura dei metadati video (§4.5, §6.1, §11): sola lettura, nessuna scrittura sugli originali."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".mts", ".avi", ".mkv"}

# Trasferimenti che indicano HLG/PQ: clip da segnalare e non usare (§6.1, §11).
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}


@dataclass
class VideoInfo:
    file: str
    duration_s: float | None
    codec: str | None
    profile: str | None
    width: int | None
    height: int | None
    fps: float | None
    pix_fmt: str | None
    bit_depth: int | None
    color_transfer: str | None
    rotation: int  # gradi dal display matrix, come li riporta ffprobe (0 se assente)
    rotation_tag: bool
    display_width: int | None
    display_height: int | None
    orientation: str | None  # "verticale" | "orizzontale" | "quadrata"
    creation_time: str | None
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_bits: int | None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def find_videos(folder: Path) -> list[Path]:
    """Video nella cartella (ricorsivo), esclusi file nascosti e AppleDouble (`._*`) dei volumi esterni."""
    out = []
    for p in sorted(folder.rglob("*")):
        if any(part.startswith(".") for part in p.relative_to(folder).parts):
            continue
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            out.append(p)
    return out


def run_ffprobe(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def _fps(stream: dict) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = stream.get(key)
        if val and val != "0/0":
            try:
                f = Fraction(val)
            except (ValueError, ZeroDivisionError):
                continue
            if f > 0:
                return round(float(f), 3)
    return None


def _rotation(stream: dict) -> tuple[int, bool]:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            return int(round(float(sd["rotation"]))), True
    tag = (stream.get("tags") or {}).get("rotate")
    if tag is not None:
        # Il vecchio tag `rotate` è in senso orario; il display matrix è antiorario.
        return -int(tag), True
    return 0, False


def _bit_depth(stream: dict) -> int | None:
    raw = stream.get("bits_per_raw_sample")
    if raw and str(raw).isdigit():
        return int(raw)
    pix = stream.get("pix_fmt") or ""
    for depth in (16, 12, 10):
        if f"p{depth}" in pix:
            return depth
    return 8 if pix else None


def parse_probe(path: Path, probe: dict) -> VideoInfo:
    streams = probe.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = probe.get("format", {})

    duration = fmt.get("duration") or (v or {}).get("duration")
    flags: list[str] = []

    if v is None:
        return VideoInfo(
            file=str(path), duration_s=float(duration) if duration else None,
            codec=None, profile=None, width=None, height=None, fps=None, pix_fmt=None,
            bit_depth=None, color_transfer=None, rotation=0, rotation_tag=False,
            display_width=None, display_height=None, orientation=None,
            creation_time=(fmt.get("tags") or {}).get("creation_time"),
            audio_codec=(a or {}).get("codec_name"), audio_sample_rate=None, audio_bits=None,
            flags=["nessuna_traccia_video"],
        )

    w, h = v.get("width"), v.get("height")
    rot, has_tag = _rotation(v)
    if w and h and abs(rot) % 180 == 90:
        dw, dh = h, w
    else:
        dw, dh = w, h
    orientation = None
    if dw and dh:
        orientation = "verticale" if dh > dw else "orizzontale" if dw > dh else "quadrata"

    fps = _fps(v)
    transfer = v.get("color_transfer")

    if not has_tag and orientation == "orizzontale":
        flags.append("rotazione_assente")  # §11: rotazione dal profilo camera (−90)
    if transfer in HDR_TRANSFERS:
        flags.append("hlg_o_pq")
    if fps and fps >= 100:
        flags.append("alto_fps")  # §11: 120p solo come b-roll rallentato

    tags = v.get("tags") or {}
    ftags = fmt.get("tags") or {}
    sr = (a or {}).get("sample_rate")
    abits = (a or {}).get("bits_per_raw_sample") or (a or {}).get("bits_per_sample")
    return VideoInfo(
        file=str(path),
        duration_s=round(float(duration), 3) if duration else None,
        codec=v.get("codec_name"),
        profile=v.get("profile"),
        width=w, height=h, fps=fps,
        pix_fmt=v.get("pix_fmt"),
        bit_depth=_bit_depth(v),
        color_transfer=transfer,
        rotation=rot, rotation_tag=has_tag,
        display_width=dw, display_height=dh, orientation=orientation,
        creation_time=tags.get("creation_time") or ftags.get("creation_time"),
        audio_codec=(a or {}).get("codec_name"),
        audio_sample_rate=int(sr) if sr else None,
        audio_bits=int(abits) if abits and int(abits) > 0 else None,
        flags=flags,
    )


def probe_file(path: Path) -> VideoInfo:
    return parse_probe(path, run_ffprobe(path))


def probe_folder(folder: Path) -> list[VideoInfo]:
    return [probe_file(p) for p in find_videos(folder)]
