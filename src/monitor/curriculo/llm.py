from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod

from monitor.config import Config

logger = logging.getLogger("monitor")


class LLMProvider(ABC):
    """Interface de provedor de IA — mesmo padrão de plugin das fontes.

    `gerar()` devolve `None` em QUALQUER falha (timeout, executável ausente,
    código de erro, saída vazia). Quem chama trata `None` como "siga sem IA":
    a feature inteira funciona sem provedor, então falha de IA nunca pode
    derrubar a geração do currículo.
    """

    nome: str

    @abstractmethod
    def gerar(self, prompt: str) -> str | None:
        raise NotImplementedError


class ProvedorNenhum(LLMProvider):
    """Padrão: não chama IA nenhuma. Mantém um caminho de código só."""

    nome = "nenhum"

    def gerar(self, prompt: str) -> str | None:
        return None


class ProvedorClaudeCLI(LLMProvider):
    """Usa o Claude Code em modo não interativo (`claude -p`), via subprocess."""

    nome = "claude-cli"

    def __init__(self, timeout: float = 60.0, executavel: str = "claude") -> None:
        self.timeout = timeout
        self.executavel = executavel

    def gerar(self, prompt: str) -> str | None:
        try:
            resultado = subprocess.run(
                [self.executavel, "-p", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("%s: tempo esgotado (%ss)", self.nome, self.timeout)
            return None
        except (FileNotFoundError, OSError):
            logger.warning("%s: executável '%s' não encontrado", self.nome, self.executavel)
            return None

        if resultado.returncode != 0:
            logger.warning("%s: saiu com código %s", self.nome, resultado.returncode)
            return None
        return resultado.stdout or None


def montar_provedor(config: Config) -> LLMProvider:
    if config.curriculo.provedor == "claude-cli":
        return ProvedorClaudeCLI(timeout=config.curriculo.timeout_ia)
    return ProvedorNenhum()
