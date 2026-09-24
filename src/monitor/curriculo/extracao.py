from __future__ import annotations

import re

from pydantic import BaseModel, Field

from monitor.curriculo.normalizacao import Idioma, detectar_idioma, normalizar_texto
from monitor.curriculo.skills import DicionarioSkills

# a ordem entre os dois grupos importa: "Preferred qualifications" precisa cair
# em desejável antes que "qualifications" o jogue em obrigatório.
_MARCADORES_DESEJAVEL = (
    "diferenciais", "diferencial", "desejável", "desejáveis", "desejavel", "desejaveis",
    "nice to have", "nice-to-have", "bônus", "bonus", "preferred", "plus",
)
_MARCADORES_OBRIGATORIO = (
    "requisitos", "requirements", "qualifications", "obrigatórios", "obrigatorios",
    "pré-requisitos", "pre-requisitos", "must have", "must-have", "required",
    "o que esperamos", "o que buscamos", "what we expect", "you will need",
)

_SENIORIDADES = (
    ("estagio", ("estágio", "estagio", "intern", "internship")),
    ("junior", ("júnior", "junior", "jr")),
    ("pleno", ("pleno", "mid-level", "mid level", "midlevel")),
    ("senior", ("sênior", "senior", "sr")),
)

# Termos do dicionário que também são palavra corrente em pt/en. O critério
# NÃO é tamanho: "spark" tem 5 letras e mesmo assim "spark innovation" é
# inglês comum, não Apache Spark. Quem entra aqui só conta com corroboração
# (ver `_tem_corroboracao`). Ao adicionar uma skill nova que colida com
# linguagem corrente, acrescente o termo nesta lista.
_TERMOS_AMBIGUOS = frozenset(
    {"go", "ia", "ai", "spark", "lead", "scale", "plus", "r", "c", "d", "swift", "processing"}
)

# Frases que introduzem skill: corroboram um termo ambíguo mesmo em minúscula,
# porque ninguém escreve "experiência com go" falando do verbo.
_FRASES_DE_SKILL = (
    "experiência com", "experiencia com", "experiência em", "experiencia em",
    "conhecimento em", "conhecimento de", "conhecimentos em", "conhecimentos de",
    "domínio de", "dominio de", "vivência em", "vivencia em", "atuação com", "atuacao com",
    "experience with", "experience in", "knowledge of", "knowledge in",
    "proficiency in", "proficiency with", "familiarity with", "expertise in",
    "hands-on with", "worked with", "skills:", "stack:", "tech stack:",
    "tecnologias:", "technologies:",
)

# quanto do texto anterior ao termo é olhado em busca de uma dessas frases.
_JANELA_DE_CONTEXTO = 60

_NUNCA_CASA = re.compile(r"(?!)")


class RequisitosVaga(BaseModel):
    obrigatorios: list[str] = Field(default_factory=list)
    desejaveis: list[str] = Field(default_factory=list)
    senioridade: str | None = None
    idioma: Idioma = "pt"


def extrair_requisitos(texto_bruto: str, dicionario: DicionarioSkills) -> RequisitosVaga:
    """Lê a descrição de uma vaga e devolve os requisitos, sem IA."""
    texto = normalizar_texto(texto_bruto)
    regex = _regex_de_termos(dicionario)
    mapa = dicionario.termos()

    obrigatorios: list[str] = []
    desejaveis: list[str] = []
    # sem seção reconhecida, requisito encontrado é tratado como obrigatório.
    bloco = obrigatorios

    for linha in texto.splitlines():
        marcador = _marcador_de_secao(linha)
        if marcador == "desejavel":
            bloco = desejaveis
        elif marcador == "obrigatorio":
            bloco = obrigatorios

        for canonica in _skills_na_linha(linha, regex, mapa):
            if canonica not in bloco:
                bloco.append(canonica)

    return RequisitosVaga(
        obrigatorios=obrigatorios,
        # skill exigida que também aparece como diferencial continua exigida.
        desejaveis=[skill for skill in desejaveis if skill not in obrigatorios],
        senioridade=_detectar_senioridade(texto),
        idioma=detectar_idioma(texto),
    )


def _regex_de_termos(dicionario: DicionarioSkills) -> re.Pattern[str]:
    # do mais longo pro mais curto: numa alternância o `re` aceita a primeira
    # que casar, então "google cloud platform" precisa vir antes de "google cloud".
    termos = sorted(dicionario.termos(), key=len, reverse=True)
    if not termos:
        return _NUNCA_CASA
    alternativas = "|".join(re.escape(termo) for termo in termos)
    # lookaround em vez de \b: termos como "C++" e "Node.js" terminam em
    # caractere não-palavra, e aí o \b final nunca casaria.
    return re.compile(rf"(?<!\w)(?:{alternativas})(?!\w)", re.IGNORECASE)


def _skills_na_linha(linha: str, regex: re.Pattern[str], mapa: dict[str, str]) -> list[str]:
    encontradas: list[str] = []
    for achado in regex.finditer(linha):
        termo = achado.group(0)
        if termo.strip().lower() in _TERMOS_AMBIGUOS and not _tem_corroboracao(termo, linha, achado.start()):
            continue
        canonica = mapa.get(termo.strip().lower())
        if canonica:
            encontradas.append(canonica)
    return encontradas


def _tem_corroboracao(termo: str, linha: str, inicio: int) -> bool:
    """Um termo ambíguo só vira skill com evidência de que é o nome próprio.

    Duas evidências bastam, e qualquer uma resolve:
    1. grafia de nome/sigla — "Go", "IA", "Spark" (maiúscula ou dígito);
    2. uma frase que introduz skill logo antes — "experiência com go".
    """
    if any(caractere.isupper() or caractere.isdigit() for caractere in termo):
        return True
    anterior = linha[max(0, inicio - _JANELA_DE_CONTEXTO) : inicio].lower()
    return any(frase in anterior for frase in _FRASES_DE_SKILL)


def _marcador_de_secao(linha: str) -> str | None:
    inicio = linha.strip().lower()
    if not inicio:
        return None
    if any(inicio.startswith(marcador) for marcador in _MARCADORES_DESEJAVEL):
        return "desejavel"
    if any(inicio.startswith(marcador) for marcador in _MARCADORES_OBRIGATORIO):
        return "obrigatorio"
    return None


def _detectar_senioridade(texto: str) -> str | None:
    baixo = texto.lower()
    melhor: tuple[int, str] | None = None
    for rotulo, termos in _SENIORIDADES:
        for termo in termos:
            achado = re.search(rf"(?<!\w){re.escape(termo)}(?!\w)", baixo)
            # vale a que aparece primeiro: o nível costuma estar no título.
            if achado and (melhor is None or achado.start() < melhor[0]):
                melhor = (achado.start(), rotulo)
    return melhor[1] if melhor else None
