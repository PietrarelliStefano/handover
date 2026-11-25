"""CLI `handover`."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from handover.ingest.probe import probe_folder

app = typer.Typer(help="Handover: dallo shooting al materiale da consegnare.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Handover: dallo shooting al materiale da consegnare."""


@app.command()
def probe(
    cartella: Path = typer.Argument(..., exists=True, file_okay=False, readable=True,
                                    help="Cartella con le clip (sola lettura)."),
    json_out: Path | None = typer.Option(None, "--json", help="Scrive anche il risultato in JSON."),
) -> None:
    """Legge formato e tag di rotazione di ogni clip, senza modificare nulla."""
    infos = probe_folder(cartella)
    if not infos:
        typer.echo(f"Nessun video in {cartella}")
        raise typer.Exit(1)

    header = f"{'file':<22} {'durata':>7} {'codec':<6} {'origine':>10} {'rot':>5} {'display':>10} {'fps':>6} {'bit':>3}  audio            flag"
    typer.echo(header)
    typer.echo("-" * len(header))
    for i in infos:
        name = Path(i.file).name
        src = f"{i.width}×{i.height}" if i.width else "-"
        disp = f"{i.display_width}×{i.display_height}" if i.display_width else "-"
        rot = f"{i.rotation}°" if i.rotation_tag else "—"
        audio = f"{i.audio_codec or '-'} {i.audio_sample_rate or ''}"
        if i.audio_bits:
            audio += f"/{i.audio_bits}"
        dur = f"{i.duration_s:.1f}s" if i.duration_s is not None else "-"
        typer.echo(
            f"{name:<22} {dur:>7} {i.codec or '-':<6} {src:>10} {rot:>5} {disp:>10} "
            f"{i.fps or '-':>6} {i.bit_depth or '-':>3}  {audio:<16} {','.join(i.flags)}"
        )

    tot = sum(i.duration_s or 0 for i in infos)
    vert = sum(1 for i in infos if i.orientation == "verticale")
    typer.echo(f"\n{len(infos)} clip, {tot:.1f} s totali, {vert} verticali dopo la rotazione.")

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps([i.to_dict() for i in infos], indent=2, ensure_ascii=False))
        typer.echo(f"JSON: {json_out}")


if __name__ == "__main__":
    app()


@app.command()
def run(
    cartella: Path = typer.Argument(..., exists=True, file_okay=False, readable=True,
                                    help="Cartella dello shooting (con CLIP/ o CLIPS/). Solo lettura."),
    agente: str = typer.Option("venezia", help="Agente: glossario e template."),
    da: str | None = typer.Option(None, help="Rifà da questo passo in poi: probe, mezzanine, vad, "
                                             "trascrizione, take, scelta, piano."),
    senza_llm: bool = typer.Option(False, "--senza-llm", help="Scelta delle take con la regola locale."),
    render_: bool = typer.Option(False, "--render", help="Fa anche il render del piano."),
) -> None:
    """Shooting → piano di montaggio (M2: parlato e sottotitoli)."""
    from handover.pipeline import STEPS, run_video

    if da and da not in STEPS:
        raise typer.BadParameter(f"passo sconosciuto: {da} (validi: {', '.join(STEPS)})")
    plan = run_video(cartella, agent=agente, redo_from=da, llm=None if senza_llm else _default_llm(),
                     log=typer.echo)
    typer.echo(f"\nPiano: {plan}")
    if render_:
        from handover.render import render_plan
        typer.echo(f"Render: {render_plan(plan, None, log=typer.echo)}")


def _default_llm():
    from handover.video.selection import run_claude
    return run_claude


@app.command()
def render(piano: Path = typer.Argument(..., exists=True, dir_okay=False, help="Piano di montaggio JSON (§7)."),
           out: Path | None = typer.Option(None, help="File di uscita (default: render/v<N>.mp4 nella cartella di lavoro).")) -> None:
    """Render del piano con Remotion (render/)."""
    from handover.render import render_plan

    path = render_plan(piano, out, log=typer.echo)
    typer.echo(f"Render: {path}")
