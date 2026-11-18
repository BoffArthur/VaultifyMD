from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Options:
    output_dir: Path
    attachments_dir: Path
    vault: Path | None = None
    root: Path | None = None
    recursive: bool = False
    preserve_tree: bool = False
    include: tuple[str, ...] = ("*.pdf",)
    exclude: tuple[str, ...] = ()
    pages: tuple[int, ...] | None = None
    dpi: int = 150
    size_limit: float = 0.05
    image_format: str = "png"
    no_images: bool = False
    wikilinks: bool = True
    overwrite: bool = False
    skip_existing: bool = False
    collision: str = "error"
    frontmatter: bool = False
    tags: tuple[str, ...] = ()
    properties: tuple[tuple[str, str], ...] = ()
    title_from: str = "filename"
    copy_pdf: bool = False
    embed_pdf: bool = False
    source_link: bool = False
    page_separator: str | None = None
    dry_run: bool = False
    workers: int = 1


@dataclass
class ItemResult:
    source: str
    note: str | None = None
    status: str = "failed"
    images: int = 0
    message: str = ""


@dataclass
class Summary:
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[ItemResult] = field(default_factory=list)

    def add(self, item: ItemResult) -> None:
        self.results.append(item)
        if item.status == "converted":
            self.converted += 1
        elif item.status == "skipped":
            self.skipped += 1
        else:
            self.failed += 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def parse_pages(spec: str | None) -> tuple[int, ...] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            raise ValueError("A lista de páginas contém um item vazio.")
        if "-" in part:
            bits = part.split("-")
            if len(bits) != 2 or not all(x.isdigit() for x in bits):
                raise ValueError(f"Intervalo inválido: {part}")
            start, end = map(int, bits)
            if start < 1 or end < start:
                raise ValueError(f"Intervalo inválido: {part}")
            pages.update(range(start - 1, end))
        elif part.isdigit() and int(part) >= 1:
            pages.add(int(part) - 1)
        else:
            raise ValueError(f"Página inválida: {part}")
    return tuple(sorted(pages))


def parse_properties(values: Iterable[str]) -> tuple[tuple[str, str], ...]:
    result = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Propriedade inválida: {value}. Use chave=valor.")
        key, content = (x.strip() for x in value.split("=", 1))
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
            raise ValueError(f"Nome de propriedade inválido: {key}")
        result.append((key, content))
    return tuple(result)


def discover(inputs: Iterable[Path], recursive: bool, include: tuple[str, ...], exclude: tuple[str, ...]) -> list[Path]:
    found: dict[str, Path] = {}
    for raw in inputs:
        path = raw.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Entrada não encontrada: {path}")
        candidates = [path] if path.is_file() else (path.rglob("*") if recursive else path.iterdir())
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
                continue
            rel = candidate.name if path.is_file() else candidate.relative_to(path).as_posix()
            if not any(fnmatch.fnmatch(rel.casefold(), p.casefold()) for p in include):
                continue
            if any(fnmatch.fnmatch(rel.casefold(), p.casefold()) for p in exclude):
                continue
            resolved = candidate.resolve()
            found[str(resolved).casefold()] = resolved
    return sorted(found.values(), key=lambda p: str(p).casefold())


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "untitled"


def image_dir_path(path: Path) -> Path:
    # pymupdf4llm replaces spaces with "_" in the image paths it writes, so the directory must use the same name.
    return Path(str(path).replace(" ", "_"))


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def markdown_title(markdown: str, pdf: Path, method: str) -> str:
    if method == "first-heading":
        match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
        if match:
            return match.group(1).strip()
    if method == "metadata":
        try:
            import pymupdf
            title = (pymupdf.open(pdf).metadata or {}).get("title", "").strip()
            if title:
                return title
        except Exception:
            pass
    return pdf.stem


def obsidian_links(markdown: str) -> str:
    pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    return pattern.sub(lambda m: f"![[{Path(m.group(1).strip().strip(chr(34))).name}]]", markdown)


def relative_note_dir(pdf: Path, options: Options) -> Path:
    if not options.preserve_tree or not options.root:
        return Path()
    try:
        return pdf.parent.relative_to(options.root)
    except ValueError:
        return Path()


