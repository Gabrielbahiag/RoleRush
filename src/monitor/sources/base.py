from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any

from monitor.models import Vaga

logger = logging.getLogger("monitor.sources")


class Source(ABC):
    """Interface que toda fonte de vagas deve implementar.

    Adicionar uma fonte nova é criar uma classe que implementa `fetch()`,
    sem precisar tocar em nada do resto do pipeline (filtros, dedup, notifier).
    """

    # toda `Vaga` devolvida por esta fonte leva `fonte=self.nome`: é por esse
    # campo que o resumo de saúde conta aprovadas/notificadas por fonte.
    nome: str

    @abstractmethod
    def fetch(self) -> list[Vaga]:
        """Busca vagas na fonte e retorna já mapeadas para `Vaga`."""
        raise NotImplementedError

    def _mapear_itens(self, itens: Iterable[Any], mapear: Callable[[Any], Vaga]) -> list[Vaga]:
        """Mapeia item a item: um item malformado é descartado, não a fonte toda.

        Se NENHUM item puder ser lido, o formato da API provavelmente mudou —
        aí sim é falha da fonte (e vira aviso), em vez de um "zero vagas"
        silencioso.
        """
        vagas: list[Vaga] = []
        descartados = 0
        for item in itens:
            try:
                vagas.append(mapear(item))
            except (KeyError, TypeError, ValueError, AttributeError) as erro:
                descartados += 1
                logger.warning("%s: item ignorado (%s: %s)", self.nome, type(erro).__name__, erro)
        if descartados and not vagas:
            raise ValueError(f"nenhum dos {descartados} item(ns) reconhecido — o formato da API mudou?")
        return vagas
