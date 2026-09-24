from __future__ import annotations

import html
import re
from typing import Literal

Idioma = Literal["pt", "en"]

# sem sinal de idioma nenhum não há o que decidir; fixar o padrão mantém a
# saída reproduzível (requisito de determinismo da feature).
IDIOMA_PADRAO: Idioma = "pt"

# tags de bloco viram quebra de linha em vez de sumir: "<li>Python</li><li>SQL</li>"
# colapsaria em "PythonSQL" e a extração perderia a separação por linha, que é
# o que distingue "Requisitos" de "Diferenciais".
_TAGS_DE_BLOCO = re.compile(
    r"</?(?:p|div|br|li|ul|ol|tr|td|h[1-6]|section|article|blockquote)\b[^>]*>",
    re.IGNORECASE,
)
_QUALQUER_TAG = re.compile(r"<[^>]+>")

_MD_CERCA = re.compile(r"^\s*```.*$", re.MULTILINE)
_MD_TITULO = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_CITACAO = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MD_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# só `*` e crase: `_` apareceria dentro de nomes técnicos (node_modules) e o
# ganho de tratar itálico com underscore não paga o estrago.
_MD_ENFASE = re.compile(r"\*{1,3}|`+")

_ESPACO_HORIZONTAL = re.compile(r"[ \t ]+")
_LINHAS_EM_BRANCO = re.compile(r"\n{3,}")

_PALAVRAS = re.compile(r"[a-zà-ÿ]+")

# stopwords escolhidas por serem frequentes E exclusivas de um idioma. Ficaram
# de fora as que existem nos dois ("a", "as", "no") e "com", que casaria com
# qualquer ".com" de URL.
_STOPWORDS_PT = frozenset(
    {
        "de", "da", "do", "dos", "das", "em", "para", "que", "uma", "um",
        "não", "nao", "você", "voce", "sua", "seu", "por", "ao", "os", "e", "ou",
    }
)
_STOPWORDS_EN = frozenset(
    {
        "the", "and", "of", "to", "in", "for", "with", "you", "your", "our",
        "we", "are", "is", "will", "have", "on", "at", "this", "be",
    }
)


def normalizar_texto(bruto: str) -> str:
    """HTML/Markdown da descrição de uma vaga -> texto limpo, linha a linha."""
    if not bruto:
        return ""

    # primeiro unescape: o Greenhouse entrega HTML escapado (&lt;p&gt;).
    texto = html.unescape(bruto)
    texto = _TAGS_DE_BLOCO.sub("\n", texto)
    texto = _QUALQUER_TAG.sub("", texto)
    # segundo unescape: entidades que estavam no conteúdo, não na marcação.
    texto = html.unescape(texto)

    texto = _MD_CERCA.sub("", texto)
    texto = _MD_TITULO.sub("", texto)
    texto = _MD_CITACAO.sub("", texto)
    texto = _MD_ITEM.sub("", texto)
    texto = _MD_LINK.sub(r"\1", texto)
    texto = _MD_ENFASE.sub("", texto)

    texto = _ESPACO_HORIZONTAL.sub(" ", texto)
    texto = "\n".join(linha.strip() for linha in texto.splitlines())
    return _LINHAS_EM_BRANCO.sub("\n\n", texto).strip()


def detectar_idioma(texto: str) -> Idioma:
    """Heurística de stopwords, de propósito.

    `langdetect` é não-determinístico por padrão — a mesma entrada pode dar
    saídas diferentes entre execuções, o que deixaria os testes instáveis e
    o currículo gerado imprevisível.
    """
    palavras = _PALAVRAS.findall(texto.lower())
    pt = sum(1 for palavra in palavras if palavra in _STOPWORDS_PT)
    en = sum(1 for palavra in palavras if palavra in _STOPWORDS_EN)

    if en > pt:
        return "en"
    if pt > en:
        return "pt"
    return IDIOMA_PADRAO
