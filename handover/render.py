"""`handover render <piano.json>`: l'unico punto di contatto con Remotion (render/), come da CLAUDE.md."""

from __future__ import annotations

import json
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
    raw = out.with_name(out.stem + ".raw.mp4")
    subprocess.run(render_cmd(plan, raw, work), cwd=RENDER_DIR, check=True)
    target = json.loads(plan.read_text()).get("audio", {}).get("voice_lufs", -14)
    stats = loudnorm(raw, out, target)
    raw.unlink()
    (out.with_suffix(".json")).write_text(json.dumps(stats, indent=2))
    log(f"Loudness: {stats['input_i']} → {stats['output_i']} LUFS, true peak {stats['output_tp']} dBTP")
    return out


def loudnorm(src: Path, dst: Path, target_lufs: float = -14, true_peak: float = -1.0, lra: float = 11) -> dict:
    """Normalizzazione EBU R128 in due passate sul mix finale (§6.4, rev. 8); il video viene copiato."""
    filt = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
    first = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(src), "-vn",
                            "-af", filt + ":print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, check=True).stderr
    m = json.loads(first[first.rindex("{"):first.rindex("}") + 1])
    second = (f"{filt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
              f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    res = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0",
                          "-c:v", "copy", "-af", second, "-ar", "48000", "-c:a", "aac", "-b:a", "320k",
                          "-movflags", "+faststart", str(dst)], capture_output=True, text=True, check=True).stderr
    out = json.loads(res[res.rindex("{"):res.rindex("}") + 1])
    return {"target_i": target_lufs, "target_tp": true_peak, "input_i": float(m["input_i"]),
            "input_tp": float(m["input_tp"]), "output_i": float(out["output_i"]), "output_tp": float(out["output_tp"]),
            "normalization": out.get("normalization_type")}
