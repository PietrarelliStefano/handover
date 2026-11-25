# Handover

Pipeline locale che trasforma uno shooting immobiliare in materiale pronto da consegnare: foto HDR dai RAW in bracketing e reel 9:16 montato dalle clip dell'agente. La specifica è in `docs/specifica-v1.md` e decide su tutto. Se un'implementazione contraddice la specifica, va cambiata la specifica prima del codice.

## Contesto

- Uso personale di Stefano, un solo utente. Gira sul suo MacBook Pro M1 con 16 GB di RAM.
- Cliente attuale: Immobiliare Venezia (agente Simone Venezia). Template di brand `venezia`.
- Macchina: Nikon Z50II + Viltrox AF 9mm f/2.8 Z. RAW: NEF **lossless** (gli High Efficiency non sono decodificabili da LibRaw). Video: HEVC 4K 25p, con tag di rotazione da rispettare.

## Stack

- Python 3.12, gestito con `uv`. Pacchetto `handover/`, CLI `handover` (Typer).
- rawpy (LibRaw ≥ 0.22), OpenCV, lensfunpy, mlx-whisper, ffmpeg con VideoToolbox.
- Render video: Remotion (Node, TypeScript) in `render/`, chiamato solo tramite `handover render <piano.json>`.
- Review: FastAPI + pagina web locale. Persistenza: SQLite + filesystem.
- Clip generate (M5): sessione `claude -p` con l'MCP di Artlist, input e output su file.

## Struttura

```text
handover/
  ingest/      scansione, EXIF, gruppi di bracket, controllo RAW
  photo/       sviluppo, allineamento, fusione, colore, geometria, export
  video/       mezzanine, A/B-roll, trascrizione, take, piano di montaggio, audio
  review/      API FastAPI e pagina di review
  generate/    integrazione Artlist (M5)
  db.py        SQLite
render/        progetto Remotion
spikes/        script usa e getta dello spike (fuori dal pacchetto)
docs/          specifica e note di design
tests/
```

## Regole

- **Gli originali non si toccano mai.** Mai scrivere, rinominare o cancellare in `RAW/` o `CLIP/` dello shooting. Gli output vanno in `RAW/EXPORT/` (foto, come oggi) e nella cartella di lavoro di Handover.
- Il **piano di montaggio JSON** è il contratto tra analisi e render: ogni modifica al formato va riportata in §7 della specifica, con un aumento di `version`.
- Nessun file originale esce dal Mac. All'LLM vanno solo trascrizioni e keyframe a 512 px.
- I numeri nei sottotitoli (prezzi, metrature, indirizzi) sono **token critici**: mai consegnare senza conferma in review.
- Musica e SFX solo dalla libreria locale con prova della licenza. Niente CapCut.
- Le clip generate hanno sempre `generated: true` e la sovrimpressione "Arredamento virtuale". Mai AI sulle foto dei portali.
- Crediti Artlist: stimare prima di generare; chiedere conferma solo se la stima è ≥ 10% dei crediti disponibili.

## Dati di test

Archivio reale su SSD esterno: `/Volumes/WORK/IMMOBILIARE VENEZIA/`, 15 shooting nel formato `MM.GG - COMUNE/` con `RAW/`, `CLIP/` (o `CLIPS/`) e il reel finito. Reference principali: `11.14 - BERNAREGGIO` (bracket + export Lightroom + reel) e `11.18 - LISSONE` (reel con home staging virtuale). I NEF dell'archivio sono High Efficiency: per i test foto servono shooting nuovi in lossless o la conversione con Adobe DNG Converter.

Non copiare l'archivio nel repo. I test che lo usano vanno marcati `@pytest.mark.archive` e saltati se il volume non è montato.

## Comandi

```bash
uv sync                      # dipendenze
uv run pytest                # test veloci
uv run pytest -m archive     # test sull'archivio reale (SSD collegato)
uv run handover run "<cartella shooting>"
```

## Stile

- Codice e identificatori in inglese, messaggi all'utente e documentazione in italiano.
- Funzioni pure dove possibile (`photo/` e `video/` non sanno nulla di DB e HTTP).
- Ogni passo della pipeline scrive un artefatto su disco riutilizzabile: rieseguire un passo non deve rifare quelli prima.
