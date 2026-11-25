"""Movimento di camera su clip sintetiche con movimento noto."""

import shutil
import subprocess
from pathlib import Path

import pytest

from handover.video.motion import SHAKE_THRESHOLD, analyze

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg assente")


@pytest.fixture(scope="module")
def still(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("motion") / "still.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1200x1600:rate=1",
                    "-f", "lavfi", "-i", "nullsrc=size=1200x1600,geq=random(1)*255:128:128",
                    "-filter_complex", "[0][1]blend=all_mode=overlay:all_opacity=0.35", "-frames:v", "1", str(p)],
                   check=True)
    return p


def clip(still: Path, out: Path, vf: str, seconds: float = 4.0) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "25", "-i", str(still),
                    "-vf", vf + ",scale=360:640,format=yuv420p", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "ultrafast", str(out)], check=True)
    return out


def test_pan_right_at_start(still, tmp_path):
    # la camera gira a destra nel primo secondo: la finestra di ritaglio si sposta a destra
    r = analyze(clip(still, tmp_path / "pan.mp4", "crop=600:1067:x='if(lt(t,1),300*t,300)':y=200"))
    assert r["entry"] and r["entry"]["kind"] == "pan_right"
    assert r["entry"]["start_ms"] <= 200 and 800 <= r["entry"]["end_ms"] <= 1400
    assert r["exit"] is None and not r["needs_stabilization"]


def test_push_in_at_end(still, tmp_path):
    vf = ("crop=600:1067:300:200,zoompan=z='if(gt(in_time,2.8),1+0.5*(in_time-2.8),1)'"
          ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=600x1066:fps=25")
    r = analyze(clip(still, tmp_path / "zoom.mp4", vf))
    assert r["entry"] is None
    assert r["exit"] and r["exit"]["kind"] == "push_in" and r["exit"]["start_ms"] >= 2400


def test_shaky_handheld_needs_stabilization(still, tmp_path):
    r = analyze(clip(still, tmp_path / "shake.mp4", "crop=600:1067:x='300+18*(random(1)-0.5)':y='200+18*(random(2)-0.5)'"))
    assert r["shake"] > SHAKE_THRESHOLD and r["needs_stabilization"]


def test_static_clip(still, tmp_path):
    r = analyze(clip(still, tmp_path / "static.mp4", "crop=600:1067:300:200"))
    assert r["entry"] is None and r["exit"] is None and r["shake"] < 0.5


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg assente")
def test_stabilize_reduces_shake_and_keeps_pan(still, tmp_path):
    from handover.video.media import has_filter, stabilize
    if not has_filter("vidstabtransform"):
        pytest.skip("ffmpeg senza vidstab")
    vf = "crop=600:1067:x='if(lt(t,1),300*t,300)+14*(random(1)-0.5)':y='200+14*(random(2)-0.5)'"
    src = clip(still, tmp_path / "shaky_pan.mp4", vf)
    before = analyze(src)
    out = tmp_path / "stab.mp4"
    stabilize(src, out, encoder="libx264")
    after = analyze(out)
    assert before["needs_stabilization"] and after["shake"] < before["shake"] / 3
    assert after["entry"] and after["entry"]["kind"] == "pan_right"   # il movimento voluto resta
