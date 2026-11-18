from __future__ import annotations

import tomllib
from pathlib import Path

DEFAULT_NAME = "vaultifymd.toml"

TEMPLATE = '''# VaultifyMD configuration
vault = ""
output = "Notes/PDF"
attachments_dir = "Attachments/PDF"
recursive = true
preserve_tree = true
include = ["*.pdf"]
exclude = ["~$*", "*/Archive/*"]
overwrite = false
skip_existing = true
collision = "error"
dpi = 150
size_limit = 0.05
image_format = "png"
no_images = false
wikilinks = true
frontmatter = true
tags = ["pdf"]
title_from = "filename"
copy_pdf = false
embed_pdf = false
source_link = true
workers = 2
'''


def load(path: Path | None) -> dict:
    if path is None:
        candidate = Path.cwd() / DEFAULT_NAME
        if not candidate.exists():
            return {}
        path = candidate
    if not path.exists():
        raise FileNotFoundError(f"Configuração não encontrada: {path}")
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data, dict):
        raise ValueError("Configuração TOML inválida.")
    return data


def init(path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"Arquivo existente: {path}. Use --force.")
    path.write_text(TEMPLATE, encoding="utf-8", newline="\n")
