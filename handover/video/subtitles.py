"""Parole dei sottotitoli: correzione da glossario, numeri in cifre, filler, token critici (§6.2.5–6, §6.5).

Ingresso: parole di Whisper ({w, start, end} in secondi, relative alla clip).
Uscita: parole da mostrare ({t, start, end, critical, reason?}); il maiuscolo è compito del render.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources

from handover.video.text import FILLERS, parse_it_number, strip_accents

TRAIL_PUNCT = ".,;:…"
EURO = {"euro", "eur", "€"}
SQM_SINGLE = {"mq", "m²", "m2", "metriquadri"}
ADDRESS = {"via", "viale", "piazza", "corso", "largo", "vicolo"}


@dataclass
class Glossary:
    agente: str = ""
    agenzia: str = ""
    template: str = "venezia-v1"
    nomi: list[str] = field(default_factory=list)
    correzioni: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, name: str = "venezia") -> "Glossary":
        data = json.loads(resources.files("handover.data.agents").joinpath(f"{name}.json").read_text())
        return cls(**{k: data[k] for k in ("agente", "agenzia", "template", "nomi", "correzioni") if k in data})

    def name_patterns(self) -> list[list[str]]:
        """Nomi come sequenze di parole, i più lunghi prima: 'Immobiliare Venezia' vale solo intero."""
        return sorted(([_key(t) for t in n.split()] for n in self.nomi), key=len, reverse=True)


def _key(w: str) -> str:
    return strip_accents(w.lower()).strip(TRAIL_PUNCT + "?!\"'«»()")


def _merge(a: dict, b: dict, text: str) -> dict:
    out = dict(a, w=text, end=b["end"])
    if b.get("critical"):
        out["critical"], out["reason"] = True, b.get("reason")
    return out


def join_fragments(words: list[dict]) -> list[dict]:
    """'L' + "'appartamento" → "L'appartamento"; '188' + '.000' → '188.000'."""
    out: list[dict] = []
    for w in words:
        t = w["w"].strip()
        if not t:
            continue
        if out and (t[0] in "'’" or (re.fullmatch(r"\.\d{3}\W*", t) and re.search(r"\d$", out[-1]["w"]))):
            out[-1] = _merge(out[-1], w, out[-1]["w"] + t)
            continue
        out.append(dict(w, w=t))
    return out


def apply_glossary(words: list[dict], g: Glossary) -> list[dict]:
    """Sostituzioni del glossario (anche su più parole). Le parole corrette diventano token critici."""
    rules = [([_key(x) for x in c["da"].split()], c["a"]) for c in g.correzioni]
    rules.sort(key=lambda r: -len(r[0]))
    out, i = [], 0
    while i < len(words):
        for src, dst in rules:
            n = len(src)
            if [_key(w["w"]) for w in words[i:i + n]] == src:
                trail = words[i + n - 1]["w"][len(words[i + n - 1]["w"].rstrip(TRAIL_PUNCT + "?!")):]
                parts = (dst + trail).split()
                a, b = words[i]["start"], words[i + n - 1]["end"]
                step = (b - a) / len(parts)
                for k, p in enumerate(parts):
                    out.append({"w": p, "start": a + k * step, "end": a + (k + 1) * step,
                                "critical": True, "reason": "glossario"})
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def _num(t: str) -> int | float | None:
    s = t.strip(TRAIL_PUNCT)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return int(s.replace(".", ""))
    if re.fullmatch(r"\d+", s):
        return int(s)
    if re.fullmatch(r"\d+,\d+", s):
        return float(s.replace(",", "."))
    m = re.fullmatch(r"(\d+)mila", s.lower())
    if m:
        return int(m.group(1)) * 1000
    return parse_it_number(s)


def _fmt_int(n: int | float) -> str:
    if isinstance(n, float):
        return f"{n:.1f}".replace(".", ",")
    return f"{n:,}".replace(",", ".")


def format_numbers(words: list[dict]) -> list[dict]:
    """'centottantottomila euro' / '188 mila euro' → '€188.000'; 'novanta metri quadri' → '90 m²';
    'tre locali' → '3 locali'. Ogni numero diventa token critico (§6.5)."""
    out: list[dict] = []
    i = 0
    while i < len(words):
        w = words[i]
        n = _num(w["w"])
        if n is None:
            out.append(w)
            i += 1
            continue
        j = i + 1
        keys = [_key(x["w"]) for x in words]
        if j < len(words) and keys[j] == "mila":
            n, j = n * 1000, j + 1
        text = _fmt_int(n)
        if j < len(words) and keys[j] in EURO:
            text, j = f"€{text}", j + 1
        elif j + 1 < len(words) and keys[j] in ("metri", "metro") and keys[j + 1] in ("quadri", "quadrati"):
            text, j = f"{text} m²", j + 2
        elif j < len(words) and keys[j] in SQM_SINGLE:
            text, j = f"{text} m²", j + 1
        last = words[j - 1]
        trail = last["w"][len(last["w"].rstrip(TRAIL_PUNCT + "?!")):]
        out.append({"w": text + trail, "start": w["start"], "end": last["end"], "critical": True, "reason": "numero"})
        i = j
    return out


def drop_fillers(words: list[dict]) -> list[dict]:
    return [w for w in words if _key(w["w"]) not in FILLERS]


def mark_critical(words: list[dict], g: Glossary) -> list[dict]:
    out = [dict(w) for w in words]
    keys = [_key(w["w"]) for w in out]
    for pat in g.name_patterns():
        n = len(pat)
        for k in range(len(out) - n + 1):
            if keys[k:k + n] == pat and not any(w.get("critical") for w in out[k:k + n]):
                for w in out[k:k + n]:
                    w["critical"], w["reason"] = True, "nome"
    for k in range(1, len(out)):
        if not out[k].get("critical") and keys[k - 1] in ADDRESS and out[k]["w"][:1].isupper():
            out[k]["critical"], out[k]["reason"] = True, "indirizzo"
    return out


def subtitle_words(words: list[dict], g: Glossary) -> list[dict]:
    """Pipeline completa; uscita con tempi in ms e testo senza punteggiatura finale (tranne ? e !)."""
    ws = mark_critical(format_numbers(drop_fillers(apply_glossary(join_fragments(words), g))), g)
    out = []
    for w in ws:
        t = w["w"].rstrip(TRAIL_PUNCT).strip()
        if not t:
            continue
        item = {"t": t, "start_ms": round(w["start"] * 1000), "end_ms": round(w["end"] * 1000),
                "critical": bool(w.get("critical"))}
        if w.get("reason"):
            item["reason"] = w["reason"]
        out.append(item)
    return out
