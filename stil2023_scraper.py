"""
Scraper do STIL 2023.

Fluxo geral:
1. Lê a página índice do dblp para obter a lista de artigos.
2. Segue o link "view" de cada artigo para a página da SBC.
3. Extrai metadados da página do artigo.
4. Baixa o PDF, extrai o texto completo e gera anotações heurísticas.
5. Salva o resultado final em JSON.
"""

import argparse
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


DBLP_TOC_URL = "https://dblp.org/db/conf/stil/stil2023.html"
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; STIL2023Scraper/1.0)"

TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

STOPWORDS = {
    "en": {
        "the": "DET",
        "a": "DET",
        "an": "DET",
        "this": "DET",
        "that": "DET",
        "these": "DET",
        "those": "DET",
        "of": "ADP",
        "in": "ADP",
        "on": "ADP",
        "for": "ADP",
        "to": "PART",
        "and": "CCONJ",
        "or": "CCONJ",
        "but": "CCONJ",
        "with": "ADP",
        "without": "ADP",
        "by": "ADP",
        "from": "ADP",
        "is": "AUX",
        "are": "AUX",
        "was": "AUX",
        "were": "AUX",
        "be": "AUX",
        "been": "AUX",
        "being": "AUX",
        "it": "PRON",
        "its": "DET",
        "we": "PRON",
        "our": "DET",
        "they": "PRON",
        "their": "DET",
    },
    "pt": {
        "o": "DET",
        "a": "DET",
        "os": "DET",
        "as": "DET",
        "um": "DET",
        "uma": "DET",
        "uns": "DET",
        "umas": "DET",
        "de": "ADP",
        "do": "ADP",
        "da": "ADP",
        "dos": "ADP",
        "das": "ADP",
        "em": "ADP",
        "no": "ADP",
        "na": "ADP",
        "nos": "ADP",
        "nas": "ADP",
        "para": "ADP",
        "por": "ADP",
        "com": "ADP",
        "sem": "ADP",
        "e": "CCONJ",
        "ou": "CCONJ",
        "mas": "CCONJ",
        "é": "AUX",
        "são": "AUX",
        "foi": "AUX",
        "ser": "AUX",
        "se": "PRON",
        "que": "SCONJ",
        "eu": "PRON",
        "nós": "PRON",
        "eles": "PRON",
        "elas": "PRON",
    },
}


@dataclass
class DblpEntry:
    """Representa um artigo encontrado na página índice do dblp."""

    title: str
    ee_url: Optional[str]
    details_url: Optional[str]
    authors: List[Dict[str, Optional[str]]]


def normalize_whitespace(value: str) -> str:
    """Remove espaços duplicados e tenta corrigir texto com encoding quebrado."""

    return re.sub(r"\s+", " ", repair_broken_diacritics(fix_mojibake(value or ""))).strip()


def fix_mojibake(value: str) -> str:
    """Corrige casos comuns de mojibake causados por decodificação incorreta."""

    if not value:
        return value

    suspicious = ("Ã", "Â", "â", "Ë", "Ê", "´", "€", "™")
    if not any(char in value for char in suspicious):
        return value

    try:
        repaired = value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value

    original_hits = sum(value.count(char) for char in suspicious)
    repaired_hits = sum(repaired.count(char) for char in suspicious)
    return repaired if repaired_hits < original_hits else value


def repair_broken_diacritics(value: str) -> str:
    """Recompõe acentos quebrados quando o PDF extrai diacríticos soltos."""

    if not value:
        return value

    repaired = value
    targeted_patterns = (
        (r"c?\s*¸\s*˜\s*oes\b", "ções"),
        (r"c?\s*¸\s*˜\s*ao\b", "ção"),
        (r"˜\s*oes\b", "ões"),
        (r"˜\s*ao\b", "ão"),
    )
    for pattern, replacement in targeted_patterns:
        repaired = re.sub(pattern, replacement, repaired, flags=re.IGNORECASE)

    # Remove espaços espúrios quando o PDF separa a palavra do diacrítico solto.
    repaired = re.sub(r"(?<=[A-Za-z])\s+(?=[´`^˜~¨¸])", "", repaired)
    repaired = re.sub(r"(?<=[´`^˜~¨¸])\s+(?=[A-Za-z])", "", repaired)

    spacing_to_combining = {
        "´": "\u0301",
        "`": "\u0300",
        "^": "\u0302",
        "˜": "\u0303",
        "~": "\u0303",
        "¨": "\u0308",
        "¸": "\u0327",
    }

    def compose(base_char: str, mark_char: str) -> str:
        if mark_char == "¸" and base_char not in {"c", "C"}:
            return base_char + mark_char
        return unicodedata.normalize("NFC", base_char + spacing_to_combining[mark_char])

    repaired = re.sub(
        r"([A-Za-z])\s*([´`^˜~¨¸])",
        lambda match: compose(match.group(1), match.group(2)),
        repaired,
    )
    repaired = re.sub(
        r"([´`^˜~¨¸])\s*([A-Za-z])",
        lambda match: compose(match.group(2), match.group(1)),
        repaired,
    )
    return repaired


