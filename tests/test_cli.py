from pathlib import Path
import pytest
from vaultifymd import __version__
from vaultifymd.cli import parser, path_inside
from vaultifymd.config import init, load


def test_version(): assert __version__ == "0.3.0"
def test_negative_flags_parse():
    args = parser().parse_args(["manual.pdf", "--no-images", "--no-wikilinks"])
    assert args.images is False and args.wikilinks is False
def test_collision_flags_share_one_option():
    assert parser().parse_args(["manual.pdf", "--skip-existing"]).collision == "skip"
    assert parser().parse_args(["manual.pdf", "--collision", "update"]).collision == "update"
    with pytest.raises(SystemExit): parser().parse_args(["manual.pdf", "--collision", "skip", "--overwrite"])
def test_config(tmp_path: Path):
    path = tmp_path / "vaultifymd.toml"; init(path); assert load(path)["dpi"] == 150
def test_vault_guard(tmp_path: Path):
    vault = tmp_path / "vault"
    assert path_inside(vault, Path("Notes"), "output") == (vault / "Notes").resolve()
    with pytest.raises(ValueError): path_inside(vault, tmp_path / "outside", "output")
