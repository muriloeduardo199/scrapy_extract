# Artigo SBC

Arquivos preparados para importar no Overleaf:

- `main.tex`: artigo principal.
- `referencias.bib`: referências bibliográficas.
- `calcular_resultados.py`: reprodução das métricas do corpus.
- `resultados_calculados.json`: valores usados nas tabelas e discussão.

## Uso no Overleaf

1. Abra o template `Instructions for Authors of SBC Book Chapters`.
2. Crie um projeto a partir do template.
3. Substitua o arquivo principal pelo conteúdo de `main.tex`.
4. Envie `referencias.bib`.
5. Mantenha os arquivos `sbc-template.sty` e `sbc.bst` fornecidos pelo template.
6. Atualize instituição, cidade, estado e e-mails no bloco `\address`.
7. Compile com pdfLaTeX.
8. Compartilhe o projeto com permissão de leitura ou edição e envie o PDF.

O template informa que artigos em português devem conter `abstract` e
`resumo`, ambos com no máximo dez linhas e na primeira página.

## Resultados ainda recomendados

Os notebooks não possuem saídas executadas salvas. Antes da versão final,
execute os notebooks de embeddings no Colab e acrescente uma tabela com:

- palavra consultada;
- cinco vizinhos de Word2Vec, FastText e GloVe;
- cinco vizinhos do modelo pré-treinado;
- cobertura de cada modelo para os termos avaliados.

Não apresente esses exemplos como uma avaliação quantitativa geral. Para isso,
seria necessário um conjunto de referência de similaridade ou analogias.
