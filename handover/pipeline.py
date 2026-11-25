"""Orchestrazione della pipeline video (M2): dallo shooting al piano di montaggio.

Passi e artefatti (vedi handover.workdir): probe → mezzanine → audio → vad → trascrizione →
take → scelta → piano. Ogni passo salta se il suo artefatto esiste già; `redo_from` rifà da un passo in poi.
Nessuna scrittura nella cartella dello shooting.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from handover.ingest.probe import probe_folder
from handover.library import CATEGORIE_SFX, Library, make_placeholders
from handover.video import media, motion as motionmod, plan as planmod, takes as takesmod, vad as vadmod
from handover.video.selection import run_claude, select
from handover.video.subtitles import Glossary
from handover.video.transcribe import MlxWhisper
from handover.workdir import Workspace, read_json, shooting_id, work_root, write_json

STEPS = ("probe", "mezzanine", "movimento", "vad", "trascrizione", "take", "scelta", "piano")
ARTIFACTS = {
    "probe": ["probe.json"],
    "mezzanine": ["mezzanine", "mezzanine_raw"],
    "movimento": ["motion.json"],  # i mezzanine stabilizzati tornano originali (vedi clear_from)
    "vad": ["audio", "vad.json"],
    "trascrizione": ["transcripts"],
    "take": ["takes.json"],
    "scelta": ["selection.json"],
    "piano": [],  # i piani non si cancellano mai: una nuova versione per ogni rigenerazione (§7)
}

Log = Callable[[str], None]


def _year(infos) -> int | None:
    for i in infos:
        if i.creation_time:
            try:
                return datetime.fromisoformat(i.creation_time.replace("Z", "+00:00")).year
            except ValueError:
                pass
    return None


def open_workspace(shooting: Path) -> tuple[Workspace, list]:
    """Probe delle clip e cartella di lavoro dello shooting."""
    from handover.workdir import find_clip_dir
    infos = probe_folder(find_clip_dir(shooting))
    if not infos:
        raise FileNotFoundError(f"Nessuna clip video in {find_clip_dir(shooting)}")
    ws = Workspace(shooting=shooting, root=work_root() / shooting_id(shooting, _year(infos)))
    return ws, infos


def _stage(ws: Workspace, lib: Library, t) -> dict:
    """Copia un file della libreria nella cartella di lavoro (lib/…): il piano resta autosufficiente."""
    dst = ws.path("lib", t.file)
    if not dst.exists():
        shutil.copy2(lib.path(t), dst)
    return {"file": f"lib/{t.file}", "license_id": t.licenza_id, "fonte": t.fonte}


def clear_from(ws: Workspace, step: str) -> None:
    raw = ws.root / "mezzanine_raw"
    if step == "movimento" and raw.is_dir():  # si rifà la stabilizzazione partendo dai mezzanine originali
        for f in raw.glob("*.mov"):
            f.replace(ws.root / "mezzanine" / f.name)
    for s in STEPS[STEPS.index(step):]:
        for name in ARTIFACTS[s]:
            p = ws.root / name
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()


def run_video(shooting: Path, *, agent: str = "venezia", encoder: str = "h264_videotoolbox",
              hw_decode: bool = True, transcriber=None, llm=run_claude, redo_from: str | None = None,
              vad_factory=None, log: Log = print) -> Path:
    ws, infos = open_workspace(shooting)
    if redo_from:
        clear_from(ws, redo_from)
    glossary = Glossary.load(agent)
    log(f"Cartella di lavoro: {ws.root}")

    # probe
    probe_path = ws.path("probe.json")
    if not probe_path.exists():
        write_json(probe_path, [i.to_dict() for i in infos])
    probe = {Path(p["file"]).stem: dict(p, file_name=Path(p["file"]).name) for p in read_json(probe_path)}
    usable = {k: p for k, p in probe.items() if "hlg_o_pq" not in p["flags"]}
    for k in sorted(set(probe) - set(usable)):
        log(f"  {k}: HLG/PQ, esclusa (§6.1)")

    # mezzanine
    todo = [k for k in usable if not (ws.root / "mezzanine" / f"{k}.mov").exists()]
    for n, k in enumerate(todo, 1):
        log(f"Mezzanine {n}/{len(todo)}: {k}")
        media.make_mezzanine(Path(usable[k]["file"]), ws.path("mezzanine", f"{k}.mov"),
                             encoder=encoder, hw_decode=hw_decode)

    # movimento di camera e stabilizzazione dove serve (§6.1, rev. 8)
    motion_path = ws.root / "motion.json"
    if not motion_path.exists():
        motion = {}
        can_stab = media.has_filter("vidstabtransform")
        for n, k in enumerate(sorted(usable, key=takesmod.clip_number), 1):
            log(f"Movimento {n}/{len(usable)}: {k}")
            mez = ws.root / "mezzanine" / f"{k}.mov"
            m = motionmod.analyze(mez)
            m["stabilized"] = False
            if m["needs_stabilization"]:
                if can_stab:
                    raw = ws.path("mezzanine_raw", f"{k}.mov")
                    mez.replace(raw)
                    media.stabilize(raw, mez, encoder=encoder)
                    m["stabilized"] = True
                else:
                    m["flag"] = "stabilizzazione_non_disponibile"
            motion[k] = m
        write_json(ws.path("motion.json"), motion)
        stab = [k for k, m in motion.items() if m["stabilized"]]
        log(f"Movimento: {sum(1 for m in motion.values() if m['entry'] or m['exit'])} clip con movimenti "
            f"d'ingresso/uscita, {len(stab)} stabilizzate" + (f" ({' '.join(stab)})" if stab else ""))
        if not can_stab and any(m["needs_stabilization"] for m in motion.values()):
            log("  ATTENZIONE: ffmpeg senza vidstab, nessuna stabilizzazione")
    motion = read_json(motion_path)

    # audio + vad
    vad_path = ws.root / "vad.json"
    if not vad_path.exists():
        detector = (vad_factory or vadmod.SileroVAD)()
        out = {}
        for k in sorted(usable, key=takesmod.clip_number):
            wav = ws.path("audio", f"{k}.wav")
            if not wav.exists():
                media.extract_audio16k(ws.root / "mezzanine" / f"{k}.mov", wav)
            audio = vadmod.read_wav16k(wav)
            segs = vadmod.speech_segments(detector.probs(audio), duration_s=len(audio) / vadmod.SR)
            out[k] = {"kind": vadmod.classify(segs), "speech": segs,
                      "speech_s": round(sum(b - a for a, b in segs), 2)}
        write_json(ws.path("vad.json"), out)
        aroll = sum(1 for v in out.values() if v["kind"] == "aroll")
        log(f"VAD: {aroll} A-roll, {len(out) - aroll} b-roll")
    vad = read_json(vad_path)
    aroll = [k for k in sorted(vad, key=takesmod.clip_number) if vad[k]["kind"] == "aroll"]
    if not aroll:
        raise RuntimeError("Nessuna clip con parlato: niente reel (flag \"solo b-roll\", §11).")

    # trascrizione (solo A-roll), con le parole fuori dal parlato tolte
    todo = [k for k in aroll if not (ws.root / "transcripts" / f"{k}.json").exists()]
    if todo:
        tr = transcriber or MlxWhisper()
        for n, k in enumerate(todo, 1):
            log(f"Trascrizione {n}/{len(todo)}: {k}")
            raw = tr(ws.root / "audio" / f"{k}.wav")
            segs, removed = vadmod.filter_words(raw["segments"], [tuple(s) for s in vad[k]["speech"]])
            write_json(ws.path("transcripts", f"{k}.json"),
                       {"model": raw.get("model"), "segments": segs, "removed": removed, "raw_text": raw["text"]})
    transcripts = {k: read_json(ws.root / "transcripts" / f"{k}.json") for k in aroll}

    # take
    takes_path = ws.root / "takes.json"
    if not takes_path.exists():
        times = {}
        for k in aroll:
            ct = probe[k].get("creation_time")
            times[k] = datetime.fromisoformat(ct.replace("Z", "+00:00")) if ct else None
        battute = takesmod.find_battute(transcripts, times)
        write_json(ws.path("takes.json"), {"battute": battute})
        log(f"Take: {len(battute)} battute, {sum(1 for b in battute if len(b['takes']) > 1)} con più take")
    battute = read_json(takes_path)["battute"]

    # scelta
    sel_path = ws.root / "selection.json"
    if not sel_path.exists():
        log("Scelta delle take…")
        sel = select(battute, llm=llm, motion=motion)
        write_json(ws.path("selection.json"), sel)
        if sel["source"] != "llm" and llm is not None:
            log("ATTENZIONE: scelta fatta con la regola locale, non con Claude:")
            for e in sel.get("llm_errors", []):
                log(f"  {e}")
            log("  Corretto il problema, rifai la scelta con: handover run <cartella> --da scelta")
        log(f"Scelta: {len(sel['order'])} battute ({sel['source']}), {len(sel['flags'])} da confermare")
    selection = read_json(sel_path)

    # libreria: SFX segnaposto se mancano, musica scelta sulla durata del reel (§6.4)
    lib = Library()
    for t in make_placeholders(lib):
        log(f"Libreria: aggiunto SFX segnaposto {t.id} ({t.categoria}), generato localmente")
    draft, _ = planmod.build_plan(ws.root.name, battute, selection, probe, glossary, motion=motion)
    duration_s = sum(planmod.frames_of(s) for s in draft["segments"]) / planmod.FPS
    music, music_flags = lib.choose_music(duration_s)
    assets = {"music": _stage(ws, lib, music) if music else None, "flags": music_flags,
              "sfx": {c: _stage(ws, lib, t) for c in CATEGORIE_SFX if (t := lib.choose_sfx(c))}}

    # piano (versionato): nuovo solo se cambiano gli ingressi
    digest = hashlib.sha256(json.dumps([battute, selection["order"], glossary.__dict__, planmod.PLAN_VERSION,
                                        motion, assets], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    versions = ws.plan_versions()
    if versions and not redo_from:  # con --da si crea sempre una versione nuova
        meta = versions[-1].with_suffix(".meta.json")
        if meta.exists() and read_json(meta).get("inputs") == digest:
            log(f"Piano invariato: {versions[-1]}")
            return versions[-1]
    plan, review = planmod.build_plan(ws.root.name, battute, selection, probe, glossary, motion=motion, assets=assets)
    path = ws.next_plan_path()
    write_json(path, plan)
    write_json(path.with_suffix(".meta.json"), {"inputs": digest, "created_at": datetime.now().isoformat()})
    write_json(ws.path("review.json"), review | {"plan": path.name})
    log(f"Piano {path.name}: {len(plan['segments'])} segmenti, {review['duration_s']:.1f} s, "
        f"{len(review['critical'])} token critici da confermare")
    for f in review["flags"]:
        log(f"  flag: {f['flag']}")
    return path
