"""Movimento di camera: ingresso, uscita e tremolio di ogni clip (§6.1, rev. 8). Sui mezzanine.

Per ogni coppia di fotogrammi (a bassa risoluzione) si stima il moto globale con punti tracciati
(Lucas-Kanade) e una trasformazione di similitudine: spostamento orizzontale e verticale, zoom.
- moto lento (media mobile di 0,5 s) = movimenti voluti → movimento d'ingresso e d'uscita;
- moto rapido (il resto) = tremolio → decide la stabilizzazione.
Convenzione: "pan_right" = la camera ruota verso destra (la scena scorre a sinistra);
"push_in" = la camera avanza o zooma (la scena si ingrandisce).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

AN_W, AN_H = 180, 320          # risoluzione di analisi (stesso rapporto 9:16 dei mezzanine)
FPS = 25
SMOOTH_S = 0.5
MOVE_SPEED = 0.10              # frazione di larghezza al secondo oltre cui c'è un movimento voluto
MOVE_ZOOM = 0.06               # variazione di scala (log) al secondo oltre cui c'è avanzamento/zoom
MIN_MOVE_S = 0.4
QUIET_S = 0.3                  # il movimento finisce dopo 0,3 s sotto soglia
START_WINDOW_S = 0.5           # il movimento d'ingresso deve cominciare entro 0,5 s dall'inizio
SHAKE_THRESHOLD = 2.5          # px/fotogramma a 1440 px di larghezza: da tarare sull'archivio


@dataclass
class Move:
    kind: str       # pan_left | pan_right | tilt_up | tilt_down | push_in | pull_out
    start_ms: int
    end_ms: int
    peak_ms: int    # fotogramma più veloce: punto migliore per il taglio

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def read_frames(path: Path, w: int = AN_W, h: int = AN_H, fps: int = FPS) -> np.ndarray:
    """Fotogrammi in scala di grigi a bassa risoluzione, (n, h, w) uint8."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
           "-vf", f"fps={fps},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w)


def frame_motion(frames: np.ndarray) -> np.ndarray:
    """Per ogni passo t→t+1: [dx, dy, log_scala], con dx, dy in frazioni di larghezza.
    dx > 0: la scena scorre a destra. log_scala > 0: la scena si ingrandisce."""
    import cv2

    out = np.zeros((max(len(frames) - 1, 0), 3))
    w = frames.shape[2] if len(frames) else AN_W
    for i in range(len(frames) - 1):
        a, b = frames[i], frames[i + 1]
        pts = cv2.goodFeaturesToTrack(a, maxCorners=200, qualityLevel=0.01, minDistance=6)
        if pts is None or len(pts) < 8:
            continue
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None, winSize=(15, 15), maxLevel=3)
        ok = st.reshape(-1) == 1
        if ok.sum() < 8:
            continue
        m, _ = cv2.estimateAffinePartial2D(pts[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=1.5)
        if m is None:
            continue
        scale = float(np.hypot(m[0, 0], m[1, 0]))
        # traslazione riferita al centro del fotogramma (lo zoom attorno al centro non deve sembrare un pan)
        cx, cy = frames.shape[2] / 2, frames.shape[1] / 2
        tx = m[0, 2] + (m[0, 0] - 1) * cx + m[0, 1] * cy
        ty = m[1, 2] + m[1, 0] * cx + (m[1, 1] - 1) * cy
        out[i] = (tx / w, ty / w, np.log(max(scale, 1e-6)))
    return out


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) == 0:
        return x
    n = max(1, min(n, len(x)))
    k = np.ones(n) / n
    pad = np.pad(x, ((n // 2, n - 1 - n // 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(pad[:, j], k, mode="valid") for j in range(x.shape[1])], axis=1)


def _kind(seg: np.ndarray) -> str:
    dx, dy, ds = seg.mean(axis=0)
    # confronto in "frazione di larghezza al secondo": lo zoom muove i bordi di circa metà larghezza × log_scala
    score = {"pan": abs(dx), "tilt": abs(dy), "zoom": abs(ds) * 0.5}
    k = max(score, key=score.get)
    if k == "pan":
        return "pan_right" if dx < 0 else "pan_left"
    if k == "tilt":
        return "tilt_down" if dy < 0 else "tilt_up"
    return "push_in" if ds > 0 else "pull_out"


def find_moves(motion: np.ndarray, fps: int = FPS) -> tuple[Move | None, Move | None]:
    """Movimento d'ingresso (dall'inizio) e d'uscita (verso la fine) dal moto lento."""
    if len(motion) < 3:
        return None, None
    slow = _smooth(motion, int(SMOOTH_S * fps))
    speed = np.hypot(slow[:, 0], slow[:, 1]) * fps
    zoom = np.abs(slow[:, 2]) * fps
    moving = (speed > MOVE_SPEED) | (zoom > MOVE_ZOOM)
    quiet = int(QUIET_S * fps)

    def span(order: list[int]) -> tuple[int, int] | None:
        window = int(START_WINDOW_S * fps)
        first = next((k for k, i in enumerate(order[:window + 1]) if moving[i]), None)
        if first is None:
            return None
        last, still = first, 0
        for k in range(first, len(order)):
            if moving[order[k]]:
                last, still = k, 0
            else:
                still += 1
                if still >= quiet:
                    break
        a, b = sorted((order[first], order[last]))
        return (a, b + 1) if (b + 1 - a) / fps >= MIN_MOVE_S else None

    def move(sp: tuple[int, int] | None) -> Move | None:
        if not sp:
            return None
        a, b = sp
        seg = slow[a:b]
        peak = a + int(np.argmax(np.hypot(seg[:, 0], seg[:, 1]) + np.abs(seg[:, 2]) * 0.5))
        return Move(_kind(seg), round(a * 1000 / fps), round(b * 1000 / fps), round(peak * 1000 / fps))

    n = len(motion)
    entry = move(span(list(range(n))))
    exit_ = move(span(list(range(n - 1, -1, -1))))
    if entry and exit_ and exit_.start_ms <= entry.end_ms:  # un solo movimento che occupa tutta la clip
        exit_ = None if entry.end_ms - entry.start_ms >= exit_.end_ms - exit_.start_ms else exit_
        entry = None if exit_ else entry
    return entry, exit_


SHAKE_WINDOW_S = 0.2
SHAKE_PERCENTILE = 60


def shake_score(motion: np.ndarray, fps: int = FPS, width_px: int = 1440) -> float:
    """Tremolio: ampiezza tipica del moto rapido (moto meno la sua media su 0,2 s), in px per fotogramma
    a 1440 px di larghezza. Si usa un percentile e non la media: l'inizio e la fine di un movimento
    voluto lasciano un residuo su pochi fotogrammi, il tremolio vero c'è su quasi tutti."""
    if len(motion) < 3:
        return 0.0
    fast = motion[:, :2] - _smooth(motion, max(3, int(SHAKE_WINDOW_S * fps)))[:, :2]
    return float(np.percentile(np.hypot(fast[:, 0], fast[:, 1]), SHAKE_PERCENTILE) * width_px)


def analyze(path: Path) -> dict:
    frames = read_frames(path)
    motion = frame_motion(frames)
    entry, exit_ = find_moves(motion)
    shake = shake_score(motion)
    return {"duration_ms": round(len(frames) * 1000 / FPS), "shake": round(shake, 2),
            "needs_stabilization": shake > SHAKE_THRESHOLD,
            "entry": entry.to_dict() if entry else None, "exit": exit_.to_dict() if exit_ else None}
