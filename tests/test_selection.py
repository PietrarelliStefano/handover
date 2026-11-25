import json

from handover.video.selection import build_prompt, heuristic_selection, select, validate

from test_takes import battute as bernareggio


def mini():
    def t(tid, clip, text, complete=True):
        return {"take": tid, "clip": clip, "start": 0.0, "end": 2.0, "text": text, "complete": complete,
                "n_words": len(text.split()), "words": []}
    return [
        {"id": "b1", "takes": [t("t1", "Z50_1", "Ehi scusa ma tu sei un agente immobiliare?"),
                               t("t2", "Z50_2", "Ehi scusa ma tu sei un agente immobiliare?")]},
        {"id": "b2", "takes": [t("t3", "Z50_1", "Il disimpegno ci conduce nella zona notte.")]},
        {"id": "b3", "takes": [t("t4", "Z50_2", "Contattami, io sono Simone Venezia.")]},
    ]


def test_prompt_contains_only_text_and_takes():
    p = build_prompt(mini())
    assert "[b1]" in p and "t2 · Z50_2" in p and "take continua" in p
    assert ".MOV" not in p and "/Volumes" not in p


def test_valid_llm_answer_is_used():
    answer = {"order": [{"battuta": "b1", "take": "t2", "role": "aggancio", "confidence": 0.9, "reason": "x"},
                        {"battuta": "b2", "take": "t3", "role": "corpo", "confidence": 0.6, "reason": "y"},
                        {"battuta": "b3", "take": "t4", "role": "chiusura", "confidence": 0.95, "reason": "z"}],
              "excluded": []}
    sel = select(mini(), llm=lambda prompt: "Ecco:\n" + json.dumps(answer))
    assert sel["source"] == "llm" and [i["take"] for i in sel["order"]] == ["t2", "t3", "t4"]
    assert sel["flags"] == [{"battuta": "b2", "flag": "take_da_confermare", "confidence": 0.6}]


def test_invalid_llm_answer_falls_back():
    bad = {"order": [{"battuta": "b1", "take": "t3", "role": "aggancio", "confidence": 0.9}]}  # t3 non è di b1
    sel = select(mini(), llm=lambda prompt: json.dumps(bad))
    assert sel["source"] == "euristica" and "take t3 non appartiene a b1" in sel["llm_errors"]
    assert all(f["flag"] == "take_da_confermare" for f in sel["flags"])


def test_llm_unavailable_falls_back():
    def boom(prompt):
        raise FileNotFoundError("claude non trovato")
    sel = select(mini(), llm=boom)
    assert sel["source"] == "euristica"
    assert [i["role"] for i in sel["order"]] == ["aggancio", "corpo", "chiusura"]


def test_validate_rejects_repeated_phrase():
    bs = mini()
    bs.append({"id": "b4", "takes": [dict(bs[0]["takes"][0], take="t9")]})
    sel = {"order": [{"battuta": "b1", "take": "t1", "role": "aggancio"},
                     {"battuta": "b4", "take": "t9", "role": "corpo"}]}
    assert any("frase ripetuta" in e for e in validate(sel, bs))


def test_heuristic_on_bernareggio_prefers_continuous_take():
    bs = bernareggio()
    sel = heuristic_selection(bs)
    takes = {t["take"]: t for b in bs for t in b["takes"]}
    chosen = {takes[i["take"]]["text"].lower(): takes[i["take"]]["clip"] for i in sel["order"]}
    # cantina, prezzo e chiusura dalla stessa take continua, come nel reel montato a mano (Z50_6411)
    assert {c for txt, c in chosen.items() if "cantina" in txt or "simone venezia" in txt} == {"Z50_6411"}
    assert sel["order"][-1]["role"] == "chiusura"


def _t(tid, clip, text, start=0.0, end=None, complete=None):
    return {"take": tid, "clip": clip, "start": start, "end": end if end is not None else start + 3,
            "text": text, "complete": text.rstrip().endswith((".", "?", "!")) if complete is None else complete,
            "n_words": len(text.split()), "words": []}


def test_heuristic_fixes_from_first_real_plan():
    """Casi del primo piano reale di Bernareggio (regola locale)."""
    bs = [
        {"id": "b1", "takes": [_t("t1", "Z50_6398", "eccoci dentro l'appartamento ingresso direttamente sul soggiorno con cucina vista", complete=False)]},
        {"id": "b2", "takes": [_t("t2", "Z50_6402", "Il disimpegno ci conduce nella zona notte dove troviamo un ampio bagno... Perché? Perché?"),
                               _t("t3", "Z50_6402", "Il disimpegno ci conduce nella zona notte dove troviamo due camere e un bagno con box doccia.", start=14)]},
        {"id": "b3", "takes": [_t("t4", "Z50_6402", "un ampio bagno, basta.")]},
        {"id": "b4", "takes": [_t("t5", "Z50_6411", "Mi chiederai il prezzo, 188 mila euro, per vivere in questi tre locali nel centro di Bernareggio.")]},
        {"id": "b5", "takes": [_t("t6", "Z50_6406", "188 mila euro per vivere in questi tre locali a Bernareggio.")]},
        {"id": "b6", "takes": [_t("t7", "Z50_6416", "Ehi scusa ma tu sei un agente immobiliare? Sì posso esserti utile?", start=1.2, end=4.1)]},
        {"id": "b7", "takes": [_t("t8", "Z50_6416", "Sì sto cercando un appartamento in vendita a Bernareggio.", start=4.2, end=6.4)]},
        {"id": "b8", "takes": [_t("t9", "Z50_6411", "Se vuoi maggiori informazioni contattami, io sono Simone Venezia.", start=15)]},
    ]
    sel = heuristic_selection(bs)
    order = [(i["battuta"], i["role"]) for i in sel["order"]]
    assert order == [("b6", "aggancio"), ("b7", "aggancio"), ("b1", "corpo"), ("b2", "corpo"), ("b4", "corpo"),
                     ("b8", "chiusura")]
    assert next(i["take"] for i in sel["order"] if i["battuta"] == "b2") == "t3"
    reasons = {e["battuta"]: e["reason"] for e in sel["excluded"]}
    assert reasons["b3"] == "nessuna take utilizzabile"          # "…, basta." è un'indicazione di regia
    assert reasons["b5"] == "contenuto già presente in un'altra battuta"


def test_validate_rejects_repeated_content_with_different_words():
    bs = [{"id": "b1", "takes": [_t("t1", "Z50_1", "Mi chiederai il prezzo, 188 mila euro, per vivere in questi tre locali.")]},
          {"id": "b2", "takes": [_t("t2", "Z50_2", "188 mila euro per vivere in questi tre locali.")]}]
    sel = {"order": [{"battuta": "b1", "take": "t1", "role": "corpo"}, {"battuta": "b2", "take": "t2", "role": "corpo"}]}
    assert any("frase ripetuta" in e for e in validate(sel, bs))
