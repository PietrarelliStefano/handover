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
