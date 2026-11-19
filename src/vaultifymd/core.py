from __future__ import annotations

import base64
import contextlib
import fnmatch
import io
import json
import logging
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator

PAGE_BATCH = 10


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
    image_text: bool = False
    wikilinks: bool = True
    collision: str = "skip"
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
    page_workers: int = 1


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


EMBEDDED_IMAGE = re.compile(r"!\[[^\]]*\]\(data:image/(png|jpe?g);base64,([^)]+)\)")


def save_embedded_images(markdown: str, attach_dir: Path, page: int, image_format: str, wikilinks: bool) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        ext = "jpg" if match.group(1) in {"jpg", "jpeg"} else image_format
        name = f"{attach_dir.name}-p{page:03d}-{count:02d}.{ext}"
        attach_dir.mkdir(parents=True, exist_ok=True)
        (attach_dir / name).write_bytes(base64.b64decode(match.group(2)))
        return f"![[{attach_dir.name}/{name}]]" if wikilinks else f"![]({name})"

    return EMBEDDED_IMAGE.sub(replace, markdown), count


def clean_page(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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


def unique_note_path(base: Path, collision: str) -> Path:
    if not base.exists() or collision != "duplicate":
        return base
    index = 2
    while True:
        candidate = base.with_name(f"{base.stem}-{index}{base.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def note_is_current(pdf: Path, note: Path) -> bool:
    pdf_mtime = datetime.fromtimestamp(pdf.stat().st_mtime).astimezone().replace(microsecond=0)
    head = note.read_text(encoding="utf-8", errors="ignore")[:4096]
    match = re.search(r'^source_modified: "([^"]+)"', head, re.MULTILINE)
    if match:
        return datetime.fromisoformat(match.group(1)) >= pdf_mtime
    return note.stat().st_mtime >= pdf.stat().st_mtime


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


def draw_progress(label: str, done: int, total: int) -> None:
    width = 30
    filled = round(width * done / total) if total else width
    name = label if len(label) <= 40 else label[:37] + "..."
    sys.stderr.write(f"\r{name:<40} [{'#' * filled}{'.' * (width - filled)}] {done}/{total} págs")
    sys.stderr.flush()


@contextlib.contextmanager
def quiet_library() -> Iterator[io.StringIO]:
    import pymupdf
    captured = io.StringIO()
    pymupdf.set_messages(stream=captured)
    try:
        with contextlib.redirect_stdout(captured):
            yield captured
    finally:
        pymupdf.set_messages(stream=sys.stdout)


def render_pages(pages: list[int], pdf: str, embed_images: bool, image_format: str, dpi: int,
                 size_limit: float, image_text: bool = False) -> tuple[list[tuple[int, str]], str]:
    import pymupdf4llm
    kwargs: dict[str, object] = {"pages": pages, "page_chunks": True, "write_images": False,
                                 "embed_images": embed_images, "force_text": image_text}
    if embed_images:
        kwargs.update(image_format=image_format, dpi=dpi, image_size_limit=size_limit)
    with quiet_library() as messages:
        chunks = pymupdf4llm.to_markdown(pdf, **kwargs)
        rows = [(page, chunk["text"]) for page, chunk in zip(pages, chunks)]
    return rows, messages.getvalue().strip()


def convert_one(pdf: Path, options: Options, logger: logging.Logger,
                progress: Callable[[int, int], None] | None = None) -> ItemResult:
    rel_dir = relative_note_dir(pdf, options)
    out_dir = options.output_dir / rel_dir
    note_path = out_dir / f"{safe_name(pdf.stem)}.md"
    policy = options.collision
    note_path = unique_note_path(note_path, policy)
    attach_dir = options.attachments_dir / rel_dir / note_path.stem

    if note_path.exists() and policy == "skip":
        return ItemResult(str(pdf), str(note_path), "skipped", message="Nota existente")
    if note_path.exists() and policy == "update" and note_is_current(pdf, note_path):
        return ItemResult(str(pdf), str(note_path), "skipped", message="Nota atualizada")

    if options.dry_run:
        return ItemResult(str(pdf), str(note_path), "converted", message="dry-run")

    out_dir.mkdir(parents=True, exist_ok=True)

    import pymupdf
    with pymupdf.open(pdf) as doc:
        page_count = doc.page_count
    pages = list(options.pages) if options.pages is not None else list(range(page_count))

    batches = [pages[start:start + PAGE_BATCH] for start in range(0, len(pages), PAGE_BATCH)]
    rendered: dict[int, str] = {}
    library_messages: list[str] = []
    done = 0

    def collect(batch: list[int], result: tuple[list[tuple[int, str]], str]) -> None:
        nonlocal done
        rows, messages = result
        rendered.update(rows)
        if messages:
            library_messages.append(messages)
        done += len(batch)
        if progress:
            progress(done, len(pages))

    args = (str(pdf), not options.no_images, options.image_format, options.dpi, options.size_limit, options.image_text)
    if options.page_workers > 1 and len(batches) > 1:
        with ProcessPoolExecutor(max_workers=min(options.page_workers, len(batches))) as executor:
            futures = {executor.submit(render_pages, batch, *args): batch for batch in batches}
            for future in as_completed(futures):
                collect(futures[future], future.result())
    else:
        for batch in batches:
            collect(batch, render_pages(batch, *args))

    parts: list[str] = []
    images = 0
    for page in pages:
        text = clean_page(rendered[page])
        if not options.no_images:
            text, page_images = save_embedded_images(text, attach_dir, page + 1, options.image_format, options.wikilinks)
            images += page_images
        marker = options.page_separator or f"**Página {page + 1}**"
        parts.append(f"{marker}\n\n{text}" if text else marker)
    if library_messages:
        logger.debug("Mensagens da biblioteca: %s", "\n".join(library_messages))

    markdown = "\n\n".join(parts)
    if options.wikilinks:
        markdown = obsidian_links(markdown)

    title = markdown_title(markdown, pdf, options.title_from)
    sections: list[str] = []
    if options.frontmatter:
        sections.append(build_frontmatter(title, pdf, options))
    if options.source_link:
        sections.append(f"[Abrir PDF de origem]({pdf.as_uri()})\n")
    if options.copy_pdf:
        attach_dir.mkdir(parents=True, exist_ok=True)
        pdf_target = attach_dir / pdf.name
        shutil.copy2(pdf, pdf_target)
        if options.embed_pdf:
            sections.append(f"![[{pdf_target.name}]]\n")
    elif options.embed_pdf:
        sections.append(f"![[{pdf.name}]]\n")
    sections.append(markdown.lstrip())
    note_path.write_text("\n".join(sections), encoding="utf-8", newline="\n")
    logger.debug("Nota criada: %s", note_path)
    return ItemResult(str(pdf), str(note_path), "converted", images)


def convert_many(pdfs: list[Path], options: Options, logger: logging.Logger, progress: bool = False) -> Summary:
    summary = Summary()
    show = progress and options.workers == 1

    def run(pdf: Path) -> ItemResult:
        callback = None
        if show:
            def callback(done: int, total: int) -> None:
                draw_progress(pdf.name, done, total)
        try:
            return convert_one(pdf, options, logger, callback)
        except Exception as exc:
            logger.debug("Falha detalhada em %s", pdf, exc_info=True)
            return ItemResult(str(pdf), status="failed", message=str(exc))
        finally:
            if show:
                sys.stderr.write("\n")
                sys.stderr.flush()
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