def normalize_key(value: str) -> str:
    """Normaliza texto para comparação estável entre nomes e chaves."""

    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalize_whitespace(ascii_only).casefold()


def infer_language_from_code(code: Optional[str], fallback_title: str) -> str:
    """Converte o código de idioma para o rótulo esperado no JSON."""

    if code == "pt":
        return "Português"
    if code == "en":
        return "Inglês"

    normalized = normalize_key(fallback_title)
    pt_markers = (" de ", " do ", " da ", " em ", " para ", " portugues", " analise ")
    return "Português" if any(marker in f" {normalized} " for marker in pt_markers) else "Inglês"


def likely_portuguese_title(title: str) -> bool:
    """Indica se o título parece estar em português com base em heurísticas leves."""

    return infer_language_from_code(code=None, fallback_title=title) == "Português"


def format_date(date_value: Optional[str]) -> str:
    """Converte datas para o formato dd/mm/aaaa quando possível."""

    if not date_value:
        return ""
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return date_value


def split_references(ref_block: Optional[BeautifulSoup]) -> List[str]:
    """Separa o bloco HTML de referências em uma lista de strings."""

    if ref_block is None:
        return []
    html_content = ref_block.decode_contents()
    parts = re.split(r"<br\s*/?>\s*<br\s*/?>", html_content, flags=re.IGNORECASE)
    references = []
    for part in parts:
        text = normalize_whitespace(BeautifulSoup(part, "html.parser").get_text(" ", strip=True))
        if text:
            references.append(text)
    return references


def extract_pdf_text(content: bytes) -> str:
    """Extrai texto do PDF, com fallback para PyMuPDF quando necessário."""

    primary_text = extract_pdf_text_with_pypdf(content)
    if primary_text and not text_looks_corrupted(primary_text):
        return primary_text

    fallback_text = extract_pdf_text_with_pymupdf(content)
    if not fallback_text:
        return primary_text
    if not primary_text:
        return fallback_text
    return fallback_text if score_text_quality(fallback_text) >= score_text_quality(primary_text) else primary_text


def extract_pdf_text_with_pypdf(content: bytes) -> str:
    """Extrai e concatena o texto de todas as páginas usando pypdf."""

    reader = PdfReader(BytesIO(content))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text:
            pages.append(text)
    return normalize_whitespace("\n".join(pages))


def extract_pdf_text_with_pymupdf(content: bytes) -> str:
    """Extrai e concatena o texto de todas as páginas usando PyMuPDF."""

    if fitz is None:
        return ""

    document = fitz.open(stream=content, filetype="pdf")
    try:
        pages = []
        for page in document:
            text = page.get_text("text") or ""
            if text:
                pages.append(text)
        return normalize_whitespace("\n".join(pages))
    finally:
        document.close()


def score_text_quality(text: str) -> float:
    """Pontua a qualidade do texto extraído penalizando artefatos comuns."""

    if not text:
        return float("-inf")

    length = max(len(text), 1)
    penalties = 0
    penalties += text.count("?") * 3
    penalties += len(re.findall(r"\b\w\s+[áàâãéêíóôõúç]\b", text, flags=re.IGNORECASE)) * 4
    penalties += len(re.findall(r"[áàâãéêíóôõúç]\s+\w", text, flags=re.IGNORECASE)) * 2
    penalties += len(re.findall(r"\b\w+\s*,\s*[a-záàâãéêíóôõúç]+\b", text, flags=re.IGNORECASE)) * 2
    penalties += len(re.findall(r"[^\w\s]{2,}", text))
    return len(re.findall(r"\w", text, flags=re.UNICODE)) / length - (penalties / length)


def text_looks_corrupted(text: str) -> bool:
    """Sinaliza texto com indícios fortes de extração ruim."""

    return score_text_quality(text) < 0.55


