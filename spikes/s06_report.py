"""Spike 01 · passo 6: scrive docs/spike-01.md dai risultati misurati (nessun numero inventato).

    uv run python spikes/s06_report.py [CLIP_DIR] [--out docs/spike-01.md]

Regola di decisione turbo / large-v3 (§6.2.1: "errori sui token critici e tempi"):
  1. vince chi sbaglia meno token critici (numeri + nomi del glossario) sulle clip (misura B),
     a parità sull'audio del reel (misura A);
  2. large-v3 è ammesso solo se la trascrizione di uno shooting tipico resta nel budget;
  3. a parità di token critici: large-v3 solo se migliora il WER sulle clip di almeno 2 punti
     e sta nel budget, altrimenti turbo (default della specifica, più veloce).
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from common import DEFAULT_CLIP_DIR, load_json, work_dir

# Shooting tipico per la proiezione dei tempi (§1: 25–30 clip di 4–30 s): 28 clip × 12 s.
TYPICAL_AUDIO_S = 28 * 12
# Budget per la trascrizione dentro i 15 minuti di §12 (foto e video in parallelo).
BUDGET_S = 5 * 60
REPO_ROOT = Path(__file__).resolve().parent.parent
MANUAL_MARK = "<!-- analisi manuale: sotto questa riga il testo non viene rigenerato -->"


def fmt_s(x) -> str:
    return "—" if x is None else f"{x:.1f} s"


def pct(x) -> str:
    return "—" if x is None else f"{x:.1%}".replace(".", ",")


def table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def crit_count(entry: dict | None) -> int | None:
    if not entry:
        return None
    return len(entry["number_errors"]) + len(entry["name_errors"])


def decide(compare: dict, trans: dict) -> tuple[str, list[str]]:
    v = compare["variants"]
    if "turbo" not in v or "large-v3" not in v:
        return "non decidibile", ["Mancano le trascrizioni di uno dei due modelli."]
    why = []
    proj = {}
    for k in ("turbo", "large-v3"):
        rtf = trans.get(k, {}).get("clips_rtf")
        proj[k] = rtf * TYPICAL_AUDIO_S if rtf else None
        why.append(f"{k}: proiezione per uno shooting tipico ({TYPICAL_AUDIO_S} s di parlato) "
                   f"= {fmt_s(proj[k])} (budget {BUDGET_S // 60} min).")
    large_ok = proj["large-v3"] is not None and proj["large-v3"] <= BUDGET_S

    cb = {k: crit_count(v[k]["clips"]) for k in v}
    ca = {k: crit_count(v[k].get("reel")) for k in v}
    why.append(f"Token critici errati sulle clip: turbo {cb['turbo']}, large-v3 {cb['large-v3']}; "
               f"sull'audio del reel: turbo {ca['turbo']}, large-v3 {ca['large-v3']}.")
    key = lambda k: (cb[k], ca[k] if ca[k] is not None else 0)  # noqa: E731
    if key("large-v3") < key("turbo"):
        if large_ok:
            return "large-v3", why + ["large-v3 sbaglia meno token critici e sta nel budget."]
        why.append("large-v3 sbaglia meno token critici ma supera il budget: resta turbo, "
                   "con conferma in review dei token critici (già obbligatoria).")
        return "turbo", why
    wt, wl = v["turbo"]["clips"]["wer"], v["large-v3"]["clips"]["wer"]
    if key("large-v3") == key("turbo") and wt is not None and wl is not None and wt - wl >= 0.02 and large_ok:
        return "large-v3", why + [f"Token critici pari; large-v3 migliora il WER di {pct(wt - wl)} e sta nel budget."]
    return "turbo", why + ["Token critici non migliori con large-v3: si tiene il default turbo, più veloce."]


def recommend(compare: dict, model: str) -> str | None:
    vs = {k: e for k, e in compare["variants"].items() if k.split("+")[0] == model}
    if not vs:
        return None
    return min(vs, key=lambda k: (crit_count(vs[k]["clips"]), vs[k]["clips"]["wer"] or 1, k.count("+")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", nargs="?", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "spike-01.md")
    args = ap.parse_args()
    wd = work_dir(args.clip_dir)
    res = wd / "results"

    probe = load_json(wd / "probe.json")
    mezz = load_json(res / "mezzanine.json") if (res / "mezzanine.json").exists() else None
    trans = {p.stem.removeprefix("transcribe-"): load_json(p) for p in sorted(res.glob("transcribe-*.json"))}
    compare = load_json(res / "compare.json") if (res / "compare.json").exists() else None
    takes = {p.stem.removeprefix("takes-"): load_json(p) for p in sorted(res.glob("takes-*.json"))}
    subs = load_json(wd / "reel" / "subs_ocr.json") if (wd / "reel" / "subs_ocr.json").exists() else None
    vad = load_json(res / "vad.json") if (res / "vad.json").exists() else None
    reel_map = load_json(res / "reel_map.json") if (res / "reel_map.json").exists() else None
    machine = (mezz or {}).get("summary", {}).get("machine") or next(iter(trans.values()), {}).get("machine", {})

    L: list[str] = []
    L += [f"# Spike 01 — video: mezzanine, trascrizione, take",
          "",
          f"Generato da `spikes/s06_report.py` il {date.today().isoformat()} sui risultati in "
          f"`{wd}`. Shooting: `{args.clip_dir.parent.name}`.",
          "",
          f"Macchina: {machine.get('cpu', machine.get('machine', '?'))}, "
          f"{int(machine['mem_bytes']) // 2**30} GB" if machine.get("mem_bytes") else
          f"Macchina: {machine.get('platform', '?')}",
          f"· {machine.get('ffmpeg', '')}", ""]

    # 1. Probe
    L += ["## 1. Formato e rotazione delle clip", ""]
    L.append(table(["clip", "durata", "codec", "origine", "rotazione", "display", "fps", "bit", "audio", "flag"], [
        [Path(p["file"]).name, fmt_s(p["duration_s"]), f"{p['codec']} {p['profile'] or ''}".strip(),
         f"{p['width']}×{p['height']}", f"{p['rotation']}°" if p["rotation_tag"] else "assente",
         f"{p['display_width']}×{p['display_height']}", p["fps"], p["bit_depth"],
         f"{p['audio_codec']} {p['audio_sample_rate'] or ''}/{p['audio_bits'] or '?'}", ", ".join(p["flags"]) or "—"]
        for p in probe]))
    L.append("")

    # 2. Mezzanine
    L += ["## 2. Mezzanine 1440×2560 (VideoToolbox)", ""]
    if mezz:
        s = mezz["summary"]
        L.append(f"Encoder `{s['encoder']}`, {s['bitrate']}, decodifica hardware: {'sì' if s['hw_decode'] else 'no'}. "
                 f"Totale: {s['footage_s']} s di girato in {s['total_s']} s (**{s['speed_x']}× tempo reale**). "
                 f"Tutti 1440×2560 dritti: **{'sì' if s['all_ok'] else 'NO'}**.")
        L.append("")
        L.append(table(["clip", "durata", "codifica", "velocità", "uscita", "MB", "ok"], [
            [c["clip"], fmt_s(c["duration_s"]), fmt_s(c.get("encode_s")), f"{c.get('speed_x', '—')}×",
             c.get("out", c.get("skipped", "—")), c.get("out_mb", "—"), "sì" if c.get("out_ok") else "no"]
            for c in mezz["clips"]]))
    else:
        L.append("Non eseguito.")
    L.append("")

    # 3. Tempi di trascrizione
    L += ["## 3. Tempi di trascrizione (mlx-whisper, timestamp per parola)", ""]
    if trans:
        L.append(table(["variante", "audio clip", "trascrizione", "RTF", "caricamento modello", "memoria di picco",
                        f"proiezione {TYPICAL_AUDIO_S} s"], [
            [k, fmt_s(t["clips_audio_s"]), fmt_s(t["clips_transcribe_s"]), t["clips_rtf"], fmt_s(t["load_s"]),
             f"{t['peak_mem_gb']} GB" if t["peak_mem_gb"] else "—",
             fmt_s(t["clips_rtf"] * TYPICAL_AUDIO_S if t["clips_rtf"] else None)] for k, t in trans.items()]))
        L.append("")
        L.append("RTF = tempo di trascrizione / durata dell'audio (più basso è meglio). "
                 "Il caricamento include il download solo al primo giro.")
    else:
        L.append("Non eseguito.")
    L.append("")

    # 3 bis. VAD
    L += ["## 3 bis. Parlato: VAD e classificazione A-roll / b-roll (§6.1)", ""]
    if vad:
        broll = [k for k, c in vad["clips"].items() if c["kind"] == "broll"]
        rtf = (trans.get("turbo") or {}).get("clips_rtf")
        saved = f", circa {vad['broll_audio_s'] * rtf:.0f} s di trascrizione turbo risparmiati" if rtf else ""
        L.append(f"Silero VAD v5 (ONNX) su {len(vad['clips'])} clip in {vad['vad_total_s']} s. "
                 f"A-roll se il parlato supera {vad['params']['min_speech_s']} s: **{len(vad['aroll'])} A-roll, "
                 f"{len(broll)} b-roll** ({vad['broll_audio_s']} s di audio che Whisper può saltare{saved}).")
        L.append("")
        L.append(table(["clip", "tipo", "parlato", "durata"], [
            [k, "A-roll" if c["kind"] == "aroll" else "b-roll", fmt_s(c["speech_s"]), fmt_s(c["duration_s"])]
            for k, c in vad["clips"].items()]))
        L.append("")
        L.append("Testo tolto dalle varianti `+vad` (clip b-roll, parole fuori dal parlato, segmenti che Whisper "
                 "stesso giudica non parlato). Da controllare: dovrebbe essere solo testo inventato da Whisper.")
        L.append("")
        for v, info in vad["variants"].items():
            items = [f"`{clip}` {it}" for clip, its in info["removed"].items() for it in its]
            L.append(f"- **{v}** ({len(items)}): " + ("; ".join(items) if items else "nulla"))
    else:
        L.append("Non eseguito.")
    L.append("")

    # 4. Qualità
    L += ["## 4. Qualità rispetto ai sottotitoli del reel", ""]
    if compare:
        src = compare["reference"]
        L.append(f"Riferimento: `{src}` ({compare['ref_words']} parole"
                 + (f", OCR {subs['engine']} su {subs['frames']} fotogrammi" if subs else "") + "). "
                 + ("Corretto a mano sul reel." if src == "reference_manual.txt" else
                    "**OCR non ricontrollato a mano**: gli errori OCR finiscono nel WER di entrambi i modelli."))
        L.append("")
        L.append("Varianti: `+prompt` = glossario come prompt di Whisper (ricavato dagli errori del primo giro "
                 "su questo shooting: il guadagno va confermato su un altro); `+vad` = trascrizione filtrata dalla VAD.")
        L.append("")
        L.append("Normalizzazione: minuscole, senza punteggiatura né accenti, numeri in lettere → cifre, "
                 "unità (€, euro, m², metri…) e filler (ehm, eh) esclusi.")
        L.append("")
        rows = []
        for k, e in compare["variants"].items():
            r, c = e.get("reel"), e["clips"]
            rows.append([k, pct(r["wer"]) if r else "—", pct(c["wer"]),
                         f"{len(c['number_errors'])}/{c['numbers']}", f"{len(c['name_errors'])}/{c['names']}",
                         f"{len(r['number_errors'])}/{r['numbers']}" if r else "—",
                         f"{len(r['name_errors'])}/{r['names']}" if r else "—"])
        L.append(table(["variante", "WER A (reel)", "WER B (clip)", "numeri errati B", "nomi errati B",
                        "numeri errati A", "nomi errati A"], rows))
        L.append("")
        L.append("A = audio del reel finito (stesso parlato dei sottotitoli, con la musica sotto). "
                 "B = clip originali: il riferimento è allineato sulle clip concatenate, con salti tra clip "
                 "solo all'inizio di un gruppo di sottotitoli; le take scartate non contano. È il caso della "
                 "pipeline, un po' ottimista quando ci sono più take simili.")
        L.append("")
        L.append("### Errori sui token critici")
        L.append("")
        any_err = False
        for k, e in compare["variants"].items():
            errs = [("B", x) for x in e["clips"]["number_errors"] + e["clips"]["name_errors"]]
            if e.get("reel"):
                errs += [("A", x) for x in e["reel"]["number_errors"] + e["reel"]["name_errors"]]
            for m, x in errs:
                any_err = True
                L.append(f"- {k}, {m}: `{x['ref']}` → `{x['hyp'] or '∅'}` ({x['op']}{', ' + x['clip'] if 'clip' in x else ''})")
        if not any_err:
            L.append("Nessun errore sui token critici.")
        L.append("")
        L.append("### Differenze principali (misura A)")
        L.append("")
        for k, e in compare["variants"].items():
            if e.get("reel"):
                d = e["reel"]["diff"]
                L.append(f"- **{k}** ({len(d)}): " + ("; ".join(f"`{x}`" for x in d[:40]) or "nessuna")
                         + (" …" if len(d) > 40 else ""))
    else:
        L.append("Non eseguito.")
    L.append("")

    # 5. Take
    L += ["## 5. Take ripetute tra file diversi (§6.2)", ""]
    if takes:
        L.append(table(["variante", "frasi", "spezzate", "battute", "con più take", "take del reel da",
                        "euristica = reel", "coppie quasi simili"], [
            [k, t["phrases"], len(t.get("split", [])), len(t["battute"]), t["multi_take"], t.get("reel_source") or "—",
             f"{t['heuristic_agree']}/{t['heuristic_judged']}", len(t["near_misses"])] for k, t in takes.items()]))
        L.append("")
        L.append("Regole: similarità ≥ 0,7 (specifica); stesso attacco (prime 8 parole, ≤ 2 errori); take interrotta "
                 "agganciata senza fare da ponte. Le frasi lunghe dette d'un fiato vengono spezzate dove ci si allineano "
                 "le altre take. \"Euristica\" = ultima take completa, senza LLM; \"reel\" = take usata nel reel "
                 "(dalla mappa audio se c'è, altrimenti stimata dal testo).")
        L.append("")
        best_cfg = recommend(compare, decide(compare, trans)[0]) if compare and trans else None
        k0 = best_cfg if best_cfg in takes else next((k for k in ("turbo+vad", "turbo") if k in takes), next(iter(takes)))
        t = takes[k0]
        L.append(f"### Battute con le take candidate ({k0})")
        L.append("")
        for b in t["battute"]:
            if len(b["takes"]) < 2 and b["reel_pick"] is None:
                continue
            L.append(f"**Battuta {b['n']}** — {len(b['takes'])} take")
            for x in b["takes"]:
                tag = []
                if x["phrase"] == b["heuristic_pick"] and len(b["takes"]) > 1:
                    tag.append("euristica")
                if x["phrase"] == b["reel_pick"]:
                    tag.append("reel")
                if not x["complete"]:
                    tag.append("incompleta")
                L.append(f"- `{x['clip']}` {x['start']:.2f}–{x['end']:.2f} s {'(' + ', '.join(tag) + ')' if tag else ''}: «{x['text']}»")
            L.append("")
        L.append("Take mancate: il rilevamento automatico non le vede per definizione. Le coppie quasi simili "
                 "(0,5–0,7) sono in `results/takes-*.json` → `near_misses` e vanno confermate guardando le clip.")
    else:
        L.append("Non eseguito.")
    L.append("")

    # 5 bis. Mappa audio del reel
    L += ["## 5 bis. Da quali clip viene l'audio del reel", ""]
    if reel_map:
        L.append(f"Correlazione della forma d'onda (finestre di {reel_map['win_s']} s): {reel_map['covered_s']} s "
                 f"su {reel_map['reel_s']} s del reel ricondotti alle clip, in {len(reel_map['segments'])} segmenti. "
                 "Il resto è musica sola o audio non preso dalle clip.")
        L.append("")
        L.append(table(["reel", "clip", "nella clip", "NCC"], [
            [f"{s['reel_start']:.2f}–{s['reel_end']:.2f}", s["clip"], f"{s['clip_start']:.2f}–{s['clip_end']:.2f}",
             f"{s['ncc_mean']:.2f}"] for s in reel_map["segments"]]))
    else:
        L.append("Non eseguito.")
    L.append("")

    # 6. Decisione
    L += ["## 6. Decisione: turbo o large-v3", ""]
    if compare and trans:
        choice, why = decide(compare, trans)
        L.append(f"**Scelta: {choice}.**")
        L.append("")
        L += [f"- {w}" for w in why]
        best = recommend(compare, choice)
        if best:
            L.append("")
            L.append(f"Configurazione con meno errori per {choice}: **`{best}`** "
                     "(prima i token critici sulle clip, poi il WER sulle clip).")
    else:
        L.append("Non decidibile: mancano trascrizioni o confronto.")
    L.append("")

    # 7. Limiti
    n = len(probe)
    L += ["## 7. Limiti della misura", "",
          f"- {n} clip in questo shooting: campione piccolo, in particolare per le take ripetute.",
          "- I sottotitoli del reel possono differire dal parlato per scelta editoriale (tagli, parafrasi): "
          "contano come errori di entrambi i modelli.",
          "- Whisper non separa i parlanti: la seconda voce fuori campo (§6.3) è trascritta insieme all'agente.",
          "- Spike da ripetere su `11.18 - LISSONE` (§14).", ""]

    # la parte scritta a mano (dopo il marcatore) sopravvive alle rigenerazioni
    manual = ""
    if args.out.exists() and MANUAL_MARK in args.out.read_text():
        manual = args.out.read_text().split(MANUAL_MARK, 1)[1]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L) + ("\n" + MANUAL_MARK + manual if manual else ""))
    print(f"Scritto {args.out}")


if __name__ == "__main__":
    main()
