from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

from . import __version__

REPO = "BoffArthur/VaultifyMD"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/tags/{{tag}}.zip"


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.strip().lstrip("vV").split("."))


def latest_tag(timeout: float = 10) -> str:
    request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "vaultifymd"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["tag_name"]


def run_update() -> int:
    try:
        tag = latest_tag()
        latest = parse_version(tag)
    except (OSError, KeyError, ValueError) as exc:
        print(f"Não foi possível verificar a última versão ({exc}). Confira se há releases publicadas.", file=sys.stderr)
        return 1
    if latest <= parse_version(__version__):
        print(f"VaultifyMD já está na versão mais recente ({__version__}).")
        return 0
    print(f"Atualizando VaultifyMD {__version__} -> {tag}...")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", ARCHIVE_URL.format(tag=tag)], check=False)
    if result.returncode:
        print("Falha ao instalar a nova versão.", file=sys.stderr)
        return 1
    print(f"VaultifyMD atualizado para {tag}.")
    return 0
