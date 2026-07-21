from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class FiltrosConfig(BaseModel):
    palavras_chave: list[str] = Field(default_factory=list)
    excluir: list[str] = Field(default_factory=list)
    senioridade: list[str] = Field(default_factory=list)
    remoto: bool | None = None
    # vagas remotas passam sempre; presenciais/híbridas só passam se baterem
    # com um desses termos (ex: "brasília", "df"). Vazio = não filtra por local.
    localizacao: list[str] = Field(default_factory=list)


class RemotiveConfig(BaseModel):
    ativo: bool = False
    categoria: str | None = None


class GithubRepoConfig(BaseModel):
    ativo: bool = False
    repos: list[str] = Field(default_factory=list)


class FontesConfig(BaseModel):
    remotive: RemotiveConfig = Field(default_factory=RemotiveConfig)
    github_repo: GithubRepoConfig = Field(default_factory=GithubRepoConfig)


class NotificacaoConfig(BaseModel):
    telegram: bool = False


class Config(BaseModel):
    filtros: FiltrosConfig = Field(default_factory=FiltrosConfig)
    fontes: FontesConfig = Field(default_factory=FontesConfig)
    notificacao: NotificacaoConfig = Field(default_factory=NotificacaoConfig)


def carregar_config(caminho: str | Path = "config.yaml") -> Config:
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de config não encontrado: {caminho}")
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    return Config.model_validate(dados)
