"""Voice activity detection con Silero VAD v5 (ONNX, senza torch) e classificazione A-roll / b-roll (§6.1).

Il modello viene preso dalla wheel ufficiale `silero-vad` su PyPI, verificata con sha256,
ed estratto una volta in ~/handover-work/models/.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from handover.workdir import models_dir

WHEEL_URL = ("https://files.pythonhosted.org/packages/98/f7/5ae11d13fbb733cd3bfd7ff1c3a3902e6f55437df4b72307c1f168146268/"
             "silero_vad-5.1.2-py3-none-any.whl")
WHEEL_SHA256 = "93b41953d7774b165407fda6b533c119c5803864e367d5034dc626c82cfdf661"
MODEL_NAME = "silero_vad-5.1.2.onnx"

SR = 16000
CHUNK = 512      # 32 ms a 16 kHz
CONTEXT = 64     # campioni di contesto richiesti dal modello v5


def ensure_model(path: Path | None = None) -> Path:
    path = path or models_dir() / MODEL_NAME
    if path.exists():
        return path
    with urllib.request.urlopen(WHEEL_URL, timeout=60) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != WHEEL_SHA256:
        raise SystemExit("Hash della wheel silero-vad non corrispondente: download rifiutato.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        model = z.read("silero_vad/data/silero_vad.onnx")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(model)
    return path


def read_wav16k(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: serve WAV PCM 16 bit mono a 16 kHz")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


class SileroVAD:
    def __init__(self, model_path: Path | None = None):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(model_path or ensure_model()), sess_options=opts,
                                         providers=["CPUExecutionProvider"])

    def probs(self, audio: np.ndarray) -> np.ndarray:
        """Probabilità di parlato per ogni blocco da 32 ms."""
        n = int(np.ceil(len(audio) / CHUNK))
        audio = np.pad(audio, (0, n * CHUNK - len(audio)))
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, CONTEXT), dtype=np.float32)
        sr = np.array(SR, dtype=np.int64)
        out = np.empty(n, dtype=np.float32)
        for i in range(n):
            x = np.concatenate([context, audio[None, i * CHUNK:(i + 1) * CHUNK]], axis=1)
            p, state = self.sess.run(None, {"input": x, "state": state, "sr": sr})
            out[i] = p[0, 0]
            context = x[:, -CONTEXT:]
        return out


@dataclass
class VadParams:
    threshold: float = 0.5
    min_speech_s: float = 0.25
    min_silence_s: float = 0.30
    pad_s: float = 0.10


def speech_segments(probs: np.ndarray, p: VadParams = VadParams(), duration_s: float | None = None) -> list[tuple[float, float]]:
    """Isteresi come in get_speech_timestamps di Silero: entra sopra threshold, esce sotto threshold-0.15."""
    dt = CHUNK / SR
    neg = max(p.threshold - 0.15, 0.01)
    segs: list[list[float]] = []
    start = None
    silence_start = None
    for i, pr in enumerate(probs):
        t = i * dt
        if pr >= p.threshold:
            silence_start = None
            if start is None:
                start = t
        elif pr < neg and start is not None:
            if silence_start is None:
                silence_start = t
            if t + dt - silence_start >= p.min_silence_s:
                if silence_start - start >= p.min_speech_s:
                    segs.append([start, silence_start])
                start = silence_start = None
    if start is not None:
        end = len(probs) * dt
        if end - start >= p.min_speech_s:
            segs.append([start, end])
    dur = duration_s if duration_s is not None else len(probs) * dt
    out: list[list[float]] = []
    for a, b in segs:
        a, b = max(0.0, a - p.pad_s), min(dur, b + p.pad_s)
        if out and a <= out[-1][1]:
            out[-1][1] = b
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


WORD_PAD_S = 0.25


def in_speech(t0: float, t1: float, segs: list[tuple[float, float]], pad_s: float = WORD_PAD_S) -> bool:
    """La parola [t0, t1] è parlato se tocca un segmento allargato di pad_s.

    Whisper anticipa spesso l'inizio della prima parola di una take (a volte fino a 0 s): con il criterio
    "metà della parola dentro il parlato" il primo giro dello spike tagliava "L'", "Il", "Ehi", "Vai".
    Basta che la parola tocchi il parlato; le allucinazioni lontane dalla voce restano fuori.
    """
    return any(t1 > a - pad_s and t0 < b + pad_s for a, b in segs)


AROLL_MIN_SPEECH_S = 1.5  # §6.1, rev. 7


def classify(segs: list[tuple[float, float]], min_speech_s: float = AROLL_MIN_SPEECH_S) -> str:
    return "aroll" if sum(b - a for a, b in segs) >= min_speech_s else "broll"


def filter_words(segments: list[dict], speech: list[tuple[float, float]]) -> tuple[list[dict], list[str]]:
    """Toglie da una trascrizione le parole che non toccano il parlato e i segmenti che Whisper
    stesso giudica non parlato (no_speech_prob > 0,6 e avg_logprob < −1). Restituisce anche il testo tolto."""
    kept, removed = [], []
    for s in segments:
        nsp, lp = s.get("no_speech_prob"), s.get("avg_logprob")
        if nsp is not None and lp is not None and nsp > 0.6 and lp < -1.0:
            removed.append(s.get("text", ""))
            continue
        words = [w for w in s["words"] if in_speech(w["start"], w["end"], speech)]
        if len(words) < len(s["words"]):
            removed.append(" ".join(w["w"] for w in s["words"] if w not in words))
        if words:
            kept.append(dict(s, words=words, text=" ".join(w["w"] for w in words)))
    return kept, removed
