from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_BASE = "https://api.github.com"


class GithubRepoSource(Source):
    """Lê vagas publicadas como issues em repositórios como backend-br/vagas."""

    def __init__(self, repo: str, timeout: float = 15.0) -> None:
        self.repo = repo
        self.nome = f"github:{repo}"
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            resposta = client.get(
                f"{API_BASE}/repos/{self.repo}/issues",
                params={"state": "open", "per_page": 100},
            )
            resposta.raise_for_status()
            itens = resposta.json()

        # a API de issues do GitHub também retorna pull requests; descartar.
        return self._mapear_itens((item for item in itens if "pull_request" not in item), self._mapear)

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        labels = [(label.get("name") or "") for label in item.get("labels") or []]
        return Vaga(
            id=f"github:{self.repo}:{item['number']}",
            titulo=item.get("title", ""),
            empresa="",
            url=item.get("html_url", ""),
            fonte=self.nome,
            remoto=_remoto_pelas_labels(labels),
            publicada_em=_parse_data(item.get("created_at")),
            descricao=item.get("body") or "",
        )


def _remoto_pelas_labels(labels: list[str]) -> bool | None:
    # backend-br e afins classificam o regime por label ("Remoto",
    # "Presencial", "Híbrido"). Sem label, None: o filtro olha o título.
    nomes = " ".join(labels).lower()
    if "remot" in nomes:
        return True
    if any(termo in nomes for termo in ("presencial", "híbrido", "hibrido", "hybrid")):
        return False
    return None


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
