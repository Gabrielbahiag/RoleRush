"""Saúde das fontes: o que cada execução coletou, aprovou e notificou.

Existe porque a falha mais cara deste projeto é silenciosa: uma fonte que
quebra ou que deixa de render (os repositórios do GitHub passaram 4 meses
entregando zero vagas sem ninguém notar) não derruba o job — o isolamento
por fonte em `coletar_vagas` faz exatamente o contrário. Daqui saem o aviso
de "fonte quebrou" e o resumo semanal que tornam isso visível.

Formatação pura, sem I/O; quem grava é o `Storage` e quem envia é o `main`.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class RegistroFonte:
    fonte: str
    coletadas: int = 0
    aprovadas: int = 0
    notificadas: int = 0
    erro: str | None = None


@dataclass(slots=True)
class ResumoFonte:
    fonte: str
    execucoes: int
    falhas: int
    coletadas: int
    aprovadas: int
    notificadas: int
    ultimo_erro: str | None


def descrever_erro(erro: Exception) -> str:
    """Descrição de erro segura para log e para o Telegram.

    Nunca `str(erro)` de um erro do httpx: a mensagem inclui a URL completa,
    e é na URL que vão o token do bot e o `app_key` da Adzuna.
    """
    if isinstance(erro, httpx.HTTPStatusError):
        return f"HTTP {erro.response.status_code}"
    if isinstance(erro, httpx.HTTPError):
        return type(erro).__name__
    return f"{type(erro).__name__}: {erro}"[:200]


def formatar_alerta_falhas(falhas: dict[str, str]) -> str:
    linhas = [f"• {_e(fonte)}: {_e(erro)}" for fonte, erro in sorted(falhas.items())]
    return "\n".join(
        [
            "⚠️ <b>Fonte(s) de vagas com falha</b>",
            *linhas,
            "As outras fontes rodaram normalmente. Só aviso de novo se ela voltar e "
            "quebrar outra vez; o resumo semanal lista as que continuam quebradas.",
        ]
    )


def formatar_resumo(resumos: list[ResumoFonte], dias: int) -> str:
    linhas = [f"📊 <b>Resumo dos últimos {dias} dias</b>", "fonte: coletadas → aprovadas → notificadas"]
    for resumo in sorted(resumos, key=lambda r: r.fonte):
        linha = f"{_e(resumo.fonte)}: {resumo.coletadas} → {resumo.aprovadas} → {resumo.notificadas}"
        if resumo.falhas:
            linha += f" ⚠️ falhou em {resumo.falhas}/{resumo.execucoes}"
            if resumo.ultimo_erro:
                linha += f" ({_e(resumo.ultimo_erro)})"
        elif resumo.coletadas == 0:
            linha += " ⚠️ não devolveu nada"
        elif resumo.aprovadas == 0:
            linha += " ⚠️ nada passou no filtro"
        linhas.append(linha)
    total = sum(r.notificadas for r in resumos)
    linhas.append(f"total notificado: {total}")
    return "\n".join(linhas)


def _e(texto: str) -> str:
    return html.escape(texto, quote=False)
