from __future__ import annotations

from abc import ABC, abstractmethod

from monitor.models import Vaga


class Source(ABC):
    """Interface que toda fonte de vagas deve implementar.

    Adicionar uma fonte nova é criar uma classe que implementa `fetch()`,
    sem precisar tocar em nada do resto do pipeline (filtros, dedup, notifier).
    """

    nome: str

    @abstractmethod
    def fetch(self) -> list[Vaga]:
        """Busca vagas na fonte e retorna já mapeadas para `Vaga`."""
        raise NotImplementedError
