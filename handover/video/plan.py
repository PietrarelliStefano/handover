"""Piano di montaggio JSON, versione 2 (§7, rev. 8): il contratto tra analisi e render.

A-roll, sottotitoli, movimenti di camera ai tagli, SFX, musica, fade di chiusura. Regole:
- silenzi interni > 300 ms accorciati a 150 ms (§6.2.5): il taglio diventa un jump cut;
- take consecutive della stessa clip senza salto restano un pezzo continuo;
- ogni jump cut dentro la stessa clip alterna lo zoom 100% / 110% (§6.3.2, finché non c'è b-roll);
- parlato oltre 90 s → flag (§6.3);
- ai tagli tra clip diverse si tengono il movimento d'uscita e quello d'ingresso, se attaccati al parlato (§6.3.4);
- chiusura con fade a nero, usando la coda della clip (§6.3.5);
- SFX: whoosh sui tagli con movimento, accento sul prezzo; al massimo uno ogni 2 s (§6.4).
Le informazioni per la review (token critici, take da confermare) vanno in review.json, non nel piano.
"""

from __future__ import annotations

from handover.video.subtitles import Glossary, subtitle_words

PLAN_VERSION = 2
FPS = 25
FORMAT = {"w": 1440, "h": 2560, "fps": FPS}
LEAD_IN_MS = 120
TAIL_MS = 200
MAX_SILENCE_MS = 300
KEEP_SILENCE_MS = 150
CONTIGUOUS_MS = 40
MAX_SPEECH_S = 90
ZOOMS = (1.0, 1.1)
MOVE_ATTACH_MS = 600     # il movimento deve essere attaccato al parlato scelto
MOVE_MAX_MS = 2000       # al massimo 2 s di movimento per lato del taglio
FADE_OUT_MS = 1200
MIN_FADE_MS = 400
SFX_GAIN_DB = -12
SFX_MIN_GAP_MS = 2000
WHOOSH_LEAD_MS = 200
MUSIC = {"gain_db": -20, "duck": True, "fade_in_ms": 500, "fade_out_ms": 1500}


def _frame(ms: float) -> int:
    """Arrotonda al fotogramma (40 ms a 25 fps): i tagli cadono sempre su un fotogramma intero."""
    step = 1000 / FPS
    return int(round(ms / step) * step)


def take_pieces(words: list[dict], clip_ms: int | None = None) -> list[tuple[int, int, list[dict]]]:
    """Divide le parole di una take nei pezzi che restano dopo aver accorciato i silenzi lunghi.
    words: parole dei sottotitoli in ms (subtitle_words). Ritorna [(in_ms, out_ms, parole)]."""
    if not words:
        return []
    pieces: list[list[dict]] = [[words[0]]]
    for prev, w in zip(words, words[1:]):
        if w["start_ms"] - prev["end_ms"] > MAX_SILENCE_MS:
            pieces.append([w])
        else:
            pieces[-1].append(w)
    half = KEEP_SILENCE_MS // 2
    out = []
    for k, ws in enumerate(pieces):
        a = ws[0]["start_ms"] - (LEAD_IN_MS if k == 0 else half)
        b = ws[-1]["end_ms"] + (TAIL_MS if k == len(pieces) - 1 else half)
        a = max(0, _frame(a))
        b = _frame(b) if clip_ms is None else min(_frame(b), clip_ms)
        out.append((a, b, ws))
    return out


def frames_of(seg: dict, fps: int = FPS) -> int:
    """Durata in fotogrammi come la calcola il render (render/src/plan.ts: segmentFrames)."""
    return max(1, round(seg["out_ms"] * fps / 1000) - round(seg["in_ms"] * fps / 1000))


def apply_moves(merged: list[dict], motion: dict[str, dict], clip_ms: dict[str, int | None]) -> None:
    """Allarga in place i segmenti ai tagli tra clip diverse per tenere i movimenti di camera."""
    for k, m in enumerate(merged):
        mo = motion.get(m["clip"]) or {}
        first_of_run = k == 0 or merged[k - 1]["clip"] != m["clip"]
        last_of_run = k == len(merged) - 1 or merged[k + 1]["clip"] != m["clip"]
        entry, exit_ = mo.get("entry"), mo.get("exit")
        if first_of_run and entry and entry["start_ms"] < m["in_ms"] <= entry["end_ms"] + MOVE_ATTACH_MS:
            m["in_ms"] = _frame(max(entry["start_ms"], m["in_ms"] - MOVE_MAX_MS))
            m["move_in"] = entry["kind"]
        if last_of_run and exit_ and exit_["start_ms"] - MOVE_ATTACH_MS <= m["out_ms"] < exit_["end_ms"]:
            end = min(exit_["end_ms"], m["out_ms"] + MOVE_MAX_MS)
            if clip_ms.get(m["clip"]):
                end = min(end, clip_ms[m["clip"]])
            m["out_ms"] = _frame(end)
            m["move_out"] = exit_["kind"]


