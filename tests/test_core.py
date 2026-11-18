import logging
from pathlib import Path
import pytest
from vaultifymd.core import Options, convert_one, discover, draw_progress, obsidian_links, parse_pages, parse_properties, safe_name, save_embedded_images
from vaultifymd import core

PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def test_pages(): assert parse_pages("1-3,5") == (0, 1, 2, 4)
@pytest.mark.parametrize("value", ["0", "3-1", "x", "1,,2"])
def test_bad_pages(value):
    with pytest.raises(ValueError): parse_pages(value)
def test_properties(): assert parse_properties(["status=done"]) == (("status", "done"),)
def test_safe_name(): assert safe_name('a:b?c') == "a_b_c"
def test_embedded_images_are_written_to_dir_with_spaces(tmp_path: Path):
    attach = tmp_path / "pasta com espaco" / "Meu Livro"
    image = f"![](data:image/png;base64,{PNG_1PX})"
    markdown, count = save_embedded_images(f"{image}\n{image}", attach, 7, "png", True, "att/pasta com espaco/Meu Livro")
    assert markdown == "![[att/pasta com espaco/Meu Livro/Meu Livro-p007-01.png]]\n![[att/pasta com espaco/Meu Livro/Meu Livro-p007-02.png]]"
    assert count == 2
    assert (attach / "Meu Livro-p007-02.png").read_bytes()[:4] == b"\x89PNG"
    _, next_page_count = save_embedded_images(image, attach, 8, "png", True)
    assert next_page_count == 1
    assert (attach / "Meu Livro-p008-01.png").exists()
def test_links(): assert obsidian_links("![](a/b.png)") == "![[b.png]]"
def test_progress_bar_reports_pages(capsys):
    draw_progress("livro.pdf", 5, 10)
    assert "5/10 págs" in capsys.readouterr().err
def test_discover(tmp_path: Path):
    (tmp_path / "A.PDF").write_bytes(b"x")
    sub = tmp_path / "sub"; sub.mkdir(); (sub / "B.pdf").write_bytes(b"x")
    assert len(discover([tmp_path], False, ("*.pdf",), ())) == 1
    assert len(discover([tmp_path], True, ("*.pdf",), ("sub/*",))) == 1
def test_parallel_pages_match_sequential(tmp_path: Path, monkeypatch):
    import pymupdf
    pdf = tmp_path / "doc.pdf"
    with pymupdf.open() as doc:
        for n in range(4):
            doc.new_page().insert_text((72, 72), f"Texto da página {n + 1}")
        doc.save(pdf)
    monkeypatch.setattr(core, "PAGE_BATCH", 1)
    notes = []
    for workers in (1, 2):
        options = Options(output_dir=tmp_path / f"out{workers}", attachments_dir=tmp_path / "att",
                          no_images=True, page_workers=workers)
        notes.append(Path(convert_one(pdf, options, logging.getLogger("test")).note).read_text(encoding="utf-8"))
    assert notes[0] == notes[1]
    assert "**Página 4**" in notes[1]
