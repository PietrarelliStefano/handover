"""Libreria locale di musica e SFX con prova della licenza (§6.4, §9 Traccia, rev. 8).

Struttura in ~/handover-work/lib/ (o $HANDOVER_LIB):

    index.json                 elenco delle tracce
    musica/L-0001.<ext>        musica
    sfx/S-0001.<ext>           effetti
    licenze/<id>/prova.json    prova della licenza (URL, autore, data, note)
    licenze/<id>/<termini>     copia dei termini in vigore il giorno del download

Senza file di licenza una traccia non entra (§9), tranne gli SFX generati localmente con ffmpeg
(fonte "generato"), che non hanno diritti di terzi.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from handover.workdir import work_root

TIPI = ("musica", "sfx")
CATEGORIE_SFX = ("whoosh", "prezzo", "card")
MOOD_DEFAULT = "elegante"
PIATTAFORME_DEFAULT = ("instagram", "tiktok")
TUTTE_LE_PIATTAFORME = ("instagram", "facebook", "tiktok", "youtube", "linkedin")


def lib_root() -> Path:
    return Path(os.environ.get("HANDOVER_LIB", work_root() / "lib")).expanduser()


@dataclass
class Traccia:
    id: str
    file: str                       # relativo a lib_root()
    tipo: str                       # musica | sfx
    durata_ms: int
    fonte: str                      # pixabay | generato | …
    licenza_file: str | None        # relativo a lib_root()
    licenza_prova: dict
    piattaforme_consentite: list[str]
    mood: str | None = None         # solo musica
    categoria: str | None = None    # solo sfx: whoosh | prezzo | card
    bpm: float | None = None
    bloccata: bool = False
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def licenza_id(self) -> str:
        return self.id


class Library:
    def __init__(self, root: Path | None = None):
        self.root = root or lib_root()
        self.index = self.root / "index.json"

    def tracks(self) -> list[Traccia]:
        if not self.index.exists():
            return []
        return [Traccia(**t) for t in json.loads(self.index.read_text())["tracks"]]

    def _save(self, tracks: list[Traccia]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tracks": [asdict(t) for t in tracks]}, indent=2, ensure_ascii=False))
        tmp.replace(self.index)

    def _next_id(self, tipo: str) -> str:
        prefix = "L" if tipo == "musica" else "S"
        nums = [int(t.id[2:]) for t in self.tracks() if t.id.startswith(prefix + "-")]
        return f"{prefix}-{max(nums, default=0) + 1:04d}"

    def add(self, file: Path, *, tipo: str, fonte: str, licenza_file: Path | None, url: str | None = None,
            autore: str | None = None, mood: str | None = None, categoria: str | None = None,
            piattaforme: list[str] | None = None, note: str = "") -> Traccia:
        if tipo not in TIPI:
            raise ValueError(f"tipo non valido: {tipo} ({', '.join(TIPI)})")
        if tipo == "sfx" and categoria not in CATEGORIE_SFX:
            raise ValueError(f"categoria SFX non valida: {categoria} ({', '.join(CATEGORIE_SFX)})")
        if licenza_file is None and fonte != "generato":
            raise ValueError("Senza file di licenza la traccia non entra nella libreria (§9).")
        tid = self._next_id(tipo)
        sub = "musica" if tipo == "musica" else "sfx"
        dst = self.root / sub / f"{tid}{file.suffix.lower()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dst)
        lic_dir = self.root / "licenze" / tid
        lic_dir.mkdir(parents=True, exist_ok=True)
        lic_rel = None
        if licenza_file is not None:
            shutil.copy2(licenza_file, lic_dir / licenza_file.name)
            lic_rel = str((lic_dir / licenza_file.name).relative_to(self.root))
        prova = {"url": url, "autore": autore, "data_download": date.today().isoformat(), "fonte": fonte,
                 "note": note}
        (lic_dir / "prova.json").write_text(json.dumps(prova, indent=2, ensure_ascii=False))
        t = Traccia(id=tid, file=str(dst.relative_to(self.root)), tipo=tipo, durata_ms=duration_ms(dst),
                    fonte=fonte, licenza_file=lic_rel, licenza_prova=prova,
                    piattaforme_consentite=list(piattaforme or PIATTAFORME_DEFAULT),
                    mood=mood if tipo == "musica" else None, categoria=categoria if tipo == "sfx" else None,
                    note=note)
        self._save(self.tracks() + [t])
        return t

    def path(self, t: Traccia) -> Path:
        return self.root / t.file

    def usable(self, tipo: str, piattaforme: list[str]) -> list[Traccia]:
        return [t for t in self.tracks() if t.tipo == tipo and not t.bloccata
                and set(piattaforme) <= set(t.piattaforme_consentite)]

    def choose_music(self, duration_s: float, mood: str = MOOD_DEFAULT,
                     piattaforme: list[str] = list(PIATTAFORME_DEFAULT)) -> tuple[Traccia | None, list[str]]:
        """Traccia del mood richiesto (o del default) che copre le piattaforme; la più vicina alla durata,
        preferendo quelle lunghe almeno quanto il reel. Ritorna anche i flag."""
        flags = []
        tracks = self.usable("musica", piattaforme)
        if not tracks:
            return None, []  # il flag musica_mancante lo mette il piano
        same = [t for t in tracks if t.mood == mood] or [t for t in tracks if t.mood == MOOD_DEFAULT]
        if not same:
            flags.append("mood_non_disponibile")
            same = tracks
        need = duration_s * 1000
        best = min(same, key=lambda t: (t.durata_ms < need, abs(t.durata_ms - need)))
        return best, flags

    def choose_sfx(self, categoria: str, piattaforme: list[str] = list(PIATTAFORME_DEFAULT)) -> Traccia | None:
        cands = [t for t in self.usable("sfx", piattaforme) if t.categoria == categoria]
        # gli SFX scelti da Stefano hanno la precedenza sui segnaposto generati
        cands.sort(key=lambda t: (t.fonte == "generato", t.id))
        return cands[0] if cands else None


def duration_ms(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return round(float(out) * 1000)


# Segnaposto generati con ffmpeg: nessun diritto di terzi. Sostituibili con SFX scelti da Stefano.
PLACEHOLDERS = {
    "whoosh": ("anoisesrc=d=0.9:c=pink:a=0.8:r=48000,"
               "highpass=f=300,lowpass=f=6000,"
               "afade=t=in:d=0.55:curve=exp,afade=t=out:st=0.55:d=0.35:curve=exp,volume=1.6"),
    "prezzo": ("sine=f=1568:d=1.0:r=48000[a];sine=f=2349:d=1.0:r=48000[b];"
               "[a][b]amix=inputs=2:normalize=0,afade=t=out:st=0.02:d=0.95:curve=exp,volume=0.7"),
    "card": ("sine=f=880:d=0.18:r=48000,afade=t=in:d=0.005,afade=t=out:st=0.03:d=0.15:curve=exp,volume=0.8"),
}


def make_placeholders(lib: Library) -> list[Traccia]:
    """Genera e aggiunge gli SFX segnaposto mancanti (uno per categoria)."""
    import tempfile

    added = []
    have = {t.categoria for t in lib.tracks() if t.tipo == "sfx" and t.fonte == "generato"}
    for cat, graph in PLACEHOLDERS.items():
        if cat in have:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{cat}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph, "-ac", "2",
                            "-c:a", "pcm_s16le", str(out)], check=True)
            added.append(lib.add(out, tipo="sfx", categoria=cat, fonte="generato", licenza_file=None,
                                 piattaforme=list(TUTTE_LE_PIATTAFORME),
                                 note=f"Segnaposto generato localmente da Handover con ffmpeg ({graph}). "
                                      "Nessun diritto di terzi."))
    return added