def build_plan(shooting_id: str, battute: list[dict], selection: dict, probe: dict[str, dict],
               glossary: Glossary, motion: dict[str, dict] | None = None,
               assets: dict | None = None) -> tuple[dict, dict]:
    """Ritorna (piano §7 v2, informazioni per la review).
    motion: clip → analisi di handover.video.motion; assets: {"music": {...}|None, "sfx": {categoria: {...}}}
    con percorsi già relativi alla cartella di lavoro (li copia la pipeline)."""
    motion = motion or {}
    assets = assets or {"music": None, "sfx": {}}
    takes = {t["take"]: (b["id"], t) for b in battute for t in b["takes"]}
    raw: list[dict] = []
    review = {"critical": [], "takes": selection.get("flags", []), "flags": [], "source": selection.get("source")}
    for item in selection["order"]:
        bid, take = takes[item["take"]]
        clip = take["clip"]
        info = probe.get(clip, {})
        clip_ms = round(info["duration_s"] * 1000) if info.get("duration_s") else None
        words = subtitle_words(take["words"], glossary)
        for a, b, ws in take_pieces(words, clip_ms):
            raw.append({"clip": clip, "file": info.get("file_name", clip), "rotation": info.get("rotation", 0),
                        "in_ms": a, "out_ms": b, "words": ws, "battuta": bid, "role": item.get("role")})

    # pezzi contigui della stessa clip (anche di battute diverse) → un solo segmento
    merged: list[dict] = []
    for r in raw:
        last = merged[-1] if merged else None
        if last and last["clip"] == r["clip"]:
            if r["in_ms"] < last["out_ms"] <= r["out_ms"]:
                r = dict(r, in_ms=last["out_ms"])  # margini sovrapposti: si riparte da dove finisce il pezzo prima
            if abs(r["in_ms"] - last["out_ms"]) <= CONTIGUOUS_MS:
                last["out_ms"] = r["out_ms"]
                last["words"] += r["words"]
                continue
        merged.append(dict(r, words=list(r["words"])))

    clip_ms = {r["clip"]: (round(probe[r["clip"]]["duration_s"] * 1000) if probe.get(r["clip"], {}).get("duration_s")
                           else None) for r in merged}
    apply_moves(merged, motion, clip_ms)

    # chiusura: coda per il fade a nero, senza coprire il parlato
    fade_ms = 0
    if merged:
        last = merged[-1]
        last_word = last["words"][-1]["end_ms"] if last["words"] else last["in_ms"]
        want = last_word + TAIL_MS + FADE_OUT_MS
        if clip_ms.get(last["clip"]):
            want = min(want, clip_ms[last["clip"]])
        last["out_ms"] = max(last["out_ms"], _frame(want))
        fade_ms = min(FADE_OUT_MS, max(MIN_FADE_MS, last["out_ms"] - last_word))

    segments = []
    zoom_i = 0
    for k, m in enumerate(merged):
        prev = merged[k - 1] if k else None
        if prev and prev["clip"] == m["clip"]:
            zoom_i = 1 - zoom_i  # jump cut nella stessa clip
        else:
            zoom_i = 0
        sid = f"s{k + 1}"
        segments.append({"id": sid, "type": "aroll", "clip": m["file"], "rotation": m["rotation"],
                         "in_ms": m["in_ms"], "out_ms": m["out_ms"], "zoom": ZOOMS[zoom_i],
                         "words": [{"t": w["t"], "start_ms": w["start_ms"], "end_ms": w["end_ms"],
                                    "critical": w["critical"]} for w in m["words"]]})
        for w in m["words"]:
            if w["critical"]:
                review["critical"].append({"segment": sid, "t": w["t"].rstrip(".,;:…"), "reason": w.get("reason"),
                                           "clip": m["file"], "start_ms": w["start_ms"]})

    # SFX ancorati ai segmenti (§6.4)
    candidates = []  # (tempo nel reel in ms, evento)
    start_f = 0
    for k, (seg, m) in enumerate(zip(segments, merged)):
        seg_start_ms = start_f * 1000 / FPS
        if k and merged[k - 1]["clip"] != m["clip"] and (merged[k - 1].get("move_out") or m.get("move_in")):
            candidates.append((seg_start_ms - WHOOSH_LEAD_MS,
                               {"kind": "whoosh", "segment": seg["id"], "offset_ms": -WHOOSH_LEAD_MS}))
        for w in m["words"]:
            if w.get("reason") == "numero" and w["t"].startswith("€"):
                off = w["start_ms"] - m["in_ms"]
                candidates.append((seg_start_ms + off, {"kind": "prezzo", "segment": seg["id"], "offset_ms": off}))
        start_f += frames_of(seg)
    sfx, last_at, missing = [], None, set()
    for at, ev in sorted(candidates, key=lambda c: c[0]):
        lib = assets.get("sfx", {}).get(ev["kind"])
        if lib is None:
            missing.add(ev["kind"])
            continue
        if last_at is not None and at - last_at < SFX_MIN_GAP_MS:
            continue
        sfx.append(ev | {"file": lib["file"], "license_id": lib["license_id"], "gain_db": SFX_GAIN_DB})
        last_at = at
    for kind in sorted(missing):
        review["flags"].append({"flag": "sfx_mancante", "categoria": kind})

    music = None
    if assets.get("music"):
        music = {"track": assets["music"]["file"], "license_id": assets["music"]["license_id"]} | MUSIC
    else:
        review["flags"].append({"flag": "musica_mancante", "bloccante": True})
    review["flags"] += [{"flag": f} for f in assets.get("flags", [])]

    total_s = start_f / FPS
    review["duration_s"] = round(total_s, 2)
    review["moves"] = [{"segment": s["id"], "in": m.get("move_in"), "out": m.get("move_out")}
                       for s, m in zip(segments, merged) if m.get("move_in") or m.get("move_out")]
    if total_s > MAX_SPEECH_S:
        review["flags"].append({"flag": "parlato_oltre_90s", "duration_s": round(total_s, 1)})
    plan = {"version": PLAN_VERSION, "shooting_id": shooting_id, "format": FORMAT,
            "template": glossary.template, "segments": segments,
            "audio": {"music": music, "sfx": sfx, "voice_lufs": -14},
            "ending": {"fade_out_ms": fade_ms}, "end_card": False}
    return plan, review
