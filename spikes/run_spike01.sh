#!/usr/bin/env bash
# Spike 01, parte video (§14). Da eseguire sul Mac con l'SSD montato.
#   ./spikes/run_spike01.sh ["/Volumes/WORK/IMMOBILIARE VENEZIA/11.14 - BERNAREGGIO/CLIP"]
# Output in ~/handover-work/spike-01/<shooting>/ ; l'archivio è solo letto.
set -euo pipefail
cd "$(dirname "$0")/.."
CLIP_DIR="${1:-/Volumes/WORK/IMMOBILIARE VENEZIA/11.14 - BERNAREGGIO/CLIP}"

uv sync --group spike
uv run handover probe "$CLIP_DIR"
uv run python spikes/s01_mezzanine.py "$CLIP_DIR"
uv run python spikes/s02_transcribe.py "$CLIP_DIR" --models turbo large-v3
uv run python spikes/s03_reel_subs.py "$CLIP_DIR"
uv run python spikes/s04_compare.py "$CLIP_DIR"
uv run python spikes/s05_takes.py "$CLIP_DIR" --variant turbo
uv run python spikes/s05_takes.py "$CLIP_DIR" --variant large-v3
uv run python spikes/s06_report.py "$CLIP_DIR"
