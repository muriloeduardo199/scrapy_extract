# STIL 2023 Scraper e Dashboard

Este projeto extrai artigos do **STIL 2023** a partir da página do `dblp`, segue o link `view` de cada item até a página da **SBC**, baixa os PDFs e gera um arquivo JSON estruturado com metadados e conteúdo textual.

Além do scraper, o projeto também inclui notebooks para uso no **Google Colab**:
- um notebook para executar a coleta
- um notebook para gerar estatísticas e dashboard do corpus

## Arquivos

- [stil2023_scraper.py](d:\scrapy_article\stil2023_scraper.py): scraper principal em Python
- [requirements.txt](d:\scrapy_article\requirements.txt): dependências do projeto
- [stil2023_scraper_colab.ipynb](d:\scrapy_article\stil2023_scraper_colab.ipynb): notebook do Colab para executar o scraper
- [stil2023_dashboard_colab.ipynb](d:\scrapy_article\stil2023_dashboard_colab.ipynb): notebook do Colab para análise do corpus
- [output/stil2023_articles.json](d:\scrapy_article\output\stil2023_articles.json): JSON gerado pela extração
- [files](d:\scrapy_article\files): PDFs baixados

## O que o scraper extrai

Para cada artigo, o JSON contém:

- `titulo`
- `informacoes_url`
- `idioma`
- `storage_key`
- `autores`
- `data_publicacao`
- `resumo`
- `keywords`
- `referencias`
- `artigo_completo`
- `artigo_tokenizado`
- `pos_tagger`
- `lema`

## Fonte dos dados

O fluxo de extração é:

1. Página índice do evento no `dblp`
   - URL: `https://dblp.org/db/conf/stil/stil2023.html`
2. Link `view` de cada artigo
   - redireciona para a página da **SBC**
3. Página da SBC
   - fornece metadados como resumo, autores, afiliação, data, palavras-chave e referências
4. PDF do artigo
   - fornece o texto completo usado em `artigo_completo`, tokenização, POS e lema

## Instalação local

Use Python 3.10+.

```bash
pip install -r requirements.txt
```

## Como executar localmente

Executar todos os artigos:

```bash
python stil2023_scraper.py
```

Executar apenas 30 artigos:

```bash
python stil2023_scraper.py --limit 30
```

Executar teste com apenas 1 artigo:

```bash
python stil2023_scraper.py --limit 1
```

## Saídas geradas

O script cria automaticamente as pastas, se elas não existirem:

- `files/`: armazena os PDFs baixados
- `output/`: armazena o JSON final

Por padrão:

- JSON: `output/stil2023_articles.json`
- PDFs: `files/article_001.pdf`, `files/article_002.pdf`, ...

## Parâmetros disponíveis

O script aceita:

- `--output`: caminho do JSON de saída
- `--download-dir`: diretório onde os PDFs serão salvos
- `--limit`: quantidade máxima de artigos processados

Exemplo:

```bash
python stil2023_scraper.py --limit 30 --output output/meu_dataset.json --download-dir files
```

## Como usar no Colab

### Notebook do scraper

Abra [stil2023_scraper_colab.ipynb](d:\scrapy_article\stil2023_scraper_colab.ipynb) no Google Colab e execute as células em ordem.

O notebook:

- instala as dependências
- define as funções do scraper
- executa a coleta
- mostra um item de exemplo
- permite baixar o JSON final

Para limitar a coleta a 30 artigos, ajuste:

```python
limit=30
```

### Notebook do dashboard

Abra [stil2023_dashboard_colab.ipynb](d:\scrapy_article\stil2023_dashboard_colab.ipynb) no Google Colab.

O notebook:

- recebe o upload do arquivo `stil2023_articles.json`
- agrega o corpus
- calcula estatísticas
- mostra tabelas e gráficos
- gera nuvem de palavras

## Estatísticas do dashboard

O dashboard calcula:

- quantidade de tokens
- quantidade de types
- quantidade de sentenças
- quantidade por classe gramatical
- quantidade de lemmas
- top 10 palavras do corpus
- distribuição de tokens por artigo
- nuvem de palavras

Observação:

- as **stopwords não são removidas**
- a contagem de palavras desconsidera apenas pontuação isolada

## Estrutura do código

Funções principais do scraper:

- `parse_dblp_toc()`: lê a página do `dblp` e monta a lista de artigos
- `parse_article_page()`: entra na página da SBC, extrai os metadados e baixa o PDF
- `build_dataset()`: coordena o processo completo e grava o JSON

Funções auxiliares:

- `fix_mojibake()`: corrige problemas comuns de encoding
- `normalize_whitespace()`: limpa espaços duplicados
- `normalize_key()`: normaliza texto para comparação
- `format_date()`: padroniza datas
- `split_references()`: separa referências
- `extract_pdf_text()`: extrai texto do PDF
- `tokenize_with_annotations()`: gera tokens, POS e lema

## Limitações atuais

- `pos_tagger` e `lema` usam abordagem **heurística**, não um modelo linguístico avançado
- a contagem de sentenças no dashboard usa uma segmentação simples por pontuação
- a qualidade do texto extraído depende da qualidade do PDF

## Próximos ajustes possíveis

- substituir POS e lema heurísticos por `spaCy` ou `stanza`
- adicionar filtros interativos ao dashboard
- exportar gráficos automaticamente
- salvar estatísticas em CSV ou Excel

