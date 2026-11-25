import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spikes"))

import pytest  # noqa: E402
from textnorm import align, normalize_tokens, number_errors, parse_it_number, wer  # noqa: E402


@pytest.mark.parametrize("word,n", [
    ("centoventi", 120), ("duecentocinquantamila", 250000), ("centottantottomila", 188000),
    ("ventuno", 21), ("trentotto", 38), ("ventitré", 23), ("mille", 1000), ("tremila", 3000),
    ("duemilacinquecento", 2500), ("cento", 100), ("trecento", 300), ("un milione", None),
    ("unmilione", 1000000), ("tre", 3),
])
def test_parse_it_number(word, n):
    assert parse_it_number(word) == n


@pytest.mark.parametrize("word", ["sei", "un", "una", "centrale", "milano", "venti9", "casa", "ottimo"])
def test_not_numbers(word):
    assert parse_it_number(word) is None


def test_normalize_subtitle_vs_whisper():
    sub = normalize_tokens("A SOLI €188.000, 3 LOCALI DA 90M")
    asr = normalize_tokens("A soli centottantottomila euro, tre locali da novanta metri quadri.")
    assert sub == asr == ["a", "soli", "188000", "3", "locali", "da", "90"]


def test_normalize_fillers_and_apostrophes():
    assert normalize_tokens("Ehm, l'appartamento è qui") == ["l", "appartamento", "e", "qui"]


def test_wer_and_fit():
    assert wer(["a", "b", "c"], ["a", "x", "c"]) == pytest.approx(1 / 3)
    al = align(["tre", "locali"], "qui ci sono tre locali luminosi".split(), fit=True)
    assert al.errors == 0 and (al.hyp_start, al.hyp_end) == (3, 5)


def test_number_errors():
    al = align(["prezzo", "188000"], ["prezzo", "180000"])
    assert number_errors(al) == [{"ref": "188000", "hyp": "180000", "op": "sub"}]


def test_align_jump_across_clips_and_takes():
    from textnorm import align_jump
    sep = "<|clip|>"
    hyp = ("sei un agente " + sep + " questo trilocale costa " + sep +
           " questo trilocale costa 180000 " + sep + " ha 3 locali").split()
    ref = "questo trilocale costa 188000 sei un agente ha 3 locali".split()
    al = align_jump(ref, hyp, {4, 7}, barrier=sep)
    assert al.errors == 1 and [o for o in al.ops if o[0] != "ok"] == [("sub", "188000", "180000")]
