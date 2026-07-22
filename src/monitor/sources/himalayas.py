from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_URL = "https://himalayas.app/jobs/api/search"


class HimalayasSource(Source):
    """API pública do Himalayas, com busca real por país + palavra-chave."""

    nome = "himalayas"

    def __init__(
        self,
        country: str | None = None,
        q: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.country = country
        self.q = q
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        params: dict[str, Any] = {}
        if self.country:
            params["country"] = self.country
        if self.q:
            params["q"] = self.q

        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(API_URL, params=params)
            resposta.raise_for_status()
            dados = resposta.json()

        return [self._mapear(item) for item in dados.get("jobs", [])]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        localizacao = ", ".join(item.get("locationRestrictions") or []) or None
        return Vaga(
            id=f"himalayas:{item['guid']}",
            titulo=item.get("title", ""),
            empresa=item.get("companyName", ""),
            url=item.get("applicationLink") or item.get("guid", ""),
            fonte=self.nome,
            localizacao=localizacao,
            # a API não expõe um booleano confiável de remoto; algumas vagas
            # de "locationRestrictions" exigem presença em escritório.
            remoto=None,
            publicada_em=_parse_epoch(item.get("pubDate")),
            descricao=item.get("description") or item.get("excerpt", ""),
        )


def _parse_epoch(valor: int | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromtimestamp(valor)
    except (ValueError, OSError):
        return None
