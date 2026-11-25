"""Scelta delle take e ordine delle battute (§6.2.4, §6.3, rev. 7).

LLM tramite `claude -p` (Claude Code, la stessa via di M5): riceve solo il testo delle trascrizioni,
mai file video o audio (CLAUDE.md). Se Claude Code non c'è o risponde male, si usa una regola
locale con confidenza bassa: tutto finisce in review.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import defaultdict
from typing import Callable

from handover.video.text import align, normalize_tokens
from handover.video.takes import clip_number, similarity

CONFIDENCE_REVIEW = 0.7
REPEAT_COVER = 0.6  # oltre il 60% delle parole già detto altrove = contenuto ripetuto
ROLES = ("aggancio", "corpo", "chiusura")
CTA_RE = re.compile(r"\b(contattami|chiamami|scrivimi|io sono|ci penso io)\b", re.I)

PROMPT = """Sei l'assistente al montaggio di un reel immobiliare verticale (Instagram, TikTok) di 45–80 secondi.
L'agente immobiliare ha girato più clip; in molte ha ripetuto la stessa battuta più volte (take).
Ti do le battute già raggruppate: per ognuna, le take candidate con clip, durata e testo trascritto.
Il testo viene da Whisper e può contenere errori di trascrizione: non correggerlo, giudica la resa.

Compito:
1. Scegli quali battute entrano nel reel e in che ordine, seguendo il template:
   - "aggancio" (0–5 s): battuta d'apertura, spesso un mini-dialogo ("Sei un agente immobiliare?" / "Sì, posso esserti utile");
   - "corpo": la visita dell'immobile, nell'ordine in cui la si percorre;
   - "chiusura": prezzo se c'è, poi la call to action ("contattami, io sono …").
   Escludi battute fuori tema, frammenti, prove, indicazioni di regia ("vai", "ok, rifacciamo").
2. Per ogni battuta scelta, scegli UNA take. Criteri, in quest'ordine:
   a. preferisci una take continua che copre più battute di fila nella stessa clip (meno tagli nel montaggio);
   b. take completa, senza esitazioni, ripetizioni o frasi interrotte;
   c. a parità, l'ultima girata (numero di clip più alto).
3. Nessuna frase deve comparire due volte nel reel.
4. Dai una confidenza da 0 a 1 per ogni scelta: sotto 0,7 la scelta verrà controllata a mano.

Rispondi SOLO con un oggetto JSON, senza testo prima o dopo, in questa forma:
{{"order": [{{"battuta": "b3", "take": "t12", "role": "aggancio", "confidence": 0.9, "reason": "breve motivo"}}],
 "excluded": [{{"battuta": "b7", "reason": "breve motivo"}}]}}

Clip e battute che contengono, nell'ordine di ripresa:
{clips}

