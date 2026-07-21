from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Vaga:
    """Uma vaga de emprego normalizada, independente da fonte de origem.

    `id` é a chave de dedup e deve ser estável entre execuções — preferir
    o id nativo da fonte ou a URL canônica, nunca o título.
    """

    id: str
    titulo: str
    empresa: str
    url: str
    fonte: str
    localizacao: str | None = None
    remoto: bool | None = None
    publicada_em: datetime | None = None
    descricao: str = ""

    def texto_busca(self) -> str:
        return f"{self.titulo}\n{self.descricao}".lower()
