from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from monitor.curriculo.extracao import skills_no_texto
from monitor.curriculo.mestre import Bullet, CurriculoMestre
from monitor.curriculo.score import skills_canonicas_do_curriculo
from monitor.curriculo.skills import DicionarioSkills

_FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+")
_INICIAL_MAIUSCULA = re.compile(r"^[A-ZÀ-Þ][\wÀ-ÿ&+.-]*")
_NUMERO = re.compile(r"\d+(?:[.,]\d+)*%?")
_PALAVRA = re.compile(r"[\wÀ-ÿ]+")


class ContextoDoMestre(BaseModel):
    """Tudo que o currículo-mestre comprova — o universo do que pode ser dito."""

    ids_de_bullet: set[str]
    skills_canonicas: set[str]
    # nomes próprios legítimos (empresas, instituições, projetos, certificações,
    # tecnologias do dicionário), normalizados pra comparação.
    nomes_proprios: set[str]


def contexto_do_mestre(mestre: CurriculoMestre, dicionario: DicionarioSkills) -> ContextoDoMestre:
    skills = skills_canonicas_do_curriculo(mestre, dicionario)

    nomes: set[str] = set()
    nomes |= _tokens(mestre.dados.nome)
    for experiencia in mestre.experiencias:
        nomes |= _tokens(experiencia.empresa) | _tokens(experiencia.cargo)
    for projeto in mestre.projetos:
        nomes |= _tokens(projeto.nome)
        for tecnologia in projeto.stack:
            nomes |= _tokens(tecnologia)
    for formacao in mestre.formacao:
        nomes |= _tokens(formacao.instituicao) | _tokens(formacao.curso)
    for certificacao in mestre.certificacoes:
        nomes |= _tokens(certificacao.nome) | _tokens(certificacao.emissor or "")
    for idioma in mestre.idiomas:
        nomes |= _tokens(idioma.nome)
    for skill in mestre.skills:
        nomes |= _tokens(skill.nome)
    # sinônimos e grafias das skills QUE O MESTRE TEM — assim "Postgres" passa
    # se o currículo tem PostgreSQL. Liberar o dicionário inteiro aqui seria
    # um furo: "Google Cloud" é skill conhecida, e o token "google" acabaria
    # autorizando a empresa Google numa reescrita inventada.
    for termo, canonica in dicionario.termos().items():
        if canonica in skills:
            nomes |= _tokens(termo)

    return ContextoDoMestre(
        ids_de_bullet={bullet.id for bullet in mestre.todos_bullets()},
        skills_canonicas=skills,
        nomes_proprios=nomes,
    )


def validar_reescrita(
    bullet_id: str,
    texto_novo: str,
    original: Bullet | None,
    contexto: ContextoDoMestre,
    dicionario: DicionarioSkills,
) -> str | None:
    """Devolve o motivo da rejeição, ou None se a reescrita pode entrar.

    As quatro regras da spec (CURRICULO.md §6). Reprovou em qualquer uma, o
    bullet original é usado no lugar — a IA nunca consegue furar o "não
    inventar", mesmo que tente.
    """
    if bullet_id not in contexto.ids_de_bullet or original is None:
        return f"bullet '{bullet_id}' não corresponde a um bullet real do currículo-mestre"

    for skill in skills_no_texto(texto_novo, dicionario):
        if skill not in contexto.skills_canonicas:
            return f"cita '{skill}', que não está no currículo-mestre"

    do_original = _numeros(original.texto.pt or "") | _numeros(original.texto.en or "")
    for numero in sorted(_numeros(texto_novo)):
        if numero not in do_original:
            return f"usa a métrica '{numero}', que não existe no bullet original"

    permitidos = contexto.nomes_proprios | _tokens(original.texto.pt or "") | _tokens(
        original.texto.en or ""
    )
    for proprio in _nomes_proprios_do_texto(texto_novo):
        if _normalizar(proprio) not in permitidos:
            return f"menciona '{proprio}', que não aparece no currículo-mestre"

    return None


def _nomes_proprios_do_texto(texto: str) -> list[str]:
    suspeitos: list[str] = []
    for frase in _FIM_DE_FRASE.split(texto):
        palavras = frase.strip().split()
        # a primeira palavra da frase é maiúscula por pontuação, não por ser
        # nome próprio — reformular o verbo inicial é o que toda reescrita faz.
        for palavra in palavras[1:]:
            achado = _INICIAL_MAIUSCULA.match(palavra)
            if achado:
                suspeitos.append(achado.group(0).strip(".,;:!?"))
    return suspeitos


def _numeros(texto: str) -> set[str]:
    return {achado.group(0).rstrip("%").replace(",", ".") for achado in _NUMERO.finditer(texto)}


def _tokens(texto: str) -> set[str]:
    return {_normalizar(palavra) for palavra in _PALAVRA.findall(texto)}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.strip().lower()
