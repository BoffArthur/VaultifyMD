from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_NAME, init as init_config, load
from .core import Options, convert_many, discover, parse_pages, parse_properties


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vaultifymd", description="PDF para Markdown pronto para Obsidian.")
    p.add_argument("inputs", nargs="*", metavar="INPUT", help="Arquivos PDF ou diretórios")
    p.add_argument("--init-config", nargs="?", const=DEFAULT_NAME, metavar="PATH")
    p.add_argument("--force", action="store_true", help="Sobrescreve configuração no init")
    p.add_argument("--config", type=Path, help="Arquivo TOML; padrão: ./vaultifymd.toml")
    p.add_argument("--vault", type=Path)
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("-i", "--img-dir", "--attachments-dir", dest="attachments_dir", type=Path)
    p.add_argument("-r", "--recursive", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--preserve-tree", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--root", type=Path, help="Raiz usada para preservar a árvore")
    p.add_argument("--include", action="append", help="Glob incluído; repetível")
    p.add_argument("--exclude", action="append", help="Glob excluído; repetível")
    policy = p.add_mutually_exclusive_group()
    policy.add_argument("--overwrite", action="store_true", default=None)
    policy.add_argument("--skip-existing", action="store_true", default=None)
    p.add_argument("--collision", choices=["skip", "overwrite", "duplicate"], help="Nota existente: ignorar, sobrescrever ou duplicar (sufixo -2, -3...)")
    p.add_argument("--pages")
    p.add_argument("--dpi", type=int)
    p.add_argument("--size-limit", type=float)
    p.add_argument("--image-format", choices=["png", "jpg"])
    p.add_argument("--no-images", dest="no_images", action="store_true", default=None)
    p.add_argument("--wikilinks", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--frontmatter", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--tags", help="Tags separadas por vírgula")
    p.add_argument("--property", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--title-from", choices=["filename", "metadata", "first-heading"])
    p.add_argument("--copy-pdf", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--embed-pdf", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--source-link", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--page-separator", metavar="TEXT")
    p.add_argument("--workers", type=int)
    p.add_argument("--page-workers", type=int, help="Processos paralelos por PDF, cada um com um lote de páginas")
    p.add_argument("--dry-run", action="store_true", default=None)
    verbosity = p.add_mutually_exclusive_group()
    verbosity.add_argument("-q", "--quiet", action="store_true")
    verbosity.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--log-file", type=Path)
    p.add_argument("--json", action="store_true", help="Emite resumo JSON")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def choose(args, cfg: dict, key: str, default=None):
    value = getattr(args, key, None)
    return cfg.get(key, default) if value is None else value


def path_inside(vault: Path | None, value: Path, label: str) -> Path:
    if not vault:
        return value.expanduser().resolve()
    vault = vault.expanduser().resolve()
    result = value.expanduser().resolve() if value.is_absolute() else (vault / value).resolve()
    try:
        result.relative_to(vault)
    except ValueError as exc:
        raise ValueError(f"{label} deve ficar dentro do Vault: {result}") from exc
    return result


def logger_for(args) -> logging.Logger:
    log = logging.getLogger("vaultifymd")
    log.handlers.clear(); log.setLevel(logging.DEBUG); log.propagate = False
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.ERROR if args.quiet else logging.DEBUG if args.verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s")); log.addHandler(console)
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(args.log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        handler.setLevel(logging.DEBUG); log.addHandler(handler)
    return log


def main(argv: list[str] | None = None) -> int:
    p = parser(); args = p.parse_args(argv)
    if args.init_config:
        try:
            init_config(Path(args.init_config), args.force)
            print(f"Configuração criada: {args.init_config}")
            return 0
        except Exception as exc:
            p.error(str(exc))
    if not args.inputs:
        p.error("informe ao menos um INPUT ou use --init-config")
    try:
        cfg = load(args.config)
        vault_raw = choose(args, cfg, "vault")
        vault = Path(vault_raw).expanduser().resolve() if vault_raw else None
        output = path_inside(vault, Path(choose(args, cfg, "output", "vaultifymd")), "--output")
        attach_default = Path(choose(args, cfg, "output", "vaultifymd"))
        attachments = path_inside(vault, Path(choose(args, cfg, "attachments_dir", attach_default)), "--attachments-dir")
        dpi = int(choose(args, cfg, "dpi", 150)); size = float(choose(args, cfg, "size_limit", 0.05))
        workers = int(choose(args, cfg, "workers", 1))
        page_workers = int(choose(args, cfg, "page_workers", 4))
        if not 36 <= dpi <= 1200: raise ValueError("DPI deve estar entre 36 e 1200.")
        if not 0 <= size <= 1: raise ValueError("size-limit deve estar entre 0 e 1.")
        if not 1 <= workers <= 32: raise ValueError("workers deve estar entre 1 e 32.")
        if not 1 <= page_workers <= 16: raise ValueError("page-workers deve estar entre 1 e 16.")
        tags_raw = choose(args, cfg, "tags", [])
        tags = tuple(x.strip().lstrip("#") for x in (tags_raw.split(",") if isinstance(tags_raw, str) else tags_raw) if x.strip())
        inputs = [Path(x) for x in args.inputs]
        root_raw = choose(args, cfg, "root")
        root = Path(root_raw).expanduser().resolve() if root_raw else (inputs[0].expanduser().resolve() if len(inputs) == 1 and inputs[0].is_dir() else None)
        options = Options(
            vault=vault, output_dir=output, attachments_dir=attachments, root=root,
            recursive=bool(choose(args, cfg, "recursive", False)), preserve_tree=bool(choose(args, cfg, "preserve_tree", False)),
            include=tuple(args.include or cfg.get("include", ["*.pdf"])), exclude=tuple(args.exclude or cfg.get("exclude", [])),
            pages=parse_pages(choose(args, cfg, "pages")), dpi=dpi, size_limit=size,
            image_format=choose(args, cfg, "image_format", "png"), no_images=bool(choose(args, cfg, "no_images", False)),
            wikilinks=bool(choose(args, cfg, "wikilinks", True)), overwrite=bool(choose(args, cfg, "overwrite", False)),
            skip_existing=bool(choose(args, cfg, "skip_existing", False)), collision=choose(args, cfg, "collision", "skip"),
            frontmatter=bool(choose(args, cfg, "frontmatter", True) or tags or args.property), tags=tags,
            properties=parse_properties(args.property), title_from=choose(args, cfg, "title_from", "filename"),
            copy_pdf=bool(choose(args, cfg, "copy_pdf", False)), embed_pdf=bool(choose(args, cfg, "embed_pdf", False)),
            source_link=bool(choose(args, cfg, "source_link", False)), page_separator=choose(args, cfg, "page_separator"),
            dry_run=bool(choose(args, cfg, "dry_run", False)), workers=workers, page_workers=page_workers)
        if options.overwrite and options.skip_existing: raise ValueError("overwrite e skip-existing são incompatíveis.")
        pdfs = discover(inputs, options.recursive, options.include, options.exclude)
        if not pdfs: raise ValueError("Nenhum PDF encontrado.")
    except Exception as exc:
        p.error(str(exc))
    log = logger_for(args)
    summary = convert_many(pdfs, options, log, progress=not args.quiet and sys.stderr.isatty())
    if args.json:
        print(summary.to_json())
    elif not args.quiet:
        print(f"Convertidos: {summary.converted} | Ignorados: {summary.skipped} | Erros: {summary.failed}")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