Battute:
{battute}
"""


def _fmt(battute: list[dict]) -> tuple[str, str]:
    by_clip: dict[str, list[str]] = defaultdict(list)
    lines = []
    for b in battute:
        lines.append(f"\n[{b['id']}]")
        for t in b["takes"]:
            by_clip[t["clip"]].append(b["id"])
            flag = "" if t["complete"] else " (incompleta)"
            lines.append(f"  {t['take']} · {t['clip']} {t['start']:.1f}–{t['end']:.1f} s"
                         f" ({t['end'] - t['start']:.1f} s){flag}: «{t['text']}»")
    clips = "\n".join(f"  {c}: {' '.join(dict.fromkeys(ids))}" for c, ids in sorted(by_clip.items(), key=lambda x: clip_number(x[0])))
    return clips, "\n".join(lines)


def build_prompt(battute: list[dict]) -> str:
    clips, text = _fmt(battute)
    return PROMPT.format(clips=clips, battute=text)


def parse_response(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("nessun JSON nella risposta")
    return json.loads(m.group(0))


def validate(sel: dict, battute: list[dict]) -> list[str]:
    """Problemi della scelta; lista vuota se valida."""
    takes = {b["id"]: {t["take"]: t for t in b["takes"]} for b in battute}
    errs, seen = [], set()
    chosen_toks: list[tuple[str, list[str]]] = []
    for item in sel.get("order", []):
        b, t = item.get("battuta"), item.get("take")
        if b not in takes:
            errs.append(f"battuta inesistente {b}")
            continue
        if t not in takes[b]:
            errs.append(f"take {t} non appartiene a {b}")
            continue
        if b in seen:
            errs.append(f"battuta {b} usata due volte")
        seen.add(b)
        if item.get("role") not in ROLES:
            errs.append(f"ruolo non valido per {b}: {item.get('role')}")
        toks = normalize_tokens(takes[b][t]["text"])
        for other, otoks in chosen_toks:
            if len(toks) >= 3 and (similarity(toks, otoks) >= 0.7 or _covered(toks, [otoks]) >= REPEAT_COVER
                                   or _covered(otoks, [toks]) >= REPEAT_COVER):
                errs.append(f"frase ripetuta: {b} e {other}")
        chosen_toks.append((b, toks))
    if not sel.get("order"):
        errs.append("nessuna battuta scelta")
    return errs


def run_claude(prompt: str, model: str | None = None, timeout: int = 300) -> str:
    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError("Claude Code (`claude`) non trovato nel PATH")
    cmd = [exe, "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"claude -p fallito: {res.stderr[-1000:]}")
    out = json.loads(res.stdout)
    return out.get("result", "") if isinstance(out, dict) else str(out)


CUE_RE = re.compile(r"\b(basta|stop|rifacciamo|rifaccio|taglia|ok|okay|vai|azione)\b[.!?,]*\s*$", re.I)


def _good(t: dict) -> bool:
    """Take utilizzabile: almeno 4 parole, completa oppure abbastanza lunga (Whisper a volte non mette
    il punto finale nelle take dette d'un fiato), e senza indicazione di regia in coda ("…, basta.")."""
    return t["n_words"] >= 4 and (t["complete"] or t["n_words"] >= 8) and not CUE_RE.search(t["text"])


def _covered(toks: list[str], others: list[list[str]]) -> float:
    """Quota delle parole di `toks` che si ritrovano, in ordine, in una delle altre frasi."""
    if not toks:
        return 0.0
    best = 0
    for o in others:
        al = align(toks, o, fit=True)
        best = max(best, sum(1 for op, *_ in al.ops if op == "ok"))
    return best / len(toks)


def heuristic_selection(battute: list[dict]) -> dict:
    """Senza LLM, confidenza 0,5 (tutto in review):
    - battute con almeno una take utilizzabile (vedi _good), in ordine di ripresa;
    - take scelta con il criterio "take continua", poi la più lunga, poi l'ultima;
    - aggancio: take che contiene una domanda, più le battute che la seguono senza stacco nella stessa clip;
    - chiusura: call to action; il resto è corpo;
    - battute il cui contenuto è già quasi tutto in altre battute scelte vengono tolte (niente ripetizioni)."""
    usable = [b for b in battute if any(_good(t) for t in b["takes"])]
    clip_battute: dict[str, set[str]] = defaultdict(set)
    for b in usable:
        for t in b["takes"]:
            if _good(t):
                clip_battute[t["clip"]].add(b["id"])

    def pick(b: dict) -> dict:
        cands = [t for t in b["takes"] if _good(t)]
        longest = max(t["n_words"] for t in cands)
        cands = [t for t in cands if t["n_words"] >= 0.8 * longest]
        return max(cands, key=lambda t: (len(clip_battute[t["clip"]]), clip_number(t["clip"]), t["start"]))

    chosen = [(b, pick(b)) for b in usable]
    excluded = [{"battuta": b["id"], "reason": "nessuna take utilizzabile"} for b in battute if b not in usable]

    # niente contenuti ripetuti: si tolgono, dalla più corta, le battute già coperte dalle altre
    toks = {b["id"]: normalize_tokens(t["text"]) for b, t in chosen}
    for b, t in sorted(chosen, key=lambda bt: len(toks[bt[0]["id"]])):
        others = [toks[o["id"]] for o, _ in chosen if o is not b]
        if len(toks[b["id"]]) >= 3 and _covered(toks[b["id"]], others) >= REPEAT_COVER:
            chosen = [(o, ot) for o, ot in chosen if o is not b]
            excluded.append({"battuta": b["id"], "reason": "contenuto già presente in un'altra battuta"})

    roles: dict[str, str] = {}
    hook_end: dict[str, float] = {}
    for b, t in sorted(chosen, key=lambda bt: (clip_number(bt[1]["clip"]), bt[1]["start"])):
        if CTA_RE.search(t["text"]):
            roles[b["id"]] = "chiusura"
        elif "?" in t["text"] or (t["clip"] in hook_end and 0 <= t["start"] - hook_end[t["clip"]] <= 1.5):
            roles[b["id"]] = "aggancio"
            hook_end[t["clip"]] = t["end"]
        else:
            roles[b["id"]] = "corpo"

    items = [{"battuta": b["id"], "take": t["take"], "role": roles[b["id"]], "confidence": 0.5,
              "reason": "regola locale (LLM non disponibile)"} for b, t in chosen]
    rank = {"aggancio": 0, "corpo": 1, "chiusura": 2}
    items.sort(key=lambda it: rank[it["role"]])  # sort stabile: dentro il ruolo resta l'ordine di ripresa
    return {"order": items, "excluded": excluded}


def select(battute: list[dict], llm: Callable[[str], str] | None = run_claude) -> dict:
    """Scelta con LLM e validazione; in caso di problemi, regola locale. Il risultato è l'artefatto
    selection.json: contiene anche prompt, risposta grezza ed eventuali errori, per la review."""
    prompt = build_prompt(battute)
    info: dict = {"source": "euristica", "prompt": prompt}
    if llm is not None:
        try:
            raw = llm(prompt)
            info["raw_response"] = raw
            sel = parse_response(raw)
            errs = validate(sel, battute)
            if not errs:
                return info | {"source": "llm"} | sel | {"flags": review_flags(sel)}
            info["llm_errors"] = errs
        except Exception as e:  # noqa: BLE001 - qualsiasi errore dell'LLM porta alla regola locale
            info["llm_errors"] = [f"{type(e).__name__}: {e}"]
    sel = heuristic_selection(battute)
    return info | sel | {"flags": review_flags(sel)}


def review_flags(sel: dict) -> list[dict]:
    return [{"battuta": it["battuta"], "flag": "take_da_confermare", "confidence": it.get("confidence")}
            for it in sel["order"] if (it.get("confidence") or 0) < CONFIDENCE_REVIEW]
