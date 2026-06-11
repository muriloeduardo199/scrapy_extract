import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import nbformat
import pandas as pd


ARTICLE_DIR = Path(__file__).resolve().parent
ROOT = ARTICLE_DIR.parent
INPUT_JSON = ARTICLE_DIR / "stil2023_articles.json"
EXECUTED_NOTEBOOK = ARTICLE_DIR / "stil2023_dashboard_executado.ipynb"
RESULTS_DIR = ARTICLE_DIR / "resultados_dashboard"
OUTPUT = ARTICLE_DIR / "resultados_calculados.json"


def cell_text(notebook, index):
    parts = []
    for output in notebook.cells[index].get("outputs", []):
        if "text" in output:
            parts.append("".join(output["text"]))
        plain = output.get("data", {}).get("text/plain")
        if plain:
            parts.append("".join(plain))
    return "\n".join(parts)


def number(text, label, decimal=False):
    pattern = rf"{re.escape(label)}:\s*([\d.]+)"
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"Resultado não encontrado: {label}")
    return float(match.group(1)) if decimal else int(match.group(1))


def records(path, limit=None):
    dataframe = pd.read_csv(path)
    if limit:
        dataframe = dataframe.head(limit)
    return dataframe.to_dict(orient="records")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    subprocess.run(
        [sys.executable, str(ARTICLE_DIR / "executar_dashboard_local.py")],
        cwd=ROOT,
        check=True,
    )

    notebook = nbformat.read(EXECUTED_NOTEBOOK, as_version=4)
    corpus_output = cell_text(notebook, 8)
    ngram_output = cell_text(notebook, 14)
    model_output = cell_text(notebook, 17)
    articles = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    article_stats = pd.read_csv(RESULTS_DIR / "estatisticas_por_artigo.csv")

    tokens = number(corpus_output, "Tokens")
    types = number(corpus_output, "Types")
    sentence_match = re.search(r"Senten.*?as:\s*(\d+)", corpus_output)
    if not sentence_match:
        raise ValueError("Resultado não encontrado: Sentenças")
    sentences = int(sentence_match.group(1))
    lemmas = number(corpus_output, "Lemmas")

    results = {
        "artigos": number(corpus_output, "Artigos carregados"),
        "idiomas": dict(Counter(str(item.get("idioma")) for item in articles)),
        "tokens": tokens,
        "types": types,
        "lemmas_distintos": lemmas,
        "sentencas": sentences,
        "media_tokens_artigo": round(article_stats["tokens"].mean(), 2),
        "media_sentencas_artigo": round(article_stats["sentencas"].mean(), 2),
        "min_tokens_artigo": int(article_stats["tokens"].min()),
        "max_tokens_artigo": int(article_stats["tokens"].max()),
        "min_sentencas_artigo": int(article_stats["sentencas"].min()),
        "max_sentencas_artigo": int(article_stats["sentencas"].max()),
        "diversidade_lexical": round(types / tokens, 4),
        "top_palavras": records(RESULTS_DIR / "top10_palavras.csv"),
        "top_pos": records(RESULTS_DIR / "classes_gramaticais.csv"),
        "tokens_modelo_linguagem": number(
            ngram_output, "Tokens usados no modelo"
        ),
        "unigramas_distintos": number(ngram_output, "Unigramas distintos"),
        "bigramas_distintos": number(ngram_output, "Bigramas distintos"),
        "trigramas_distintos": number(ngram_output, "Trigramas distintos"),
        "top_unigramas": records(
            RESULTS_DIR / "unigramas_top30.csv", limit=10
        ),
        "top_bigramas": records(
            RESULTS_DIR / "bigramas_top30.csv", limit=10
        ),
        "top_trigramas": records(
            RESULTS_DIR / "trigramas_top30.csv", limit=10
        ),
        "tokens_treino": number(model_output, "Tokens de treino"),
        "tokens_teste": number(model_output, "Tokens de teste"),
        "perplexidade_bigramas": number(
            model_output, "Perplexidade bigrama", decimal=True
        ),
        "perplexidade_trigramas": number(
            model_output, "Perplexidade trigrama", decimal=True
        ),
        "paragrafos_gerados": (
            RESULTS_DIR / "paragrafos_gerados_100_palavras.txt"
        ).read_text(encoding="utf-8"),
    }
    OUTPUT.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
