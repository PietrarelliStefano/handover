"""Testo italiano: normalizzazione, numeri in lettere → cifre, allineamento a livello di parola (§6.2, §6.5)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --- Numeri in lettere -------------------------------------------------------

_UNITS = {
    "zero": 0, "uno": 1, "un": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12,
    "tredici": 13, "quattordici": 14, "quindici": 15, "sedici": 16, "diciassette": 17,
    "diciotto": 18, "diciannove": 19,
}
_TENS = {
    "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, "sessanta": 60,
    "settanta": 70, "ottanta": 80, "novanta": 90,
}


def _lt100(s: str) -> int | None:
    if s in _UNITS:
        return _UNITS[s]
    for word, val in _TENS.items():
        if s == word:
            return val
        # "ventitre", "trentadue"; con uno/otto la vocale cade: "ventuno", "trentotto"
        if s.startswith(word) and s[len(word):] in ("due", "tre", "quattro", "cinque", "sei", "sette", "nove"):
            return val + _UNITS[s[len(word):]]
        if s.startswith(word[:-1]) and s[len(word) - 1:] in ("uno", "otto"):
            return val + _UNITS[s[len(word) - 1:]]
    return None


def _lt1000(s: str) -> int | None:
    if s == "":
        return 0
    idx = s.find("cent")
    if idx == -1:
        return _lt100(s)
    head, tail = s[:idx], s[idx + 4:]
    mult = 1 if head == "" else _lt100(head)
    if mult is None or mult >= 10 or (head and mult < 2):
        return None
    # "cento", "centoventi", "centottanta" (o elisa davanti a ottanta/otto)
    candidates = []
    if tail.startswith("o"):
        candidates.append(tail[1:])
    if tail.startswith("ott"):
        candidates.append(tail)
    for rest in candidates:
        if rest == "":
            return mult * 100
        r = _lt100(rest)
        if r is not None:
            return mult * 100 + r
    return None


# Parole che da sole sono quasi sempre articoli o verbi ("sei un agente?"): non convertite.
AMBIGUOUS = {"un", "una", "uno", "sei"}


def parse_it_number(word: str) -> int | None:
    """'duecentocinquantamila' → 250000; None se non è un numero in lettere."""
    s = strip_accents(word.lower())
    if not s or not s.isalpha() or s in AMBIGUOUS:
        return None
    for sep, mul in (("milioni", 10**6), ("milione", 10**6)):
        if sep in s:
            head, tail = s.split(sep, 1)
            h = 1 if head in ("", "un") else _below_million(head)
            t = _below_million(tail) if tail else 0
            if h is None or t is None:
                return None
            return h * mul + t
    return _below_million(s)


def _below_million(s: str) -> int | None:
    if s.startswith("mille"):
        rest = s[5:]
        r = _lt1000(rest) if rest else 0
        return None if r is None else 1000 + r
    if "mila" in s:
        head, tail = s.split("mila", 1)
        h = _lt1000(head)
        t = _lt1000(tail) if tail else 0
        if h is None or t is None or h < 2:
            return None
        return h * 1000 + t
    return _lt1000(s)


# --- Normalizzazione ---------------------------------------------------------

FILLERS = {"ehm", "eh", "uhm", "mmm", "mm", "ehh", "ah"}
# Unità rimosse dal confronto: nei sottotitoli e in Whisper compaiono in forme e posizioni
# diverse ("€188.000" / "188.000 euro", "30M" / "30 metri quadri"). Il numero resta.
UNITS = {"euro", "eur", "mq", "m2", "m", "metri", "metro", "quadri", "quadrati", "quadro"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _digits(tok: str) -> str:
    """'188.000' → '188000', '3,5' → '3.5', '188mila' → '188000'."""
    m = re.fullmatch(r"(\d+)mila", tok)
    if m:
        return str(int(m.group(1)) * 1000)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", tok):
        return tok.replace(".", "")
    if re.fullmatch(r"\d+,\d+", tok):
        return tok.replace(",", ".")
    return tok


def normalize_tokens(text: str, *, drop_fillers: bool = True, drop_units: bool = True) -> list[str]:
    s = text.lower().replace("²", "2").replace("€", " euro ")
    s = re.sub(r"[’'`´]", " ", s)
    s = strip_accents(s)
    # separa cifre da lettere attaccate ("30m" → "30 m"), tranne "188mila"
    s = re.sub(r"(\d)(?!mila)([a-z])", r"\1 \2", s)
    out: list[str] = []
    for raw in s.split():
        tok = raw.strip(".,;:!?\"«»()[]-–—…")
        if not tok:
            continue
        tok = _digits(tok)
        tok = re.sub(r"[^\w.]", "", tok).strip(".")
        if not tok:
            continue
        n = parse_it_number(tok)
        if n is not None:
            tok = str(n)
        if drop_fillers and tok in FILLERS:
            continue
        if drop_units and tok in UNITS:
            continue
        out.append(tok)
    return _merge_numbers(out)


def _merge_numbers(toks: list[str]) -> list[str]:
    """Fonde numeri scritti separati: '200 50 mila' non serve; ma '250 000' (cifre spezzate) sì."""
    out: list[str] = []
    for t in toks:
        if out and t == "000" and out[-1].isdigit():
            out[-1] = out[-1] + "000"
        elif out and t == "mila" and out[-1].isdigit():
            out[-1] = str(int(out[-1]) * 1000)
        else:
            out.append(t)
    return out


def is_number(tok: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)?", tok))


# --- Allineamento e WER ------------------------------------------------------

@dataclass
class Alignment:
    ops: list[tuple[str, str | None, str | None]]  # (op, ref, hyp): ok | sub | del | ins
    hyp_start: int
    hyp_end: int

    @property
    def errors(self) -> int:
        return sum(1 for op, _, _ in self.ops if op != "ok")

    @property
    def subs(self) -> int:
        return sum(1 for op, *_ in self.ops if op == "sub")

    @property
    def dels(self) -> int:
        return sum(1 for op, *_ in self.ops if op == "del")

    @property
    def ins(self) -> int:
        return sum(1 for op, *_ in self.ops if op == "ins")

    @property
    def n_ref(self) -> int:
        return sum(1 for op, *_ in self.ops if op != "ins")


def align(ref: list[str], hyp: list[str], *, fit: bool = False) -> Alignment:
    """Edit distance a livello di parola con backtrack.

    fit=True: allineamento "fitting": ref deve essere coperto tutto, hyp può iniziare e finire
    ovunque senza costo (trova la porzione di hyp che meglio corrisponde a ref).
    """
    n, m = len(ref), len(hyp)
    INF = 10**9
    d = [[INF] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        d[0][j] = 0 if fit else j
    for i in range(1, n + 1):
        d[i][0] = i
        for j in range(1, m + 1):
            c = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j - 1] + c, d[i - 1][j] + 1, d[i][j - 1] + 1)
    j_end = min(range(m + 1), key=lambda j: (d[n][j], -j)) if fit else m
    i, j = n, j_end
    ops: list[tuple[str, str | None, str | None]] = []
    while i > 0 or (j > 0 and not fit):
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], None))
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1]))
            j -= 1
    ops.reverse()
    return Alignment(ops=ops, hyp_start=j, hyp_end=j_end)


def wer(ref: list[str], hyp: list[str]) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    return align(ref, hyp).errors / len(ref)


def number_errors(al: Alignment) -> list[dict]:
    """Token numerici del riferimento non riprodotti esattamente nell'ipotesi."""
    errs = []
    for op, r, h in al.ops:
        if r is not None and is_number(r) and op != "ok":
            errs.append({"ref": r, "hyp": h, "op": op})
    return errs


