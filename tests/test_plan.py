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
    assert plan["version"] == 2 and plan["format"] == {"w": 1440, "h": 2560, "fps": 25}
    # b1 e b2 sono contigue nella stessa clip: un segmento; b3 ha un silenzio lungo → due pezzi, jump cut
    assert [(s["clip"], s["zoom"]) for s in segs] == [("Z50_0010.MOV", 1.0), ("Z50_0011.MOV", 1.0), ("Z50_0011.MOV", 1.1)]
    assert [w["t"] for w in segs[1]["words"]] == ["Costa", "€188.000."]
    assert review["critical"] == [{"segment": "s2", "t": "€188.000", "reason": "numero", "clip": "Z50_0011.MOV",
                                   "start_ms": 800}]
    assert all(set(s) == {"id", "type", "clip", "rotation", "in_ms", "out_ms", "zoom", "words"} for s in segs)


ASSETS = {"music": None,
          "sfx": {"whoosh": {"file": "lib/sfx/S-0001.wav", "license_id": "S-0001"},
                  "prezzo": {"file": "lib/sfx/S-0002.wav", "license_id": "S-0002"}}}


def test_moves_at_cuts_sfx_and_fade():
    battute = [
        {"id": "b1", "takes": [take("t1", "Z50_0010", [("Ciao", 1.2), ("a", 1.5), ("tutti.", 1.8)])]},
        {"id": "b2", "takes": [take("t2", "Z50_0011", [("Costa", 1.0), ("188", 1.3), ("mila", 1.6), ("euro.", 1.9)])]},
        {"id": "b3", "takes": [take("t3", "Z50_0012", [("Contattami.", 4.0)])]},
    ]
    sel = {"order": [{"battuta": b["id"], "take": b["takes"][0]["take"], "role": "corpo"} for b in battute],
           "flags": [], "source": "llm"}
    probe = {c: {"duration_s": 8.0, "rotation": 90, "file_name": f"{c}.MOV"} for c in ("Z50_0010", "Z50_0011", "Z50_0012")}
    motion = {
        "Z50_0010": {"entry": None, "exit": {"kind": "pan_right", "start_ms": 2400, "end_ms": 3600, "peak_ms": 3000}},
        "Z50_0011": {"entry": {"kind": "pan_right", "start_ms": 0, "end_ms": 700, "peak_ms": 300},
                     "exit": {"kind": "push_in", "start_ms": 6000, "end_ms": 8000, "peak_ms": 7000}},  # lontano: non si tiene
        "Z50_0012": {"entry": {"kind": "tilt_up", "start_ms": 0, "end_ms": 1000, "peak_ms": 500}, "exit": None},  # lontano
    }
    plan, review = build_plan("x", battute, sel, probe, G, motion=motion, assets=ASSETS)
    s1, s2, s3 = plan["segments"]
    assert s1["out_ms"] == 3600                       # uscita in pan tenuta (era 2300)
    assert s2["in_ms"] == 0 and s2["out_ms"] < 6000  # ingresso tenuto; uscita lontana dal parlato: no
    assert s3["in_ms"] > 1000                         # l'ingresso finisce 3 s prima del parlato: no
    assert plan["ending"]["fade_out_ms"] == 1200 and s3["out_ms"] >= 4300 + 200 + 1200 - 40
    kinds = [(e["kind"], e["segment"]) for e in plan["audio"]["sfx"]]
    assert kinds == [("whoosh", "s2"), ("prezzo", "s2")] or kinds == [("whoosh", "s2")]
    assert plan["audio"]["sfx"][0]["offset_ms"] == -200 and plan["audio"]["sfx"][0]["file"].startswith("lib/sfx/")
    assert plan["audio"]["music"] is None and {"flag": "musica_mancante", "bloccante": True} in review["flags"]
    assert review["moves"] == [{"segment": "s1", "in": None, "out": "pan_right"},
                               {"segment": "s2", "in": "pan_right", "out": None}]


def test_sfx_min_gap_and_missing_category():
    battute = [{"id": "b1", "takes": [take("t1", "Z50_0010", [("€188.000", 0.5), ("e", 0.8), ("€190.000", 1.2)])]}]
    sel = {"order": [{"battuta": "b1", "take": "t1", "role": "corpo"}], "flags": []}
    probe = {"Z50_0010": {"duration_s": 5.0, "file_name": "Z50_0010.MOV"}}
    plan, review = build_plan("x", battute, sel, probe, G, assets={"music": None, "sfx": {"prezzo": ASSETS["sfx"]["prezzo"]}})
    assert [e["kind"] for e in plan["audio"]["sfx"]] == ["prezzo"]   # due prezzi a 0,7 s: uno solo
    plan2, review2 = build_plan("x", battute, sel, probe, G, assets={"music": None, "sfx": {}})
    assert plan2["audio"]["sfx"] == [] and {"flag": "sfx_mancante", "categoria": "prezzo"} in review2["flags"]
