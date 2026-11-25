"""`handover render <piano.json>`: l'unico punto di contatto con Remotion (render/), come da CLAUDE.md."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

RENDER_DIR = Path(__file__).resolve().parent.parent / "render"


def render_cmd(plan: Path, out: Path, public_dir: Path) -> list[str]:
    cmd = ["npx", "remotion", "render", "src/index.ts", "Reel", str(out),
           f"--props={plan}", f"--public-dir={public_dir}", "--codec=h264", "--crf=18",
           "--audio-codec=aac", "--audio-bitrate=320k"]
    chrome = os.environ.get("HANDOVER_CHROME")
    if chrome:
        cmd.append(f"--browser-executable={chrome}")
    return cmd


def render_plan(plan: Path, out: Path | None = None, log: Callable[[str], None] = print) -> Path:
    plan = plan.resolve()
    work = plan.parent.parent           # <work>/<shooting>/plan/vN.json
    if not (work / "mezzanine").is_dir():
        raise FileNotFoundError(f"Mezzanine non trovati in {work}: il piano va reso dalla sua cartella di lavoro")
    out = (out or work / "render" / f"{plan.stem}.mp4").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("npx"):
        raise RuntimeError("Node.js non trovato: serve per Remotion (`brew install node`).")
    if not (RENDER_DIR / "node_modules").exists():
        log("Installo le dipendenze di Remotion (una volta sola)…")
        subprocess.run(["npm", "ci"], cwd=RENDER_DIR, check=True)
    subprocess.run(render_cmd(plan, out, work), cwd=RENDER_DIR, check=True)
    return out
