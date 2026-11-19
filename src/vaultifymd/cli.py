from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import DEFAULT_NAME, init as init_config, load
from .core import Options, convert_many, discover, parse_pages, parse_properties
from .updater import run_update


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vaultifymd",
        usage="%(prog)s [opções] INPUT [INPUT ...]",
        description="PDF para Markdown pronto para Obsidian.",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=32),
        add_help=False,
    )

    ajuda = p.add_argument_group("Ajuda")
    ajuda.add_argument("-h", "--help", action="help", help="mostra esta ajuda e encerra")

    entrada = p.add_argument_group("Entrada")
    entrada.add_argument("inputs", nargs="*", metavar="INPUT", help="arquivos PDF ou pastas")
    entrada.add_argument("-r", "--recursive", action=argparse.BooleanOptionalAction, default=None, help="busca PDFs em subpastas")
    entrada.add_argument("--include", action="append", metavar="GLOB", help="inclui arquivos pelo padrão (repetível; padrão: *.pdf)")
    entrada.add_argument("--exclude", action="append", metavar="GLOB", help="exclui arquivos pelo padrão (repetível)")
    entrada.add_argument("--pages", metavar="LISTA", help="páginas a converter, ex.: 1-5,8")
    entrada.add_argument("--preserve-tree", action=argparse.BooleanOptionalAction, default=None, help="mantém a estrutura de pastas na saída")
    entrada.add_argument("--root", type=Path, metavar="PASTA", help="raiz usada para preservar a árvore")

    saida = p.add_argument_group("Saída")
    saida.add_argument("--vault", type=Path, metavar="PASTA", help="Vault do Obsidian; saída e anexos devem ficar dentro dele")
    saida.add_argument("-o", "--output", type=Path, metavar="PASTA", help="pasta das notas (padrão: vaultifymd)")
    saida.add_argument("-i", "--img-dir", "--attachments-dir", dest="attachments_dir", type=Path, metavar="PASTA",
                       help="pasta dos anexos (padrão: a mesma da saída)")
    policy = saida.add_mutually_exclusive_group()
    policy.add_argument("--collision", choices=["skip", "overwrite", "duplicate", "update"],
                        help="nota existente: skip (ignorar, padrão), overwrite, duplicate (sufixo -2, -3...) "
                             "ou update (só se o PDF for mais novo)")
    policy.add_argument("--overwrite", dest="collision", action="store_const", const="overwrite", help=argparse.SUPPRESS)
    policy.add_argument("--skip-existing", dest="collision", action="store_const", const="skip", help=argparse.SUPPRESS)

    conversao = p.add_argument_group("Conversão")
    conversao.add_argument("--dpi", type=int, metavar="N", help="resolução de renderização (36–1200, padrão: 150)")
    conversao.add_argument("--size-limit", type=float, metavar="F", help="tamanho mínimo de imagem como fração da página (0–1, padrão: 0.05)")
    conversao.add_argument("--image-format", choices=["png", "jpg"], help="formato das imagens extraídas")
    conversao.add_argument("--images", action=argparse.BooleanOptionalAction, default=None, help="extrai imagens dos PDFs (padrão: sim)")
    conversao.add_argument("--image-text", action=argparse.BooleanOptionalAction, default=None,
                           help="inclui o texto dentro de figuras e diagramas no Markdown (padrão: não)")
    conversao.add_argument("--wikilinks", action=argparse.BooleanOptionalAction, default=None,
                           help="usa wikilinks do Obsidian; --no-wikilinks gera links Markdown")

    conteudo = p.add_argument_group("Conteúdo")
    conteudo.add_argument("--frontmatter", action=argparse.BooleanOptionalAction, default=None, help="adiciona frontmatter YAML")
    conteudo.add_argument("--title-from", choices=["filename", "metadata", "first-heading"], help="origem do título (padrão: filename)")
    conteudo.add_argument("--tags", metavar="TAGS", help="tags separadas por vírgula")
    conteudo.add_argument("--property", action="append", default=[], metavar="CHAVE=VALOR",
                          help="propriedade personalizada no frontmatter (repetível)")
    conteudo.add_argument("--copy-pdf", action=argparse.BooleanOptionalAction, default=None, help="copia o PDF para a pasta de anexos")
    conteudo.add_argument("--embed-pdf", action=argparse.BooleanOptionalAction, default=None, help="incorpora o PDF na nota")
    conteudo.add_argument("--source-link", action=argparse.BooleanOptionalAction, default=None, help="inclui link para o PDF original")
    conteudo.add_argument("--page-separator", metavar="TEXTO", help="separador entre páginas (padrão: **Página N**)")

    desempenho = p.add_argument_group("Desempenho")
    desempenho.add_argument("--workers", type=int, metavar="N", help="PDFs processados em paralelo (1–32)")
    desempenho.add_argument("--page-workers", type=int, metavar="N",
                            help="processos paralelos por PDF, cada um com um lote de páginas (1–16, padrão: 4)")

    execucao = p.add_argument_group("Execução e log")
    execucao.add_argument("--dry-run", action="store_true", default=None, help="mostra o que seria feito, sem gravar arquivos")
    verbosity = execucao.add_mutually_exclusive_group()
    verbosity.add_argument("-q", "--quiet", action="store_true", help="mostra apenas erros")
    verbosity.add_argument("-v", "--verbose", action="store_true", help="mostra detalhes de depuração")
    execucao.add_argument("--log-file", type=Path, metavar="ARQUIVO", help="grava log em arquivo")
    execucao.add_argument("--json", action="store_true", help="emite resumo em JSON")
    execucao.add_argument("--version", action="version", version=f"%(prog)s {__version__}", help="mostra a versão e encerra")
    execucao.add_argument("--update", action="store_true", help="instala a última release do GitHub, se for mais nova, e encerra")

    configuracao = p.add_argument_group("Configuração")
    configuracao.add_argument("--init-config", nargs="?", const=DEFAULT_NAME, metavar="ARQUIVO",
                              help=f"cria o TOML de configuração (padrão: {DEFAULT_NAME}) e encerra")
    configuracao.add_argument("--force", action="store_true", help="sobrescreve a configuração existente no --init-config")
    configuracao.add_argument("--config", type=Path, metavar="ARQUIVO", help="arquivo TOML (padrão: ./vaultifymd.toml)")
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
    if args.update:
        return run_update()
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
            image_format=choose(args, cfg, "image_format", "png"), no_images=not bool(choose(args, cfg, "images", not cfg.get("no_images", False))),
            image_text=bool(choose(args, cfg, "image_text", False)),
            wikilinks=bool(choose(args, cfg, "wikilinks", True)),
            collision=choose(args, cfg, "collision", "overwrite" if cfg.get("overwrite") else "skip"),
            frontmatter=bool(choose(args, cfg, "frontmatter", True) or tags or args.property), tags=tags,
            properties=parse_properties(args.property), title_from=choose(args, cfg, "title_from", "filename"),
            copy_pdf=bool(choose(args, cfg, "copy_pdf", False)), embed_pdf=bool(choose(args, cfg, "embed_pdf", False)),
            source_link=bool(choose(args, cfg, "source_link", False)), page_separator=choose(args, cfg, "page_separator"),
            dry_run=bool(choose(args, cfg, "dry_run", False)), workers=workers, page_workers=page_workers)
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
