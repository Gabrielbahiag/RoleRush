from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseSource(Source):
    """Lê vagas do endpoint público do Greenhouse (o ATS por trás da página
    de carreira da empresa) — sem autenticação, um board por empresa."""

    def __init__(self, empresa: str, timeout: float = 15.0) -> None:
        self.empresa = empresa
        self.nome = f"greenhouse:{empresa}"
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(
                f"{API_BASE}/{self.empresa}/jobs",
                # content=true traz a descrição completa; sem isso o campo
                # "content" nem aparece na resposta.
                params={"content": "true"},
            )
            resposta.raise_for_status()
            dados = resposta.json()

        return [self._mapear(item) for item in dados.get("jobs", [])]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        localizacao = (item.get("location") or {}).get("name")
        return Vaga(
            id=f"greenhouse:{self.empresa}:{item['id']}",
            titulo=item.get("title", ""),
            empresa=self.empresa,
            url=item.get("absolute_url", ""),
            fonte=self.nome,
            localizacao=localizacao,
            remoto=_parece_remoto(localizacao),
            publicada_em=_parse_data(item.get("first_published")),
            descricao=item.get("content") or "",
        )


def _parece_remoto(localizacao: str | None) -> bool | None:
    if not localizacao:
        return None
    return "remote" in localizacao.lower() or "remoto" in localizacao.lower()


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
