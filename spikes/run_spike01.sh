#!/usr/bin/env bash
# Spike 01, parte video (§14). Da eseguire sul Mac.
#   ./spikes/run_spike01.sh [CARTELLA_CLIP] [REEL]
# CARTELLA_CLIP: qualsiasi cartella di clip (anche una copia sul disco interno).
# REEL: il reel finito; di default "<cartella shooting>/<nome shooting>.mp4".
#   Se manca (e non c'è reel/reference_manual.txt) si saltano OCR, mappa audio e WER.
# I passi già fatti (mezzanine, trascrizioni, OCR) vengono saltati: rilanciare costa solo i passi nuovi.
# Output in ~/handover-work/spike-01/<shooting>/ ; le clip sono solo lette.
set -euo pipefail
cd "$(dirname "$0")/.."
CLIP_DIR="${1:-/Volumes/WORK/IMMOBILIARE VENEZIA/11.14 - BERNAREGGIO/CLIP}"
SHOOT_DIR="$(dirname "$CLIP_DIR")"
REEL="${2:-$SHOOT_DIR/$(basename "$SHOOT_DIR").mp4}"
WORK="${HANDOVER_WORK:-$HOME/handover-work}/spike-01/$(basename "$SHOOT_DIR" | tr -d ' ')"

uv sync --group spike
uv run handover probe "$CLIP_DIR"
uv run python spikes/s01_mezzanine.py "$CLIP_DIR"
uv run python spikes/s02_transcribe.py "$CLIP_DIR" --reel "$REEL" --models turbo large-v3
uv run python spikes/s02_transcribe.py "$CLIP_DIR" --reel "$REEL" --models turbo large-v3 --prompt
uv run python spikes/s02b_vad.py "$CLIP_DIR"

if [[ -f "$REEL" ]]; then
  uv run python spikes/s03_reel_subs.py "$CLIP_DIR" --reel "$REEL"
  uv run python spikes/s03b_reel_match.py "$CLIP_DIR"
else
  echo "Reel non trovato ($REEL): niente OCR dei sottotitoli né mappa audio."
fi
if [[ -f "$WORK/reel/reference_manual.txt" || -f "$WORK/reel/reference.txt" ]]; then
  uv run python spikes/s04_compare.py "$CLIP_DIR"
else
  echo "Nessun riferimento: niente WER. Per averlo scrivi il testo corretto in $WORK/reel/reference_manual.txt"
fi

for v in "$WORK"/transcripts/*/; do
  uv run python spikes/s05_takes.py "$CLIP_DIR" --variant "$(basename "$v")" > "$WORK/results/takes-$(basename "$v").txt"
done
echo "Take: elenco completo in $WORK/results/takes-*.txt"
uv run python spikes/s06_report.py "$CLIP_DIR"
