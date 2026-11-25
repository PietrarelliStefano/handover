"""handover.video.takes sulle frasi reali di Bernareggio (stesse attese dello spike)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from handover.video.takes import find_battute, heuristic_pick

FIX = json.loads((Path(__file__).parent / "fixtures" / "bernareggio_takes.json").read_text())


def transcript(sentences: list[str]) -> dict:
    segs, t = [], 0.0
    for s in sentences:
        if s == "|":
            t += 2.0
            continue
        words = []
        for w in s.split():
            words.append({"w": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
        segs.append({"start": words[0]["start"], "end": words[-1]["end"], "text": s, "words": words})
        t += 0.4
    return {"segments": segs}


def battute():
    trs = {k: transcript(v) for k, v in FIX["clips"].items()}
    t0 = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
    return find_battute(trs, {k: t0 + timedelta(minutes=i) for i, k in enumerate(sorted(trs))})


def of(bs, clip, words):
    for b in bs:
        for t in b["takes"]:
            if t["clip"] == clip and words in t["text"].lower():
                return b["id"]
    raise AssertionError((clip, words))


def test_grouping():
    bs = battute()
    notte = of(bs, "Z50_6402", "box doccia")
    assert {of(bs, c, "disimpegno") for c in ("Z50_6399", "Z50_6400", "Z50_6401")} == {notte}
    assert len({of(bs, "Z50_6416", w) for w in ("agente immobiliare", "posso esserti utile", "sto cercando")}) == 3
    assert of(bs, "Z50_6413", "agente immobiliare") == of(bs, "Z50_6416", "agente immobiliare")
    assert of(bs, "Z50_6410", "cantina") != of(bs, "Z50_6410", "chiederai")


def test_heuristic_pick_is_last_complete_take():
    bs = battute()
    b = next(b for b in bs if b["id"] == of(bs, "Z50_6402", "box doccia"))
    picked = next(t for t in b["takes"] if t["take"] == heuristic_pick(b))
    assert picked["clip"] == "Z50_6402" and "box doccia" in picked["text"]
    assert [t["clip"] for t in b["takes"]] == sorted(t["clip"] for t in b["takes"])  # ordine di ripresa
