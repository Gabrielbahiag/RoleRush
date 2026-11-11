from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_BASE = "https://api.adzuna.com/v1/api/jobs"


class AdzunaSource(Source):
    """Agregador de vagas com filtro real de localização (ex: cidade no Brasil)."""

    nome = "adzuna"

    def __init__(
        self,
        pais: str = "br",
        what: str | None = None,
        where: str | None = None,
        app_id: str | None = None,
        app_key: str | None = None,
        resultados_por_pagina: int = 50,
        paginas: int = 3,
        max_dias: int | None = 3,
        timeout: float = 15.0,
    ) -> None:
        self.pais = pais
        self.what = what
        self.where = where
        self.app_id = app_id or os.environ.get("ADZUNA_APP_ID")
        self.app_key = app_key or os.environ.get("ADZUNA_APP_KEY")
        self.resultados_por_pagina = resultados_por_pagina
        self.paginas = paginas
        self.max_dias = max_dias
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        if not (self.app_id and self.app_key):
            raise RuntimeError(
                "Adzuna não configurado: defina ADZUNA_APP_ID e ADZUNA_APP_KEY."
            )

        params: dict[str, Any] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": self.resultados_por_pagina,
            "content-type": "application/json",
            # sem isto a ordem é por relevância: a página 1 traz as mesmas
            # vagas "relevantes" de sempre e as recém-publicadas podem nunca
            # aparecer. Um monitor de novidades precisa da mais nova primeiro.
            "sort_by": "date",
        }
        if self.max_dias:
            params["max_days_old"] = self.max_dias
        if self.what:
            params["what"] = self.what
        if self.where:
            params["where"] = self.where

        itens: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout) as client:
            # o plano gratuito tem cota diária de chamadas: 3 páginas x 4
            # execuções = 12/dia, e a paginação para na primeira incompleta.
            for pagina in range(1, self.paginas + 1):
                resposta = client.get(f"{API_BASE}/{self.pais}/search/{pagina}", params=params)
                resposta.raise_for_status()
                resultados = resposta.json().get("results", [])
                itens.extend(resultados)
                if len(resultados) < self.resultados_por_pagina:
                    break

        return self._mapear_itens(itens, self._mapear)

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        localizacao = (item.get("location") or {}).get("display_name")
        return Vaga(
            id=f"adzuna:{item['id']}",
            titulo=item.get("title", ""),
            empresa=(item.get("company") or {}).get("display_name", ""),
            url=item.get("redirect_url", ""),
            fonte=self.nome,
            localizacao=localizacao,
            # a API não expõe um campo booleano confiável de remoto; deixamos
            # como desconhecido e o filtro de localização decide pelo texto.
            remoto=None,
            publicada_em=_parse_data(item.get("created")),
            descricao=item.get("description", ""),
        )


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
