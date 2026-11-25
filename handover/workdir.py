"""Cartella di lavoro di Handover e regola "gli originali non si toccano mai" (CLAUDE.md).

Struttura per shooting, in ~/handover-work/<shooting_id>/ (o $HANDOVER_WORK):

    probe.json            metadati delle clip
    mezzanine/<clip>.mov  sorgenti ruotate 1440×2560
    audio/<clip>.wav      audio 16 kHz mono per VAD e Whisper
    vad.json              parlato per clip, A-roll / b-roll
    transcripts/<clip>.json
    takes.json            battute e take candidate
    selection.json        scelta delle take e ordine (LLM o euristica)
    plan/v<N>.json        piani di montaggio versionati (§7)
    render/v<N>.mp4

Ogni passo scrive il suo artefatto; rieseguire un passo non rifà quelli prima.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

CLIP_DIR_NAMES = ("CLIP", "CLIPS")


def work_root() -> Path:
    return Path(os.environ.get("HANDOVER_WORK", Path.home() / "handover-work")).expanduser()


def models_dir() -> Path:
    return work_root() / "models"


def find_clip_dir(shooting: Path) -> Path:
    for name in CLIP_DIR_NAMES:
        if (shooting / name).is_dir():
            return shooting / name
    raise FileNotFoundError(f"Nessuna cartella {' o '.join(CLIP_DIR_NAMES)} in {shooting}")


def slug(text: str) -> str:
    from handover.video.text import strip_accents
    s = re.sub(r"[^a-z0-9]+", "-", strip_accents(text.lower())).strip("-")
    return s or "shooting"


def shooting_id(shooting: Path, year: int | None = None) -> str:
    """'11.14 - BERNAREGGIO' → '2026-11-14-bernareggio' (§7). Anno dalle clip o, in mancanza, corrente."""
    name = shooting.name
    m = re.match(r"\s*(\d{1,2})\.(\d{1,2})\s*-\s*(.+)$", name)
    y = year or date.today().year
    if m:
        return f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}-{slug(m.group(3))}"
    return slug(name)


@dataclass(frozen=True)
class Workspace:
    shooting: Path   # cartella dello shooting (sola lettura)
    root: Path       # cartella di lavoro

    @property
    def clip_dir(self) -> Path:
        return find_clip_dir(self.shooting)

    def path(self, *parts: str) -> Path:
        p = guard_output(self.root.joinpath(*parts), self.shooting)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def plan_versions(self) -> list[Path]:
        d = self.root / "plan"
        if not d.exists():
            return []
        return sorted((p for p in d.glob("v*.json") if re.fullmatch(r"v\d+\.json", p.name)),
                      key=lambda p: int(p.stem[1:]))

    def next_plan_path(self) -> Path:
        versions = self.plan_versions()
        n = int(versions[-1].stem[1:]) + 1 if versions else 1
        return self.path("plan", f"v{n}.json")


def guard_output(path: Path, *protected: Path) -> Path:
    """Rifiuta qualsiasi scrittura dentro le cartelle protette (lo shooting e i suoi originali)."""
    p = path.expanduser().resolve()
    for root in protected:
        r = root.expanduser().resolve()
        if p == r or r in p.parents:
            raise PermissionError(f"Rifiutato: {p} è dentro {r}. Gli originali non si toccano.")
    return p


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)
