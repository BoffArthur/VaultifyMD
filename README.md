# VaultifyMD

Converte PDFs em Markdown pronto para Obsidian, com imagens, Wikilinks, frontmatter, processamento em lote e configuração TOML.

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
vaultifymd C:\PDFs -r --preserve-tree --skip-existing --workers 4
vaultifymd manual.pdf --pages "1-5,8" --frontmatter --tags "pdf,engenharia"
vaultifymd C:\PDFs -r --include "*manual*" --exclude "*/Archive/*" --dry-run
vaultifymd C:\PDFs -r --json --quiet > resultado.json
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
- Políticas seguras para existentes: erro, ignorar, sobrescrever, numerar ou hash
- Seleção de páginas; marcador de página `**Página N**` (ou `--page-separator`)
- Barra de progresso por página no terminal (desativada com `--quiet` ou fora de terminal)
- Extração opcional de imagens em PNG/JPG, gravadas em `--img-dir` (padrão: `<saída>/att/<nome do PDF>/`) com links `![[...]]` relativos ao Vault (ex.: `![[att/<nome do PDF>/<nome>-p<página>-<id>.png]]`) e nomes `<nome>-p<página>-<id>.png`, em que o id reinicia em cada página
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
