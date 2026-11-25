from pathlib import Path

from typer.testing import CliRunner

from handover.cli import app


def test_run_with_render_passes_plain_values(tmp_path, monkeypatch):
    plan = tmp_path / "plan" / "v1.json"
    calls = {}
    monkeypatch.setattr("handover.pipeline.run_video", lambda *a, **k: plan)

    def fake_render(p, out, log=print):
        calls["args"] = (p, out)
        return tmp_path / "render" / "v1.mp4"

    monkeypatch.setattr("handover.render.render_plan", fake_render)
    shooting = tmp_path / "11.14 - X"
    shooting.mkdir()
    res = CliRunner().invoke(app, ["run", str(shooting), "--senza-llm", "--render"])
    assert res.exit_code == 0, res.output
    assert calls["args"] == (plan, None)   # prima arrivava un OptionInfo di Typer al posto di None
    assert "Render:" in res.output
