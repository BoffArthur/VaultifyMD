from pathlib import Path
import pytest
from vaultifymd.core import discover, image_dir_path, obsidian_links, parse_pages, parse_properties, safe_name


def test_pages(): assert parse_pages("1-3,5") == (0, 1, 2, 4)
@pytest.mark.parametrize("value", ["0", "3-1", "x", "1,,2"])
def test_bad_pages(value):
    with pytest.raises(ValueError): parse_pages(value)
def test_properties(): assert parse_properties(["status=done"]) == (("status", "done"),)
def test_safe_name(): assert safe_name('a:b?c') == "a_b_c"
def test_image_dir_replaces_spaces(): assert image_dir_path(Path("out dir/Meu Livro")) == Path("out_dir/Meu_Livro")
def test_links(): assert obsidian_links("![](a/b.png)") == "![[b.png]]"
def test_discover(tmp_path: Path):
    (tmp_path / "A.PDF").write_bytes(b"x")
    sub = tmp_path / "sub"; sub.mkdir(); (sub / "B.pdf").write_bytes(b"x")
    assert len(discover([tmp_path], False, ("*.pdf",), ())) == 1
    assert len(discover([tmp_path], True, ("*.pdf",), ("sub/*",))) == 1
