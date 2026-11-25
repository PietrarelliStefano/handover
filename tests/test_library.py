import shutil
import subprocess

import pytest

from handover.library import Library, make_placeholders

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg assente")


def tone(path, seconds):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=d={seconds}", str(path)], check=True)
    return path


def test_add_requires_license_and_chooses_music(tmp_path):
    lib = Library(tmp_path / "lib")
    terms = tmp_path / "pixabay-termini.html"
    terms.write_text("termini")
    with pytest.raises(ValueError):
        lib.add(tone(tmp_path / "a.mp3", 1), tipo="musica", fonte="pixabay", licenza_file=None, mood="elegante")
    short = lib.add(tone(tmp_path / "s.mp3", 20), tipo="musica", fonte="pixabay", licenza_file=terms,
                    mood="elegante", url="https://pixabay.com/x", autore="Y")
    long_ = lib.add(tone(tmp_path / "l.mp3", 70), tipo="musica", fonte="pixabay", licenza_file=terms, mood="elegante")
    meta = lib.add(tone(tmp_path / "m.mp3", 90), tipo="musica", fonte="meta", licenza_file=terms, mood="elegante",
                   piattaforme=["instagram", "facebook"])
    assert short.id == "L-0001" and (lib.root / "licenze" / "L-0001" / "pixabay-termini.html").exists()
    t, flags = lib.choose_music(55)
    assert t.id == long_.id and flags == []                 # copre il reel; meta non copre TikTok
    assert lib.choose_music(55, piattaforme=["instagram"])[0].id in (long_.id, meta.id)


def test_placeholders_and_empty_library(tmp_path):
    lib = Library(tmp_path / "lib")
    assert lib.choose_music(50) == (None, [])
    added = make_placeholders(lib)
    assert sorted(t.categoria for t in added) == ["card", "prezzo", "whoosh"]
    assert make_placeholders(lib) == []                     # non li duplica
    w = lib.choose_sfx("whoosh")
    assert w.fonte == "generato" and 700 <= w.durata_ms <= 1100 and lib.path(w).exists()
