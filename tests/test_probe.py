import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from handover.cli import app
from handover.ingest.probe import find_videos, parse_probe


def _probe(w=3840, h=2160, rotation=None, transfer="bt709", fps="25/1"):
    v = {"codec_type": "video", "codec_name": "hevc", "profile": "Main", "width": w, "height": h,
         "avg_frame_rate": fps, "pix_fmt": "yuv420p", "color_transfer": transfer,
         "tags": {"creation_time": "2026-11-14T10:00:00.000000Z"}}
    if rotation is not None:
        v["side_data_list"] = [{"side_data_type": "Display Matrix", "rotation": rotation}]
    a = {"codec_type": "audio", "codec_name": "pcm_s24le", "sample_rate": "48000", "bits_per_sample": 24}
    return {"streams": [v, a], "format": {"duration": "12.48"}}


def test_z50_vertical_with_tag():
    i = parse_probe(Path("Z50_0001.MOV"), _probe(rotation=90))
    assert (i.display_width, i.display_height, i.orientation) == (2160, 3840, "verticale")
    assert i.rotation_tag and i.flags == []
    assert i.fps == 25.0 and i.bit_depth == 8 and i.audio_bits == 24


def test_landscape_without_tag_is_flagged():
    i = parse_probe(Path("x.MOV"), _probe())
    assert i.orientation == "orizzontale" and "rotazione_assente" in i.flags


def test_native_vertical_no_flag():
    i = parse_probe(Path("x.MOV"), _probe(w=2160, h=3840))
    assert i.orientation == "verticale" and i.flags == []


def test_hlg_and_high_fps_flags():
    i = parse_probe(Path("x.MOV"), _probe(rotation=-90, transfer="arib-std-b67", fps="120000/1001"))
    assert "hlg_o_pq" in i.flags and "alto_fps" in i.flags


def test_find_videos_skips_appledouble(tmp_path):
    (tmp_path / "Z50_1.MOV").write_bytes(b"")
    (tmp_path / "._Z50_1.MOV").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")
    assert [p.name for p in find_videos(tmp_path)] == ["Z50_1.MOV"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg assente")
def test_cli_probe_on_rotated_clip(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine", "-t", "1", "-c:v", "libx264", "-c:a", "aac", str(src)], check=True)
    clip = tmp_path / "clips" / "Z50_0001.MOV"
    clip.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(src), "-c", "copy", str(clip)],
                   check=True)
    res = CliRunner().invoke(app, ["probe", str(clip.parent), "--json", str(tmp_path / "p.json")])
    assert res.exit_code == 0, res.output
    assert "180×320" in res.output and "1 verticali" in res.output
