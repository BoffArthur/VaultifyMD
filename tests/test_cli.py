from pathlib import Path
from types import SimpleNamespace
import pytest
from vaultifymd import __version__, cli, updater
from vaultifymd.cli import parser, path_inside
from vaultifymd.config import init, load


def test_version(): assert __version__ == "0.4.0"
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
def test_update_version_is_compared_numerically():
    assert updater.parse_version("v0.10.0") > updater.parse_version("0.9.2")
def test_update_runs_without_inputs(monkeypatch):
    monkeypatch.setattr(cli, "run_update", lambda: 0)
    assert cli.main(["--update"]) == 0
def test_update_skips_pip_when_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "latest_tag", lambda: f"v{__version__}")
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: pytest.fail("pip não deveria rodar"))
    assert updater.run_update() == 0
def test_update_installs_newer_release(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "latest_tag", lambda: "v9.0.0")
    monkeypatch.setattr(updater.subprocess, "run", lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=0))
    assert updater.run_update() == 0
    assert calls[0][-1] == "https://github.com/BoffArthur/VaultifyMD/archive/refs/tags/v9.0.0.zip"
