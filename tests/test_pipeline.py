"""handover run su uno shooting sintetico: ffmpeg vero, Whisper e VAD finti (test offline)."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from handover.pipeline import run_video
from handover.video.vad import CHUNK, SR

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg assente")

SCRIPT = {  # clip → frasi dette (None = b-roll)
    "Z50_0001": ["Ehi scusa ma tu sei un agente immobiliare?", "Sì posso esserti utile."],
    "Z50_0002": None,
    "Z50_0003": ["L'appartamento è concluso dalla cantina.", "Mi chiederai il prezzo, 188 mila euro."],
    "Z50_0004": ["L'appartamento è concluso dalla cantina.", "Mi chiederai il prezzo, 188 mila euro.",
                 "Contattami, io sono Simone Venezia."],
}


def make_clip(path: Path, seconds: float) -> None:
    src = path.with_suffix(".src.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=f=300:sample_rate=48000", "-t", str(seconds),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(src)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", str(src), "-c", "copy",
                    str(path)], check=True)
    src.unlink()


class FakeWhisper:
    def __call__(self, audio: Path) -> dict:
        segs, t = [], 0.5
        for s in SCRIPT[audio.stem]:
            words = []
            for w in s.split():
                words.append({"w": w, "start": round(t, 2), "end": round(t + 0.3, 2), "p": 0.9})
                t += 0.35
            segs.append({"start": words[0]["start"], "end": words[-1]["end"], "text": s, "words": words,
                         "avg_logprob": -0.2, "no_speech_prob": 0.01})
            t += 0.5
        return {"text": " ".join(SCRIPT[audio.stem]), "segments": segs, "model": "fake"}


class FakeVAD:
    """Parlato su tutta la clip, tranne la b-roll (riconosciuta dalla durata di 2 s)."""

    def probs(self, audio):
        n = int(np.ceil(len(audio) / CHUNK))
        return np.zeros(n) if abs(len(audio) / SR - 2.0) < 0.05 else np.ones(n)


@pytest.fixture
def shooting(tmp_path, monkeypatch):
    monkeypatch.setenv("HANDOVER_WORK", str(tmp_path / "work"))
    sh = tmp_path / "11.14 - PROVA"
    (sh / "CLIP").mkdir(parents=True)
    for clip, lines in SCRIPT.items():
        make_clip(sh / "CLIP" / f"{clip}.MOV", 2.0 if lines is None else 8.0)
    return sh


def test_run_video_end_to_end(shooting, tmp_path):
    before = sorted(p.name for p in (shooting / "CLIP").iterdir())
    logs = []
    plan_path = run_video(shooting, encoder="libx264", hw_decode=False, transcriber=FakeWhisper(),
                          llm=None, vad_factory=FakeVAD, log=logs.append)
    work = plan_path.parent.parent
    assert sorted(p.name for p in (shooting / "CLIP").iterdir()) == before   # originali intatti
    assert plan_path.name == "v1.json" and work.name.endswith("-11-14-prova")

    vad = json.loads((work / "vad.json").read_text())
    assert vad["Z50_0002"]["kind"] == "broll" and not (work / "transcripts" / "Z50_0002.json").exists()

    plan = json.loads(plan_path.read_text())
    words = [w["t"].rstrip(".,?") for s in plan["segments"] for w in s["words"]]
    text = " ".join(words)
    assert text.count("cantina") == 1 and text.count("€188.000") == 1     # niente frasi ripetute
    assert words[-2:] == ["Simone", "Venezia"]                             # chiusura in fondo
    assert all(s["clip"].endswith(".MOV") and s["in_ms"] < s["out_ms"] for s in plan["segments"])
    review = json.loads((work / "review.json").read_text())
    assert {c["t"] for c in review["critical"]} >= {"€188.000", "Simone", "Venezia"}

    # rilancio: nessun passo rifatto, stesso piano
    again = run_video(shooting, encoder="libx264", hw_decode=False, transcriber=None, llm=None,
                      vad_factory=FakeVAD, log=logs.append)
    assert again == plan_path and "Piano invariato" in logs[-1]
