from pathlib import Path

import nbformat
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parent.parent
ARTICLE_DIR = ROOT / "artigo_sbc"
INPUT_NOTEBOOK = ROOT / "stil2023_dashboard_colab.ipynb"
INPUT_JSON = ARTICLE_DIR / "stil2023_articles.json"
OUTPUT_DIR = ARTICLE_DIR / "resultados_dashboard"
OUTPUT_NOTEBOOK = ARTICLE_DIR / "stil2023_dashboard_executado.ipynb"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    notebook = nbformat.read(INPUT_NOTEBOOK, as_version=4)

    # A instalação já foi feita no ambiente local.
    notebook.cells[1].source = "# Dependências instaladas no ambiente local."

    # Substitui somente o upload exclusivo do Google Colab.
    notebook.cells[3].source = (
        "from pathlib import Path\n"
        f"json_path = Path(r'{INPUT_JSON}')\n"
        "print(f'Arquivo carregado: {json_path}')\n"
    )

    client = NotebookClient(
        notebook,
        timeout=600,
        kernel_name="python3",
        resources={"metadata": {"path": str(OUTPUT_DIR)}},
        allow_errors=False,
    )
    client.execute()
    nbformat.write(notebook, OUTPUT_NOTEBOOK)
    print(f"Notebook executado: {OUTPUT_NOTEBOOK}")
    print(f"Resultados exportados: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
