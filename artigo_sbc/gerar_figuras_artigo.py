import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ARTICLE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = ARTICLE_DIR / "resultados_dashboard"
FIGURES_DIR = ARTICLE_DIR / "figuras"
SUMMARY = ARTICLE_DIR / "resultados_calculados.json"


def main():
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    top_words = pd.read_csv(RESULTS_DIR / "top10_palavras.csv")
    results = json.loads(SUMMARY.read_text(encoding="utf-8"))

    plt.figure(figsize=(8, 4.2))
    bars = plt.bar(
        top_words["palavra"],
        top_words["frequencia"],
        color="#4f63d9",
    )
    plt.title("Dez palavras mais frequentes no corpus")
    plt.xlabel("Palavra")
    plt.ylabel("Frequência")
    plt.bar_label(bars, padding=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "top10_palavras.png", dpi=220)
    plt.close()

    labels = ["Bigramas", "Trigramas"]
    values = [
        results["perplexidade_bigramas"],
        results["perplexidade_trigramas"],
    ]
    plt.figure(figsize=(6, 4.2))
    bars = plt.bar(labels, values, color=["#2a9d8f", "#e76f51"])
    plt.title("Perplexidade dos modelos de n-gramas")
    plt.ylabel("Perplexidade")
    plt.bar_label(
        bars,
        labels=[f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") for value in values],
        padding=3,
    )
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "perplexidade_ngramas.png", dpi=220)
    plt.close()


if __name__ == "__main__":
    main()
