from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicySource(Source):
    """API pública do Jobicy — agregador de vagas 100% remotas."""

    nome = "jobicy"

    def __init__(
        self,
        geo: str | None = None,
        tag: str | None = None,
        quantidade: int = 100,
        timeout: float = 15.0,
    ) -> None:
        self.geo = geo
        self.tag = tag
        self.quantidade = quantidade
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        # `geo` filtra na própria API por onde a pessoa pode morar ("brazil"
        # devolve vagas abertas ao Brasil, à LATAM ou a qualquer lugar).
        params: dict[str, Any] = {"count": self.quantidade}
        if self.geo:
            params["geo"] = self.geo
        if self.tag:
            params["tag"] = self.tag
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(API_URL, params=params)
            resposta.raise_for_status()
            dados = resposta.json()

        return self._mapear_itens(dados.get("jobs", []), self._mapear)

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        return Vaga(
            id=f"jobicy:{item['id']}",
            titulo=item.get("jobTitle", ""),
            empresa=item.get("companyName", ""),
            url=item.get("url", ""),
            fonte=self.nome,
            localizacao=item.get("jobGeo") or None,
            # o Jobicy só lista vagas remotas.
            remoto=True,
            publicada_em=_parse_data(item.get("pubDate")),
            descricao=item.get("jobDescription") or item.get("jobExcerpt", ""),
        )


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