def heuristic_pos(token: str, language_code: str) -> str:
    """Atribui uma POS tag simples usando regras heurísticas."""

    lowered = token.casefold()
    if re.fullmatch(r"\d+(?:[.,]\d+)*", token):
        return "NUM"
    if re.fullmatch(r"[^\w\s]", token):
        return "PUNCT"
    if lowered in STOPWORDS.get(language_code, {}):
        return STOPWORDS[language_code][lowered]
    if token[:1].isupper():
        return "PROPN"
    if lowered.endswith(("mente", "ly")):
        return "ADV"
    if lowered.endswith(("ar", "er", "ir", "ing", "ed")):
        return "VERB"
    if lowered.endswith(("al", "vel", "ivo", "iva", "ous", "ful", "able", "ible")):
        return "ADJ"
    return "NOUN"


def heuristic_lemma(token: str) -> str:
    """Gera um lema simplificado por normalização do token."""

    if re.fullmatch(r"[^\w\s]", token):
        return token
    return normalize_key(token)


def tokenize_with_annotations(text: str, language_label: str) -> Dict[str, List[str]]:
    """Tokeniza o texto e produz POS tags e lemas heurísticos."""

    language_code = "pt" if language_label == "Português" else "en"
    tokens = TOKEN_PATTERN.findall(text)
    pos_tags = [heuristic_pos(token, language_code) for token in tokens]
    lemmas = [heuristic_lemma(token) for token in tokens]
    return {
        "artigo_tokenizado": tokens,
        "pos_tagger": pos_tags,
        "lema": lemmas,
    }


