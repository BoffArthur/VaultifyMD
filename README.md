# VaultifyMD

Converte PDFs em Markdown pronto para Obsidian, com imagens, Wikilinks, frontmatter, processamento em lote e configuração TOML.

## Versão 0.4.1

- Nova opção `--image-text` (`image_text = true` no TOML): inclui o texto de dentro de figuras e diagramas no Markdown, como os blocos `picture text`. Desligada por padrão, porque esse texto pode sair fora de ordem em diagramas com cotas. O texto vem do próprio PDF (não é OCR); sem a opção, ele é omitido.

## Versão 0.4.0

- Nova opção `--update`: consulta a última release publicada no GitHub e instala com `pip` somente se for mais nova que a versão instalada. Requer que a release exista (tag `vX.Y.Z`).

## Versão 0.3.0

- Flags booleanas com `--X/--no-X` (`--images`, `--wikilinks`, etc.) substituem `--no-images` e a configuração `no_images` (agora `images = true` no TOML; `no_images` ainda é lido).
- `--collision` aceita `update`: regenera a nota somente se o PDF for mais novo que a nota (`source_modified` do frontmatter, ou mtime da nota quando não há frontmatter).
- `--collision`, `--overwrite` e `--skip-existing` são mutuamente exclusivos; `--overwrite` e `--skip-existing` são aliases ocultos mantidos por compatibilidade. A configuração `overwrite`/`skip_existing` ainda é lida como fallback.

## Versão 0.2.2

- Anexos em `<saída>/<nome do arquivo>/` e wikilinks `![[<nome do arquivo>/<imagem>]]`, com o Markdown direto na saída.
- Política de colisão reduzida a `skip` (padrão), `overwrite` e `duplicate`; a pasta de anexos acompanha o nome final da nota.

## Versão 0.2.1

Correção: a CLI não iniciava no Python 3.14 por causa de `--no-images` e `--no-wikilinks`.

## Versão 0.2.0

Renomeado de `pdf2obsidian-cli` para `vaultifymd` e ampliado para uso diário e automações.

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ".[dev]"
```

Ou como CLI isolada:

```powershell
pipx install .
```

As versões testadas do runtime estão em `requirements.txt`; as dependências declaradas em `pyproject.toml` são `pymupdf>=2.1` e `pymupdf4llm>=2.1`.

## Exemplos

```powershell
vaultifymd manual.pdf
vaultifymd C:\PDFs --recursive --vault D:\Obsidian --output "Notas/PDF"
vaultifymd C:\PDFs -r --preserve-tree --collision skip --workers 4
vaultifymd manual.pdf --pages "1-5,8" --frontmatter --tags "pdf,engenharia"
vaultifymd C:\PDFs -r --include "*manual*" --exclude "*/Archive/*" --dry-run
vaultifymd C:\PDFs -r --json --quiet > resultado.json
vaultifymd --update
```

## Configuração persistente

```powershell
vaultifymd --init-config
vaultifymd C:\PDFs
```

A CLI carrega automaticamente `vaultifymd.toml` no diretório atual. Argumentos da linha de comando prevalecem sobre o TOML.

## Qualidade de vida incluída

- Arquivo TOML persistente e gerador `--init-config`
- Múltiplos arquivos, pastas, recursão e filtros `--include`/`--exclude`
- Preservação opcional da árvore de pastas
- Política para notas existentes (`--collision`): ignorar (padrão), sobrescrever, duplicar com sufixo numérico (`-2`, `-3`...) ou atualizar somente se o PDF for mais novo (`update`); a pasta de anexos acompanha o nome final da nota
- Extração de imagens ligada por padrão; desative com `--no-images`
- Seleção de páginas; marcador de página `**Página N**` (ou `--page-separator`)
- Barra de progresso por página no terminal (desativada com `--quiet` ou fora de terminal)
- Extração opcional de imagens em PNG/JPG, gravadas em `--img-dir` (padrão: `<saída>/<nome do PDF>/`) com links `![[<nome do PDF>/<nome>-p<página>-<id>.png]]` e nomes `<nome>-p<página>-<id>.png`, em que o id reinicia em cada página
- Wikilinks ou links Markdown
- Título por nome, metadados do PDF ou primeiro heading
- Frontmatter, tags e propriedades personalizadas
- Cópia, incorporação e link para o PDF original
- Processamento paralelo de 1 a 32 workers
- Processamento paralelo de páginas dentro de cada PDF com `--page-workers` (1 a 16, padrão 4), dividindo as páginas em lotes de 10
- `--dry-run`, modo silencioso, verbose, log e resumo JSON
- Validação para impedir escrita fora do Vault
- Nomes compatíveis com Windows
- Códigos de saída: 0 sucesso, 1 falha de conversão, 2 erro de argumentos

## Testes

```powershell
pytest -q
ruff check .
```
