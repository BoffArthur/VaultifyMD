from pathlib import Path
import pytest
from vaultifymd import __version__
from vaultifymd.cli import parser, path_inside
from vaultifymd.config import init, load


def test_version(): assert __version__ == "0.2.2"
def test_negative_flags_parse():
    args = parser().parse_args(["manual.pdf", "--no-images", "--no-wikilinks"])
    assert args.no_images is True and args.wikilinks is False
def test_config(tmp_path: Path):
    path = tmp_path / "vaultifymd.toml"; init(path); assert load(path)["dpi"] == 150
def test_vault_guard(tmp_path: Path):
    vault = tmp_path / "vault"
    assert path_inside(vault, Path("Notes"), "output") == (vault / "Notes").resolve()
    with pytest.raises(ValueError): path_inside(vault, tmp_path / "outside", "output")
