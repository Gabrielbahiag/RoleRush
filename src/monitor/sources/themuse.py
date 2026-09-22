from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_URL = "https://www.themuse.com/api/public/jobs"

# teto de segurança: evita paginar indefinidamente se a API mudar o formato.
MAX_PAGINAS = 5


class TheMuseSource(Source):
    """API pública do The Muse — vagas com dados de empresa/cultura.

    Funciona sem credencial (500 req/h); THEMUSE_API_KEY é opcional e eleva
    o limite pra 3.600 req/h.
    """

    nome = "themuse"

    def __init__(
        self,
        categoria: str | None = None,
        localizacao: str | None = None,
        api_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.categoria = categoria
        self.localizacao = localizacao
        self.api_key = api_key or os.environ.get("THEMUSE_API_KEY")
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        params: dict[str, Any] = {}
        if self.categoria:
            params["category"] = self.categoria
        if self.localizacao:
            params["location"] = self.localizacao
        if self.api_key:
            params["api_key"] = self.api_key

        vagas: list[Vaga] = []
        with httpx.Client(timeout=self.timeout) as client:
            pagina = 0
            page_count = 1
            while pagina < page_count and pagina < MAX_PAGINAS:
                resposta = client.get(API_URL, params={**params, "page": pagina})
                resposta.raise_for_status()
                dados = resposta.json()

                vagas.extend(self._mapear(item) for item in dados.get("results", []))
                page_count = dados.get("page_count", 1)
                pagina += 1

        return vagas

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        locais = [loc.get("name", "") for loc in item.get("locations") or []]
        localizacao = ", ".join(local for local in locais if local) or None
        return Vaga(
            id=f"themuse:{item['id']}",
            titulo=item.get("name", ""),
            empresa=(item.get("company") or {}).get("name", ""),
            url=(item.get("refs") or {}).get("landing_page", ""),
            fonte=self.nome,
            localizacao=localizacao,
            remoto=_parece_remoto(locais),
            publicada_em=_parse_data(item.get("publication_date")),
            descricao=item.get("contents", ""),
        )


def _parece_remoto(locais: list[str]) -> bool | None:
    if not locais:
        return None
    return any("remote" in local.lower() or "flexible" in local.lower() for local in locais)


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
