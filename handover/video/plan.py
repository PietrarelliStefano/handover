"""Piano di montaggio JSON, versione 1 (§7): il contratto tra analisi e render.

M2: solo A-roll e sottotitoli. Regole:
- silenzi interni > 300 ms accorciati a 150 ms (§6.2.5): il taglio diventa un jump cut;
- take consecutive della stessa clip senza salto restano un pezzo continuo;
- ogni jump cut dentro la stessa clip alterna lo zoom 100% / 110% (§6.3.2, finché non c'è b-roll);
- parlato oltre 90 s → flag (§6.3).
Le informazioni per la review (token critici, take da confermare) vanno in review.json, non nel piano.
"""

from __future__ import annotations

from handover.video.subtitles import Glossary, subtitle_words

PLAN_VERSION = 1
FPS = 25
FORMAT = {"w": 1440, "h": 2560, "fps": FPS}
LEAD_IN_MS = 120
TAIL_MS = 200
MAX_SILENCE_MS = 300
KEEP_SILENCE_MS = 150
CONTIGUOUS_MS = 40
MAX_SPEECH_S = 90
ZOOMS = (1.0, 1.1)


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


def build_plan(shooting_id: str, battute: list[dict], selection: dict, probe: dict[str, dict],
               glossary: Glossary) -> tuple[dict, dict]:
    """Ritorna (piano §7, informazioni per la review)."""
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
                review["critical"].append({"segment": sid, "t": w["t"], "reason": w.get("reason"),
                                           "clip": m["file"], "start_ms": w["start_ms"]})

    total_s = sum(s["out_ms"] - s["in_ms"] for s in segments) / 1000
    review["duration_s"] = round(total_s, 2)
    if total_s > MAX_SPEECH_S:
        review["flags"].append({"flag": "parlato_oltre_90s", "duration_s": round(total_s, 1)})
    plan = {"version": PLAN_VERSION, "shooting_id": shooting_id, "format": FORMAT,
            "template": glossary.template, "segments": segments,
            "audio": {"music": None, "voice_lufs": -14}, "end_card": True}
    return plan, review
