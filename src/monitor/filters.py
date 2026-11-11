from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from monitor.config import FiltrosConfig
from monitor.curriculo.normalizacao import normalizar_texto
from monitor.models import Vaga

# Os repositórios de vagas do GitHub (e boa parte da Adzuna) não têm campo de
# remoto: quem diz é o título, "[Remoto] Dev Python". Sem olhar o título,
# essas vagas caíam na regra de presencial e eram descartadas por não citarem
# Brasília — foi assim que as fontes brasileiras ficaram meses mudas.
_SINAL_REMOTO = re.compile(r"(?<!\w)(?:remoto|remota|remote|home office|teletrabalho|anywhere)(?!\w)")
_PONTUACAO_DE_LOCAL = " \t\n-–—,;/|()[]:."
# "(Remote - Denmark)", "[Remoto]", "(Hybrid)": qualificador de regime/lugar
# que distingue anúncios da MESMA vaga, não vagas diferentes. Só parênteses
# com essas palavras saem — "(Backend)" e "(Frontend)" continuam distintos.
_QUALIFICADOR_DE_REGIME = re.compile(
    r"[(\[][^)\]]*(?:remot|hybrid|hibrid|presencial|on-?site|anywhere)[^)\]]*[)\]]"
)


def normalizar(texto: str) -> str:
    """Texto comparável: sem HTML/Markdown, sem acento e em minúsculas.

    Sem isso "inteligencia" não casa com "inteligência", e o HTML cru que
    Remotive/Jobicy mandam ("Intelig&ecirc;ncia") não casa com nenhum dos dois.
    """
    decomposto = unicodedata.normalize("NFKD", normalizar_texto(texto))
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def vaga_passa_filtro(vaga: Vaga, filtros: FiltrosConfig) -> bool:
    texto = normalizar(f"{vaga.titulo}\n{vaga.descricao}")

    if filtros.remoto is True and vaga.remoto is False:
        return False

    if filtros.excluir and _contem_alguma(texto, filtros.excluir):
        return False

    if filtros.palavras_chave and not _contem_alguma(texto, filtros.palavras_chave):
        return False

    if filtros.senioridade and not _contem_alguma(texto, filtros.senioridade):
        return False

    if filtros.localizacao and not _bate_localizacao(vaga, texto, filtros):
        return False

    return True


def aplicar_filtros(vagas: list[Vaga], filtros: FiltrosConfig) -> list[Vaga]:
    return [vaga for vaga in vagas if vaga_passa_filtro(vaga, filtros)]


def impressao_digital(vaga: Vaga) -> str | None:
    """Chave "mesma vaga" entre fontes e entre anúncios por país.

    Empresa + título normalizado, sem o qualificador de regime. Sem empresa
    (issues do GitHub) não há como distinguir "Dev Python Pleno" de duas
    empresas diferentes, então não há impressão digital.
    """
    empresa = " ".join(re.findall(r"\w+", normalizar(vaga.empresa)))
    titulo = " ".join(re.findall(r"\w+", _QUALIFICADOR_DE_REGIME.sub(" ", normalizar(vaga.titulo))))
    if not empresa or not titulo:
        return None
    return f"{empresa}|{titulo}"


def eh_remota(vaga: Vaga) -> bool:
    """O que a fonte disser; se ela não souber, o título decide."""
    if vaga.remoto is not None:
        return vaga.remoto
    return bool(_SINAL_REMOTO.search(normalizar(vaga.titulo)))


def _bate_localizacao(vaga: Vaga, texto: str, filtros: FiltrosConfig) -> bool:
    local = normalizar(vaga.localizacao or "")
    if eh_remota(vaga):
        return _remota_aceita(local, filtros)
    # presencial/híbrida só serve se for na região configurada.
    return _contem_alguma(f"{texto}\n{local}", filtros.localizacao)


def _remota_aceita(local: str, filtros: FiltrosConfig) -> bool:
    # "Remote", "Remoto - Anywhere" ou vazio: não há restrição declarada.
    restricao = _SINAL_REMOTO.sub(" ", local).strip(_PONTUACAO_DE_LOCAL)
    if not restricao or not filtros.remoto_aceito:
        return True
    # "remoto só nos EUA" não serve; "remoto, mas morando no DF" serve.
    return _contem_alguma(local, filtros.remoto_aceito) or _contem_alguma(local, filtros.localizacao)


def _contem_alguma(texto: str, termos: list[str]) -> bool:
    return any(_padrao(termo).search(texto) for termo in termos)


@lru_cache(maxsize=512)
def _padrao(termo: str) -> re.Pattern[str]:
    # `termo*` casa qualquer continuação: "desenvolvedor*" pega desenvolvedora
    # e desenvolvedores. O `*` sai antes de normalizar, que o trataria como
    # ênfase de Markdown.
    termo = termo.strip()
    prefixo = termo.endswith("*")
    base = normalizar(termo.rstrip("*"))
    continuacao = r"\w*" if prefixo else ""
    # (?<!\w)…(?!\w) em vez de \b: um termo que termina em símbolo ("c++")
    # nunca casaria com um \b depois dele. Mesma lição do extracao.py.
    return re.compile(rf"(?<!\w){re.escape(base)}{continuacao}(?!\w)")
