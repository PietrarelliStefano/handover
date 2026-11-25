from handover.video.subtitles import Glossary, subtitle_words


def W(text: str, t0: float = 0.0, step: float = 0.3):
    return [{"w": w, "start": round(t0 + i * step, 2), "end": round(t0 + i * step + 0.25, 2)}
            for i, w in enumerate(text.split())]


G = Glossary.load("venezia")


def texts(ws):
    return [w["t"] for w in ws]


def test_price_whisper_variants():
    for src in ("mi chiederai il prezzo, 188 mila euro,", "il prezzo centottantottomila euro.", "il prezzo 188 .000 euro"):
        ws = subtitle_words(W(src), G)
        price = next(w for w in ws if w["t"].startswith("€"))
        assert price["t"] == "€188.000" and price["critical"] and price["reason"] == "numero"


def test_sqm_and_counts():
    ws = subtitle_words(W("tre locali da novanta metri quadri."), G)
    assert texts(ws) == ["3", "locali", "da", "90 m²"]
    assert all(w["critical"] for w in ws if w["t"][0].isdigit())


def test_glossary_correction_is_critical():
    ws = subtitle_words(W("un appartamento in merita a Bernareggio con WMC"), G)
    assert texts(ws) == ["un", "appartamento", "in", "vendita", "a", "Bernareggio", "con", "VMC"]
    assert {w["t"]: w.get("reason") for w in ws if w["critical"]} == {
        "in": "glossario", "vendita": "glossario", "Bernareggio": "nome", "VMC": "glossario"}


def test_fragments_fillers_and_punctuation():
    words = [{"w": "Ehm,", "start": 0.0, "end": 0.3}, {"w": "L", "start": 0.4, "end": 0.5},
             {"w": "'appartamento", "start": 0.5, "end": 1.0}, {"w": "è", "start": 1.0, "end": 1.1},
             {"w": "concluso.", "start": 1.1, "end": 1.6}]
    ws = subtitle_words(words, G)
    assert texts(ws) == ["L'appartamento", "è", "concluso"]
    assert ws[0]["start_ms"] == 400 and ws[0]["end_ms"] == 1000


def test_sei_is_not_a_number_and_names_are_critical():
    ws = subtitle_words(W("Sei un agente immobiliare? Io sono Simone Venezia."), G)
    assert texts(ws)[0] == "Sei" and not ws[0]["critical"]
    assert [w["t"] for w in ws if w["critical"]] == ["Simone", "Venezia"]
