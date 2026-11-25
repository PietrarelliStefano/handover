from handover.video.plan import FPS, build_plan, take_pieces
from handover.video.subtitles import Glossary

G = Glossary.load("venezia")


def words(spec):
    """spec: [(testo, start_s)] con parole da 0,3 s."""
    return [{"w": t, "start": s, "end": s + 0.3} for t, s in spec]


def take(tid, clip, spec, complete=True):
    ws = words(spec)
    return {"take": tid, "clip": clip, "start": ws[0]["start"], "end": ws[-1]["end"],
            "text": " ".join(w["w"] for w in ws), "complete": complete, "n_words": len(ws), "words": ws}


def test_long_silence_is_shortened_to_150ms():
    ws = [{"t": "a", "start_ms": 1000, "end_ms": 1300, "critical": False},
          {"t": "b", "start_ms": 1400, "end_ms": 1700, "critical": False},   # pausa 100 ms: resta
          {"t": "c", "start_ms": 2500, "end_ms": 2800, "critical": False}]   # pausa 800 ms: taglio
    pieces = take_pieces(ws, clip_ms=5000)
    assert [(a, b) for a, b, _ in pieces] == [(880, 1760), (2440, 3000)]
    gap_kept = (1760 - 1700) + (2500 - 2440)
    assert abs(gap_kept - 150) <= 1000 / FPS  # 150 ms, arrotondati al fotogramma
    assert all(a % 40 == 0 and b % 40 == 0 for a, b, _ in pieces)


def test_plan_continuity_zoom_and_review():
    battute = [
        {"id": "b1", "takes": [take("t1", "Z50_0010", [("Sei", 1.0), ("un", 1.3), ("agente?", 1.6)])]},
        {"id": "b2", "takes": [take("t2", "Z50_0010", [("Sì,", 2.0), ("posso", 2.3), ("aiutarti.", 2.6)])]},
        {"id": "b3", "takes": [take("t3", "Z50_0011", [("Costa", 0.5), ("188", 0.8), ("mila", 1.1), ("euro.", 1.4),
                                                      ("Bello", 3.0), ("vero.", 3.3)])]},
    ]
    sel = {"order": [{"battuta": "b1", "take": "t1", "role": "aggancio"},
                     {"battuta": "b2", "take": "t2", "role": "aggancio"},
                     {"battuta": "b3", "take": "t3", "role": "chiusura"}], "flags": [], "source": "llm"}
    probe = {"Z50_0010": {"duration_s": 5.0, "rotation": 90, "file_name": "Z50_0010.MOV"},
             "Z50_0011": {"duration_s": 5.0, "rotation": 90, "file_name": "Z50_0011.MOV"}}
    plan, review = build_plan("2026-11-14-test", battute, sel, probe, G)
    segs = plan["segments"]
    assert plan["version"] == 1 and plan["format"] == {"w": 1440, "h": 2560, "fps": 25}
    # b1 e b2 sono contigue nella stessa clip: un segmento; b3 ha un silenzio lungo → due pezzi, jump cut
    assert [(s["clip"], s["zoom"]) for s in segs] == [("Z50_0010.MOV", 1.0), ("Z50_0011.MOV", 1.0), ("Z50_0011.MOV", 1.1)]
    assert [w["t"] for w in segs[1]["words"]] == ["Costa", "€188.000."]
    assert review["critical"] == [{"segment": "s2", "t": "€188.000", "reason": "numero", "clip": "Z50_0011.MOV",
                                   "start_ms": 800}]
    assert all(set(s) == {"id", "type", "clip", "rotation", "in_ms", "out_ms", "zoom", "words"} for s in segs)
