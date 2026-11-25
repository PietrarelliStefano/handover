"""Raggruppamento delle take sui casi problematici del primo giro dello spike (Bernareggio)."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = json.loads((ROOT / "tests" / "fixtures" / "bernareggio_takes.json").read_text())


def _transcript(name: str, sentences: list[str]) -> dict:
    segs, t = [], 0.0
    for s in sentences:
        if s == "|":  # pausa lunga
            t += 2.0
            continue
        words = []
        for w in s.split():
            words.append({"w": w, "start": round(t, 2), "end": round(t + 0.3, 2), "p": 0.9})
            t += 0.35
        segs.append({"start": words[0]["start"], "end": words[-1]["end"], "text": s, "words": words})
        t += 0.4  # pausa breve tra frasi (sotto la soglia di 0,7 s)
    return {"file": name, "text": " ".join(x["text"] for x in segs), "segments": segs}


def run_takes(tmp_path: Path) -> dict:
    shoot = tmp_path / "work" / "spike-01" / "11.14-TAKES"
    tdir = shoot / "transcripts" / "turbo"
    tdir.mkdir(parents=True)
    probe = []
    for i, (name, sents) in enumerate(sorted(FIX["clips"].items())):
        (tdir / f"{name}.json").write_text(json.dumps(_transcript(name, sents)))
        probe.append({"file": f"/x/{name}.MOV", "creation_time": f"2026-11-14T10:{i:02d}:00Z"})
    (shoot / "probe.json").write_text(json.dumps(probe))
    clip_dir = tmp_path / "11.14 - TAKES" / "CLIP"
    env = {"HANDOVER_WORK": str(tmp_path / "work"), "PATH": "/usr/bin:/bin"}
    res = subprocess.run([sys.executable, str(ROOT / "spikes" / "s05_takes.py"), str(clip_dir), "--variant", "turbo"],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    return json.loads((shoot / "results" / "takes-turbo.json").read_text())


def _battuta_of(result: dict, clip: str, words: str) -> int:
    for b in result["battute"]:
        for t in b["takes"]:
            if t["clip"] == clip and words in t["text"].lower():
                return b["n"]
    raise AssertionError(f"{clip} «{words}» non trovata")


def test_bernareggio_takes(tmp_path):
    r = run_takes(tmp_path)
    b = lambda clip, words: _battuta_of(r, clip, words)  # noqa: E731

    # zona notte: tutte le take insieme, compresa quella interrotta di 6399 (mancata nel primo giro)
    notte = b("Z50_6402", "box doccia")
    assert {b(c, "disimpegno") for c in ("Z50_6399", "Z50_6400", "Z50_6401")} == {notte}

    # apertura: domanda, risposta e "sto cercando" sono battute diverse (fuse in una nel primo giro)
    domanda = b("Z50_6416", "agente immobiliare")
    risposta = b("Z50_6416", "posso esserti utile")
    cerco = b("Z50_6416", "sto cercando")
    assert len({domanda, risposta, cerco}) == 3
    assert b("Z50_6415", "agente immobiliare") == domanda
    assert b("Z50_6412", "agente immobiliare") == domanda
    assert b("Z50_6413", "agente immobiliare") == domanda  # pezzo della take detta d'un fiato
    assert b("Z50_6412", "sto cercando") == cerco

    # cantina e prezzo restano battute distinte; la chiusura è una battuta a sé
    assert b("Z50_6410", "cantina") != b("Z50_6410", "chiederai")
    assert b("Z50_6411", "simone venezia") == b("Z50_6408", "simone venezia")
