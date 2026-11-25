"""Utility condivise dagli script dello spike 01 (video)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # pacchetto handover

DEFAULT_CLIP_DIR = Path("/Volumes/WORK/IMMOBILIARE VENEZIA/11.14 - BERNAREGGIO/CLIP")
ARCHIVE_ROOT = Path("/Volumes/WORK")
WORK_ROOT = Path(os.environ.get("HANDOVER_WORK", Path.home() / "handover-work"))

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}

# Glossario (§6.5): nomi propri attesi, usati per contare gli errori sui nomi.
GLOSSARY = ["Simone", "Venezia", "Immobiliare Venezia", "Bernareggio"]


def work_dir(clip_dir: Path) -> Path:
    shooting = clip_dir.parent.name.replace(" ", "")
    return WORK_ROOT / "spike-01" / shooting


def default_reel(clip_dir: Path) -> Path:
    return clip_dir.parent / f"{clip_dir.parent.name}.mp4"


def guard_output(path: Path, *protected: Path) -> Path:
    """Rifiuta qualsiasi scrittura dentro l'archivio o nella cartella delle clip."""
    p = path.expanduser().resolve()
    for root in (ARCHIVE_ROOT, *protected):
        r = root.expanduser().resolve()
        if p == r or r in p.parents:
            raise SystemExit(f"Rifiutato: {p} è dentro {r}. Gli originali non si toccano.")
    return p


def out_path(path: Path, *protected: Path) -> Path:
    p = guard_output(path, *protected)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def timer(store: dict, key: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        store[key] = round(time.perf_counter() - t0, 3)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Comando fallito ({res.returncode}): {' '.join(cmd)}\n{res.stderr[-2000:]}")
    return res


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_json(path: Path):
    return json.loads(path.read_text())


def machine_info() -> dict:
    import platform
    info = {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}
    if sys.platform == "darwin":
        for key, cmd in (("cpu", ["sysctl", "-n", "machdep.cpu.brand_string"]),
                         ("mem_bytes", ["sysctl", "-n", "hw.memsize"])):
            try:
                info[key] = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
            except OSError:
                pass
    try:
        info["ffmpeg"] = run(["ffmpeg", "-hide_banner", "-version"]).stdout.splitlines()[0]
    except Exception:  # noqa: BLE001
        pass
    return info
