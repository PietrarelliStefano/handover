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
