"""Trascrizione con mlx-whisper, timestamp per parola (§6.2.1, rev. 7: turbo, nessun prompt)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


class Transcriber(Protocol):
    def __call__(self, audio: Path) -> dict: ...


def _clean(res: dict) -> dict:
    segs = [{"start": s["start"], "end": s["end"], "text": s["text"].strip(),
             "avg_logprob": s.get("avg_logprob"), "no_speech_prob": s.get("no_speech_prob"),
             "words": [{"w": w["word"].strip(), "start": w["start"], "end": w["end"],
                        "p": round(w.get("probability", 0.0), 3)} for w in s.get("words", [])]}
            for s in res.get("segments", [])]
    return {"text": res.get("text", "").strip(), "segments": segs}


class MlxWhisper:
    """Whisper su Apple Silicon. Il modello resta in memoria tra una clip e l'altra."""

    def __init__(self, model: str = DEFAULT_MODEL, language: str = "it"):
        self.model, self.language = model, language

    def __call__(self, audio: Path) -> dict:
        try:
            import mlx_whisper
        except ImportError as e:  # pragma: no cover - solo fuori dal Mac
            raise RuntimeError("mlx-whisper non disponibile: serve un Mac con Apple Silicon (`uv sync`).") from e
        # Nessun initial_prompt: nello spike faceva scrivere a Whisper il testo del prompt (§6.2.1).
        res = mlx_whisper.transcribe(str(audio), path_or_hf_repo=self.model, language=self.language,
                                     word_timestamps=True, condition_on_previous_text=False)
        return _clean(res) | {"model": self.model}
