from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbySource(Source):
    """Lê vagas do endpoint público do Ashby (o ATS por trás da página de
    carreira da empresa) — sem autenticação, um board por empresa."""

    def __init__(self, empresa: str, timeout: float = 15.0) -> None:
        self.empresa = empresa
        self.nome = f"ashby:{empresa}"
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(f"{API_BASE}/{self.empresa}")
            resposta.raise_for_status()
            dados = resposta.json()

        return [self._mapear(item) for item in dados.get("jobs", [])]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        return Vaga(
            id=f"ashby:{self.empresa}:{item['id']}",
            titulo=item.get("title", ""),
            empresa=self.empresa,
            url=item.get("jobUrl", ""),
            fonte=self.nome,
            localizacao=item.get("location") or None,
            remoto=item.get("isRemote"),
            publicada_em=_parse_data(item.get("publishedAt")),
            descricao=item.get("descriptionPlain") or item.get("descriptionHtml", ""),
        )


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
