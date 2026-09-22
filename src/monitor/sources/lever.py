from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_BASE = "https://api.lever.co/v0/postings"


class LeverSource(Source):
    """Lê vagas do endpoint público do Lever (o ATS por trás da página de
    carreira da empresa) — sem autenticação, um board por empresa."""

    def __init__(self, empresa: str, timeout: float = 15.0) -> None:
        self.empresa = empresa
        self.nome = f"lever:{empresa}"
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(f"{API_BASE}/{self.empresa}", params={"mode": "json"})
            resposta.raise_for_status()
            itens = resposta.json()

        return [self._mapear(item) for item in itens]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        localizacao = (item.get("categories") or {}).get("location")
        return Vaga(
            id=f"lever:{self.empresa}:{item['id']}",
            titulo=item.get("text", ""),
            empresa=self.empresa,
            url=item.get("hostedUrl", ""),
            fonte=self.nome,
            localizacao=localizacao,
            remoto=item.get("workplaceType") == "remote",
            publicada_em=_parse_epoch_ms(item.get("createdAt")),
            descricao=item.get("descriptionPlain") or item.get("description", ""),
        )


def _parse_epoch_ms(valor: int | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromtimestamp(valor / 1000)
    except (ValueError, OSError):
        return None
