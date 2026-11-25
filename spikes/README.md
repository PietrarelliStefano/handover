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
| Trascrizione turbo e large-v3 (clip + audio del reel) | `s02_transcribe.py` | `audio/`, `transcripts/<modello>/`, `results/transcribe-*.json` |
| Sottotitoli del reel via OCR | `s03_reel_subs.py` | `reel/subs_ocr.json`, `reel/reference.txt` |
| WER e token critici | `s04_compare.py` | `results/compare.json` |
| Take ripetute | `s05_takes.py` | `results/takes-<modello>.json` |
| Report | `s06_report.py` | `docs/spike-01.md` nel repo |

Il riferimento OCR va riletto guardando il reel: copiare `reel/reference.txt` in
`reel/reference_manual.txt`, correggerlo, poi rieseguire `s04`, `s05` e `s06`.