@dataclass
class JumpAlignment(Alignment):
    hyp_pos: list[int | None] | None = None  # indice in hyp per ogni op (None per le cancellazioni)


def align_jump(ref: list[str], hyp: list[str], boundaries: set[int], jump_cost: float = 1.0,
               barrier: str | None = None) -> JumpAlignment:
    """Allinea ref (il parlato del reel) su hyp (le clip concatenate) permettendo, solo alle posizioni
    di ref in `boundaries` (inizio di un gruppo di sottotitoli, dove cadono i tagli del montaggio),
    di saltare in qualunque punto di hyp con costo `jump_cost`. Inizio e fine in hyp liberi.
    Le parti di hyp non usate (take scartate) non costano nulla. Il token `barrier` (separatore tra
    clip) non si attraversa né si sostituisce: per passare a un'altra clip serve un salto.
    """
    BAR = 1000.0
    hcost = [BAR if t == barrier else 1.0 for t in hyp]
    n, m = len(ref), len(hyp)
    INF = float("inf")
    d = [[INF] * (m + 1) for _ in range(n + 1)]
    bp = [[0] * (m + 1) for _ in range(n + 1)]  # 0 diag, 1 del, 2 ins, 3 salto
    jump_from = [0] * (n + 1)
    d[0] = [0.0] * (m + 1)
    for i in range(n + 1):
        row = d[i]
        if i > 0:
            prev = d[i - 1]
            r = ref[i - 1]
            for j in range(m + 1):
                best, move = prev[j] + 1, 1
                if j > 0:
                    c = prev[j - 1] + (0 if r == hyp[j - 1] else hcost[j - 1])
                    if c <= best:
                        best, move = c, 0
                    if row[j - 1] + hcost[j - 1] < best:
                        best, move = row[j - 1] + hcost[j - 1], 2
                row[j], bp[i][j] = best, move
        if 0 < i < n and i in boundaries:
            # a parità di costo si salta da una cella raggiunta per corrispondenza (sub/ok, non del)
            k = min(range(m + 1), key=lambda x: (row[x], bp[i][x] != 0, -x))
            jump_from[i] = k
            jv = row[k] + jump_cost
            for j in range(m + 1):
                if jv < row[j]:
                    row[j], bp[i][j] = jv, 3
    j = min(range(m + 1), key=lambda x: (d[n][x], -x))
    j_end, i = j, n
    ops: list[tuple[str, str | None, str | None]] = []
    pos: list[int | None] = []
    while i > 0:
        mv = bp[i][j]
        if mv == 3:
            j = jump_from[i]
            continue
        if mv == 0:
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            pos.append(j - 1)
            i, j = i - 1, j - 1
        elif mv == 1:
            ops.append(("del", ref[i - 1], None))
            pos.append(None)
            i -= 1
        else:
            ops.append(("ins", None, hyp[j - 1]))
            pos.append(j - 1)
            j -= 1
    ops.reverse()
    pos.reverse()
    return JumpAlignment(ops=ops, hyp_start=j, hyp_end=j_end, hyp_pos=pos)


def normalize_words(words: list[str]) -> list[tuple[str, int]]:
    """Come normalize_tokens, ma per parola: ogni token porta l'indice della parola di origine
    (serve a spezzare una frase mantenendo i timestamp). '188 mila' → ('188000', i)."""
    out: list[tuple[str, int]] = []
    for i, w in enumerate(words):
        for t in normalize_tokens(w):
            if out and out[-1][0].isdigit() and t in ("mila", "000"):
                out[-1] = (str(int(out[-1][0]) * 1000), out[-1][1])
            else:
                out.append((t, i))
    return out