def unique_note_path(base: Path, pdf: Path, collision: str) -> Path:
    if not base.exists() or collision in {"error", "overwrite", "skip"}:
        return base
    if collision == "hash":
        token = hashlib.sha1(str(pdf).encode("utf-8")).hexdigest()[:8]
        return base.with_name(f"{base.stem}-{token}{base.suffix}")
    index = 2
    while True:
        candidate = base.with_name(f"{base.stem}-{index}{base.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def build_frontmatter(title: str, pdf: Path, options: Options) -> str:
    modified = datetime.fromtimestamp(pdf.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    lines = ["---", f"title: {yaml_quote(title)}", f"source: {yaml_quote(str(pdf))}",
             f"source_modified: {yaml_quote(modified)}", "generator: vaultifymd"]
    if options.tags:
        lines.append("tags:")
        lines.extend(f"  - {yaml_quote(tag)}" for tag in options.tags)
    for key, value in options.properties:
        lines.append(f"{key}: {yaml_quote(value)}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def convert_one(pdf: Path, options: Options, logger: logging.Logger) -> ItemResult:
    rel_dir = relative_note_dir(pdf, options)
    out_dir = options.output_dir / rel_dir
    attach_dir = image_dir_path(options.attachments_dir / rel_dir / safe_name(pdf.stem))
    note_path = out_dir / f"{safe_name(pdf.stem)}.md"
    policy = "overwrite" if options.overwrite else "skip" if options.skip_existing else options.collision
    note_path = unique_note_path(note_path, pdf, policy)

    if note_path.exists():
        if policy == "skip":
            return ItemResult(str(pdf), str(note_path), "skipped", message="Nota existente")
        if policy != "overwrite":
            raise FileExistsError(f"Nota existente: {note_path}")

    if options.dry_run:
        return ItemResult(str(pdf), str(note_path), "converted", message="dry-run")

    out_dir.mkdir(parents=True, exist_ok=True)
    if not options.no_images:
        attach_dir.mkdir(parents=True, exist_ok=True)

    import pymupdf4llm
    kwargs: dict[str, object] = {"write_images": not options.no_images}
    if not options.no_images:
        kwargs.update(image_path=str(attach_dir), image_format=options.image_format,
                      dpi=options.dpi, image_size_limit=options.size_limit)
    if options.pages is not None:
        kwargs["pages"] = list(options.pages)
    if options.page_separator is not None:
        kwargs["page_separators"] = True

    before = set(attach_dir.glob("*")) if attach_dir.exists() else set()
    markdown = pymupdf4llm.to_markdown(str(pdf), **kwargs)
    if options.page_separator:
        markdown = markdown.replace("-----\n", f"\n{options.page_separator}\n")
    if options.wikilinks:
        markdown = obsidian_links(markdown)

    title = markdown_title(markdown, pdf, options.title_from)
    sections: list[str] = []
    if options.frontmatter:
        sections.append(build_frontmatter(title, pdf, options))
    if options.source_link:
        sections.append(f"[Abrir PDF de origem]({pdf.as_uri()})\n")
    if options.copy_pdf:
        pdf_target = attach_dir / pdf.name
        shutil.copy2(pdf, pdf_target)
        if options.embed_pdf:
            sections.append(f"![[{pdf_target.name}]]\n")
    elif options.embed_pdf:
        sections.append(f"![[{pdf.name}]]\n")
    sections.append(markdown.lstrip())
    note_path.write_text("\n".join(sections), encoding="utf-8", newline="\n")
    images = len(set(attach_dir.glob("*")) - before) if attach_dir.exists() else 0
    logger.debug("Nota criada: %s", note_path)
    return ItemResult(str(pdf), str(note_path), "converted", images)


def convert_many(pdfs: list[Path], options: Options, logger: logging.Logger) -> Summary:
    summary = Summary()
    def run(pdf: Path) -> ItemResult:
        try:
            return convert_one(pdf, options, logger)
        except Exception as exc:
            logger.debug("Falha detalhada em %s", pdf, exc_info=True)
            return ItemResult(str(pdf), status="failed", message=str(exc))

    if options.workers == 1:
        results = map(run, pdfs)
    else:
        pool = ThreadPoolExecutor(max_workers=options.workers)
        futures = {pool.submit(run, pdf): pdf for pdf in pdfs}
        results = (future.result() for future in as_completed(futures))
    for result in results:
        summary.add(result)
        log = logger.error if result.status == "failed" else logger.info
        log("%s: %s%s", result.status.upper(), result.source,
            f" ({result.message})" if result.message else "")
    if options.workers != 1:
        pool.shutdown()
    summary.results.sort(key=lambda x: x.source.casefold())
    return summary
