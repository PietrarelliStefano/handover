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
