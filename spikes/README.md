# Spike

Script usa e getta, fuori dal pacchetto. Leggono l'archivio e scrivono solo in `~/handover-work/`
(o in `$HANDOVER_WORK`); `common.guard_output` rifiuta qualsiasi scrittura sotto `/Volumes/WORK`.

## Spike 01 — video (§14)

Sul Mac, con l'SSD montato:

```bash
./spikes/run_spike01.sh
```

| Passo | Script | Uscita in `~/handover-work/spike-01/11.14-BERNAREGGIO/` |
| --- | --- | --- |
| Probe e mezzanine VideoToolbox | `s01_mezzanine.py` | `probe.json`, `mezzanine/`, `results/mezzanine.json` |
| Trascrizione turbo e large-v3 (clip + audio del reel), anche con glossario (`--prompt`) | `s02_transcribe.py` | `audio/`, `transcripts/<variante>/`, `results/transcribe-*.json` |
| VAD, A-roll / b-roll, filtro allucinazioni | `s02b_vad.py` | `results/vad.json`, `transcripts/<variante>+vad/` |
| Sottotitoli del reel via OCR | `s03_reel_subs.py` | `reel/subs_ocr.json`, `reel/reference.txt` |
| Da quali clip viene l'audio del reel | `s03b_reel_match.py` | `results/reel_map.json` |
| WER e token critici | `s04_compare.py` | `results/compare.json` |
| Take ripetute | `s05_takes.py` | `results/takes-<modello>.json` |
| Report | `s06_report.py` | `docs/spike-01.md` nel repo |

I passi già fatti vengono saltati (`--force` per rifarli). Il modello Silero VAD viene scaricato
una volta dalla wheel ufficiale su PyPI, verificata con sha256, in `~/handover-work/models/`.

Il riferimento OCR va riletto guardando il reel: copiare `reel/reference.txt` in
`reel/reference_manual.txt`, correggerlo, poi rieseguire `s04`, `s05` e `s06`.
