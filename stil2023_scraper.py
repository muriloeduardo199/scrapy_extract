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
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from langdetect import DetectorFactory, LangDetectException, detect
from pypdf import PdfReader
import spacy

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None


DBLP_TOC_URL = "https://dblp.org/db/conf/stil/stil2023.html"
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; STIL2023Scraper/1.0)"
TRANSLATION_MAX_CHARS = 4000
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF_SECONDS = 5

DetectorFactory.seed = 0

SPACY_MODEL_BY_LANGUAGE = {
    "Português": "pt_core_news_sm",
    "Inglês": "en_core_web_sm",
}
_NLP_CACHE: Dict[str, "spacy.language.Language"] = {}



@dataclass
class DblpEntry:
    """Representa um artigo encontrado na página índice do dblp."""

    title: str
    ee_url: Optional[str]
    details_url: Optional[str]
    authors: List[Dict[str, Optional[str]]]


translator = GoogleTranslator(source="en", target="pt")


def get_with_status(
    session: requests.Session,
    url: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    allow_redirects: bool = True,
    label: str = "recurso",
) -> requests.Response:
    """Faz a requisição HTTP e devolve uma mensagem clara quando o servidor falha."""

    last_error: Optional[Exception] = None
    for attempt in range(1, HTTP_RETRY_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=allow_redirects)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            resolved_url = getattr(getattr(exc, "response", None), "url", url)
            detail = f"Falha ao acessar {label}: status={status_code}, url={resolved_url}"
            last_error = requests.HTTPError(detail) if isinstance(exc, requests.HTTPError) else requests.RequestException(detail)
            if attempt == HTTP_RETRY_ATTEMPTS:
                break
            wait_seconds = HTTP_RETRY_BACKOFF_SECONDS * attempt
            print(f"{detail}. Nova tentativa em {wait_seconds}s ({attempt}/{HTTP_RETRY_ATTEMPTS}).")
            time.sleep(wait_seconds)
    raise last_error if last_error else RuntimeError(f"Falha inesperada ao acessar {label}: {url}")


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

    repaired = value.replace("ı", "i")
    targeted_patterns = (
        (r"c?\s*¸\s*˜\s*oes\b", "ções"),
        (r"c?\s*¸\s*˜\s*ao\b", "ção"),
        (r"˜\s*oes\b", "ões"),
        (r"˜\s*ao\b", "ão"),
    )
    for pattern, replacement in targeted_patterns:
        repaired = re.sub(pattern, replacement, repaired, flags=re.IGNORECASE)

    # Remove espaços espúrios quando o PDF separa a palavra do diacrítico solto.
    repaired = re.sub(r"(?<=[A-Za-z])\s+(?=[´`^ˆ˜~¨¸])", "", repaired)
    repaired = re.sub(r"(?<=[´`^ˆ˜~¨¸])\s+(?=[A-Za-z])", "", repaired)

    spacing_to_combining = {
        "´": "\u0301",
        "`": "\u0300",
        "^": "\u0302",
        "ˆ": "\u0302",
        "˜": "\u0303",
        "~": "\u0303",
        "¨": "\u0308",
        "¸": "\u0327",
    }

    def compose(base_char: str, mark_char: str) -> str:
        if mark_char == "¸" and base_char not in {"c", "C"}:
            return base_char + mark_char
        return unicodedata.normalize("NFC", base_char + spacing_to_combining[mark_char])

    def transfer_marks_from_accented_consonants(text: str) -> str:
        result = []
        index = 0
        while index < len(text):
            current = text[index]
            decomposed = unicodedata.normalize("NFD", current)
            base_char = decomposed[:1]
            marks = decomposed[1:]

            if marks and base_char.isalpha() and base_char.lower() not in "aeiou":
                next_index = index + 1
                if next_index < len(text) and text[next_index].isalpha() and text[next_index].lower() in "aeiou":
                    plain_current = unicodedata.normalize("NFC", base_char)
                    next_decomposed = unicodedata.normalize("NFD", text[next_index])
                    combined_next = unicodedata.normalize("NFC", next_decomposed[:1] + marks + next_decomposed[1:])
                    result.append(plain_current)
                    result.append(combined_next)
                    index += 2
                    continue
                result.append(unicodedata.normalize("NFC", base_char))
                index += 1
                continue

            result.append(current)
            index += 1

        return "".join(result)

    repaired = transfer_marks_from_accented_consonants(repaired)

    # Quando a marca fica entre duas letras, quase sempre ela pertence à vogal seguinte.
    repaired = re.sub(
        r"([A-Za-z])([´`^ˆ˜~¨])([AEIOUaeiou])",
        lambda match: match.group(1) + compose(match.group(3), match.group(2)),
        repaired,
    )
    repaired = re.sub(
        r"([cC])(¸)([A-Za-z])",
        lambda match: compose(match.group(1), match.group(2)) + match.group(3),
        repaired,
    )
    repaired = re.sub(
        r"([A-Za-z])([´`^ˆ˜~¨])([A-Za-z])",
        lambda match: match.group(1) + compose(match.group(3), match.group(2)),
        repaired,
    )
    repaired = re.sub(
        r"([A-Za-z])\s*([´`^ˆ˜~¨¸])",
        lambda match: compose(match.group(1), match.group(2)),
        repaired,
    )
    repaired = re.sub(
        r"([´`^ˆ˜~¨¸])\s*([A-Za-z])",
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

    normalized_code = normalize_key(code or "")
    if normalized_code in {"pt", "pt-br", "por", "portuguese", "portugues"}:
        return "Português"
    if normalized_code in {"en", "en-us", "en-gb", "eng", "english", "ingles"}:
        return "Inglês"

    normalized = normalize_key(fallback_title)
    padded = f" {normalized} "
    pt_markers = (
        " de ",
        " do ",
        " da ",
        " das ",
        " dos ",
        " em ",
        " para ",
        " sobre ",
        " uma ",
        " um ",
        " os ",
        " as ",
        " nao ",
        " linguagem ",
        " portugues ",
        " brasileiro ",
        " analise ",
        " avaliacao ",
        " estudo ",
    )
    en_markers = (
        " the ",
        " and ",
        " for ",
        " with ",
        " without ",
        " using ",
        " from ",
        " into ",
        " on ",
        " in ",
        " of ",
        " a ",
        " an ",
        " study ",
        " analysis ",
        " portuguese ",
        " brazilian ",
        " language ",
    )
    pt_score = sum(marker in padded for marker in pt_markers)
    en_score = sum(marker in padded for marker in en_markers)
    if pt_score > en_score:
        return "Português"
    return "Inglês"


def detect_language_label(title: str, abstract_text: str, code: Optional[str]) -> str:
    """Decide o idioma usando detector automático e metadados como fallback."""

    sample = normalize_whitespace(" ".join(part for part in (title, abstract_text) if part))
    if len(sample) >= 20:
        try:
            detected = detect(sample)
            if detected.startswith("pt"):
                return "Português"
            if detected.startswith("en"):
                return "Inglês"
        except LangDetectException:
            pass
    return infer_language_from_code(code, title)


def translate_long_text(text: str, max_chars: int = TRANSLATION_MAX_CHARS) -> str:
    """Traduz textos longos em blocos menores, preservando o original em caso de falha."""

    if not text:
        return ""
    if len(text) <= max_chars:
        try:
            return normalize_whitespace(translator.translate(text))
        except Exception:
            return text

    parts = []
    position = 0
    sentence_endings = (". ", "!\n", "?\n", ".\n", ";", ".\n\n")

    while position < len(text):
        end = min(position + max_chars, len(text))
        if end < len(text):
            best_end = position
            for marker in sentence_endings:
                last = text.rfind(marker, position, end)
                if last > best_end:
                    best_end = last + len(marker)
            if best_end > position:
                end = best_end

        part = text[position:end].strip()
        if part:
            try:
                parts.append(normalize_whitespace(translator.translate(part)))
            except Exception:
                parts.append(part)
        position = end

    return normalize_whitespace(" ".join(parts))


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


def get_spacy_pipeline(language_label: str):
    """Carrega e reutiliza o pipeline spaCy adequado para o idioma do artigo."""

    model_name = SPACY_MODEL_BY_LANGUAGE.get(language_label, SPACY_MODEL_BY_LANGUAGE["Inglês"])
    if model_name not in _NLP_CACHE:
        try:
            _NLP_CACHE[model_name] = spacy.load(model_name)
        except OSError as exc:
            raise RuntimeError(
                "Modelo spaCy ausente. Instale com "
                f"'python -m spacy download {model_name}' e execute novamente."
            ) from exc
    return _NLP_CACHE[model_name]


def tokenize_with_annotations(text: str, language_label: str) -> Dict[str, List[str]]:
    """Tokeniza o texto e produz POS tags e lemas usando spaCy."""

    if not text:
        return {
            "artigo_tokenizado": [],
            "pos_tagger": [],
            "lema": [],
        }

    doc = get_spacy_pipeline(language_label)(text)
    tokens = [token.text for token in doc]
    pos_tags = [token.pos_ or "X" for token in doc]
    lemmas = [
        normalize_key(token.lemma_) if token.lemma_ and token.lemma_ != "-PRON-" else normalize_key(token.text)
        for token in doc
    ]
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

    response = get_with_status(session, DBLP_TOC_URL, label="índice do dblp")
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

    response = get_with_status(session, entry.ee_url, label=f"página do artigo '{entry.title}'")
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
    language_label = detect_language_label(title, abstract_text, language_code)

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
        pdf_response = get_with_status(session, pdf_url, label=f"PDF do artigo '{title}'")

        # O JSON guarda a storage_key lógica, e o arquivo é salvo localmente com esse nome.
        pdf_path = download_dir / Path(storage_key).name
        pdf_path.write_bytes(pdf_response.content)
        article_text = extract_pdf_text(pdf_response.content)

    annotations = tokenize_with_annotations(article_text, language_label)
    title_pt = title
    abstract_text_pt = abstract_text
    article_text_pt = article_text
    translated_to_pt = False

    if language_label == "Inglês":
        print(f"Traduzindo conteúdo de: {title}")
        title_pt = translate_long_text(title)
        abstract_text_pt = translate_long_text(abstract_text)
        article_text_pt = translate_long_text(article_text)
        translated_to_pt = True

    return {
        "titulo": title,
        "titulo_pt": title_pt,
        "informacoes_url": article_url,
        "idioma": language_label,
        "idioma_original": language_label,
        "traduzido_para_pt": translated_to_pt,
        "storage_key": storage_key,
        "autores": authors,
        "data_publicacao": format_date((meta.get("citation_date") or [""])[0]),
        "resumo": abstract_text,
        "resumo_pt": abstract_text_pt,
        "keywords": keywords,
        "referencias": references,
        "artigo_completo": article_text,
        "artigo_completo_pt": article_text_pt,
        "artigo_tokenizado": annotations["artigo_tokenizado"],
        "pos_tagger": annotations["pos_tagger"],
        "lema": annotations["lema"],
    }


def build_dataset(
    output_path: Path,
    download_dir: Path,
    limit: Optional[int],
    prioritize_portuguese: bool,
) -> List[Dict[str, object]]:
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
        try:
            article = parse_article_page(
                session=session,
                entry=entry,
                storage_key=storage_key,
                download_dir=download_dir,
            )
        except Exception as exc:
            print(f"[{index}/{len(entries)}] falha em '{entry.title}': {exc}")
            output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Progresso parcial salvo em: {output_path}")
            continue
        dataset.append(article)
        output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{index}/{len(entries)}] extraido: {article['titulo']}")

    print(f"Arquivo gerado em: {output_path}")
    return dataset


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