def parse_dblp_toc(session: requests.Session) -> List[DblpEntry]:
    """
    Lê a página do dblp e extrai apenas os artigos do evento.

    O dblp é usado como índice: ele fornece título, autores básicos,
    ORCID em alguns casos e, principalmente, o link "view" que aponta
    para a página da SBC.
    """

    response = session.get(DBLP_TOC_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    entries = []

    for item in soup.select("li.entry.inproceedings"):
        title_node = item.select_one("cite span.title")
        if title_node is None:
            continue

        # O link "ee" é o mesmo aberto ao clicar em "view".
        ee_link = item.select_one("li.ee a[itemprop='url']")
        details_link = item.select_one("li.details a")
        authors = []

        for author_node in item.select("cite span[itemprop='author']"):
            name_node = author_node.select_one("span[itemprop='name']")
            if name_node is None:
                continue
            orcid_node = author_node.select_one("img[title]")
            authors.append(
                {
                    "nome": normalize_whitespace(name_node.get_text(" ", strip=True)),
                    "afiliacao": "",
                    "orcid": (
                        f"http://orcid.org/{orcid_node.get('title')}"
                        if orcid_node and orcid_node.get("title")
                        else ""
                    ),
                }
            )

        entries.append(
            DblpEntry(
                title=normalize_whitespace(title_node.get_text(" ", strip=True)).rstrip("."),
                ee_url=ee_link.get("href") if ee_link else None,
                details_url=urljoin("https://dblp.org/", details_link.get("href")) if details_link else None,
                authors=authors,
            )
        )
    return entries


def parse_article_page(
    session: requests.Session,
    entry: DblpEntry,
    storage_key: str,
    download_dir: Path,
) -> Dict[str, object]:
    """
    Extrai os dados completos de um artigo a partir da página da SBC.

    Também baixa o PDF correspondente e gera:
    - artigo_completo
    - artigo_tokenizado
    - pos_tagger
    - lema
    """

    if not entry.ee_url:
        raise ValueError(f"Entrada sem link eletrônico: {entry.title}")

    response = session.get(entry.ee_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")

    article_url = response.url

    # As meta tags da página da SBC concentram boa parte dos metadados estruturados.
    meta = {}
    for node in soup.select("meta[name], meta[property]"):
        key = node.get("name") or node.get("property")
        content = node.get("content", "")
        if key:
            meta.setdefault(key, []).append(content)

    title = normalize_whitespace((meta.get("citation_title") or [entry.title])[0]).rstrip(".")
    language_code = (meta.get("DC.Language") or [""])[0].strip().lower()
    language_label = infer_language_from_code(language_code, title)

    # Os autores visíveis na página costumam ter afiliação e, às vezes, ORCID.
    authors = []
    for index, author_node in enumerate(soup.select("ul.item.authors > li")):
        name = normalize_whitespace(author_node.select_one("span.name").get_text(" ", strip=True))
        affiliation_node = author_node.select_one("span.affiliation")
        orcid_node = author_node.select_one("span.orcid a")
        authors.append(
            {
                "nome": name,
                "afiliacao": normalize_whitespace(affiliation_node.get_text(" ", strip=True)) if affiliation_node else "",
                "orcid": orcid_node.get("href", "") if orcid_node else "",
            }
        )

    if not authors:
        authors = entry.authors

    # Se o ORCID não vier da página da SBC, tenta reaproveitar o que veio do dblp.
    dblp_orcid_by_name = {normalize_key(author["nome"]): author["orcid"] for author in entry.authors}
    for author in authors:
        if not author["orcid"]:
            author["orcid"] = dblp_orcid_by_name.get(normalize_key(author["nome"]), "")

    # Resumo, palavras-chave e referências vêm do HTML principal da página.
    abstract_node = soup.select_one("div.item.abstract")
    abstract_text = ""
    if abstract_node is not None:
        label = abstract_node.select_one(".label")
        if label:
            label.extract()
        abstract_text = normalize_whitespace(abstract_node.get_text(" ", strip=True))
    if not abstract_text:
        abstract_text = normalize_whitespace((meta.get("DC.Description") or [""])[0])

    keywords_node = soup.select_one("div.item.keywords span.value")
    keywords = []
    if keywords_node is not None:
        keywords = [normalize_whitespace(keyword) for keyword in keywords_node.get_text(" ", strip=True).split(",")]
        keywords = [keyword for keyword in keywords if keyword]

    references_node = soup.select_one("div.item.references div.value")
    references = split_references(references_node)

    pdf_url = (meta.get("citation_pdf_url") or [""])[0]
    article_text = ""
    if pdf_url:
        pdf_response = session.get(pdf_url, timeout=REQUEST_TIMEOUT)
        pdf_response.raise_for_status()

        # O JSON guarda a storage_key lógica, e o arquivo é salvo localmente com esse nome.
        pdf_path = download_dir / Path(storage_key).name
        pdf_path.write_bytes(pdf_response.content)
        article_text = extract_pdf_text(pdf_response.content)

    annotations = tokenize_with_annotations(article_text, language_label)

    return {
        "titulo": title,
        "informacoes_url": article_url,
        "idioma": language_label,
        "storage_key": storage_key,
        "autores": authors,
        "data_publicacao": format_date((meta.get("citation_date") or [""])[0]),
        "resumo": abstract_text,
        "keywords": keywords,
        "referencias": references,
        "artigo_completo": article_text,
        "artigo_tokenizado": annotations["artigo_tokenizado"],
        "pos_tagger": annotations["pos_tagger"],
        "lema": annotations["lema"],
    }


def build_dataset(
    output_path: Path,
    download_dir: Path,
    limit: Optional[int],
    prioritize_portuguese: bool,
) -> None:
    """
    Coordena a extração completa e grava o dataset final em disco.

    Parâmetros:
    - output_path: caminho do JSON de saída
    - download_dir: diretório dos PDFs
    - limit: quantidade máxima de artigos a processar
    - prioritize_portuguese: processa primeiro títulos que parecem estar em português
    """

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Cria automaticamente os diretórios de saída, se necessário.
    download_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    entries = parse_dblp_toc(session)
    if prioritize_portuguese:
        entries = sorted(entries, key=lambda entry: (not likely_portuguese_title(entry.title), entry.title.casefold()))
    if limit is not None:
        entries = entries[:limit]

    dataset = []
    for index, entry in enumerate(entries, start=1):
        # Define a chave/caminho lógico esperado para cada PDF.
        storage_key = f"files/article_{index:03d}.pdf"
        article = parse_article_page(
            session=session,
            entry=entry,
            storage_key=storage_key,
            download_dir=download_dir,
        )
        dataset.append(article)
        print(f"[{index}/{len(entries)}] extraido: {article['titulo']}")

    output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Arquivo gerado em: {output_path}")


def main() -> None:
    """Ponto de entrada da linha de comando."""

    parser = argparse.ArgumentParser(description="Extrai os artigos do STIL 2023 em JSON.")
    parser.add_argument(
        "--output",
        default="output/stil2023_articles.json",
        help="Caminho do JSON de saída.",
    )
    parser.add_argument(
        "--download-dir",
        default="files",
        help="Diretório onde os PDFs serão salvos.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita a quantidade de artigos processados.",
    )
    parser.add_argument(
        "--prioritize-portuguese",
        action="store_true",
        help="Processa primeiro artigos cujo título parece estar em português.",
    )
    args = parser.parse_args()

    build_dataset(
        output_path=Path(args.output),
        download_dir=Path(args.download_dir),
        limit=args.limit,
        prioritize_portuguese=args.prioritize_portuguese,
    )


if __name__ == "__main__":
    main()
