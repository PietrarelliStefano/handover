import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spikes"))

from common import guard_output  # noqa: E402
from s03_reel_subs import group_frames  # noqa: E402


def test_guard_refuses_archive_and_clip_dir(tmp_path):
    with pytest.raises(SystemExit):
        guard_output(Path("/Volumes/WORK/IMMOBILIARE VENEZIA/11.14 - BERNAREGGIO/CLIP/x.mov"))
    clips = tmp_path / "CLIP"
    with pytest.raises(SystemExit):
        guard_output(clips / "out.json", clips)
    assert guard_output(tmp_path / "work" / "out.json", clips) == (tmp_path / "work" / "out.json").resolve()


def test_group_frames_merges_and_drops_noise():
    dt = 0.2
    texts = [(0.0, "SEI UN AGENTE"), (0.2, "SEI UN AGENTE"), (0.4, "SEI UN AGENTF"),
             (0.6, "XQ"),  # un solo fotogramma: scartato
             (0.8, "IMMOBILIARE?"), (1.0, "IMMOBILIARE?")]
    groups = group_frames(texts, dt)
    assert [g["text"] for g in groups] == ["SEI UN AGENTE", "IMMOBILIARE?"]


def test_in_speech_keeps_early_first_word_drops_far_hallucination():
    from vad import in_speech
    segs = [(0.9, 4.0)]
    assert in_speech(0.0, 0.95, segs)        # "L'" con inizio anticipato da Whisper a 0 s
    assert in_speech(4.05, 4.2, segs)        # coda appena dopo la fine del parlato
    assert not in_speech(5.0, 5.6, segs)     # "Grazie." lontano dalla voce


def test_take_similarity_and_order():
    from s05_takes import clip_number, similarity
    assert similarity(["andiamolo", "a", "vedere"], ["andiamola", "a", "vedere"]) >= 0.7
    assert similarity(["l", "appartamento", "e", "concluso"], ["mi", "chiederai", "il", "prezzo"]) < 0.5
    assert sorted(["Z50_6412", "Z50_6406", "Z50_6405"], key=clip_number) == ["Z50_6405", "Z50_6406", "Z50_6412"]
