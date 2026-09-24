from __future__ import annotations

from pathlib import Path
from typing import Literal

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


class AdzunaConfig(BaseModel):
    ativo: bool = False
    pais: str = "br"
    what: str | None = None
    where: str | None = None


class RemoteOKConfig(BaseModel):
    ativo: bool = False


class ArbeitnowConfig(BaseModel):
    ativo: bool = False


class HimalayasConfig(BaseModel):
    ativo: bool = False
    country: str | None = None
    q: str | None = None


class JobicyConfig(BaseModel):
    ativo: bool = False


class TheMuseConfig(BaseModel):
    ativo: bool = False
    categoria: str | None = None
    localizacao: str | None = None


class GreenhouseConfig(BaseModel):
    ativo: bool = False
    empresas: list[str] = Field(default_factory=list)


class LeverConfig(BaseModel):
    ativo: bool = False
    empresas: list[str] = Field(default_factory=list)


class AshbyConfig(BaseModel):
    ativo: bool = False
    empresas: list[str] = Field(default_factory=list)


class FontesConfig(BaseModel):
    remotive: RemotiveConfig = Field(default_factory=RemotiveConfig)
    github_repo: GithubRepoConfig = Field(default_factory=GithubRepoConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    arbeitnow: ArbeitnowConfig = Field(default_factory=ArbeitnowConfig)
    himalayas: HimalayasConfig = Field(default_factory=HimalayasConfig)
    jobicy: JobicyConfig = Field(default_factory=JobicyConfig)
    themuse: TheMuseConfig = Field(default_factory=TheMuseConfig)
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    lever: LeverConfig = Field(default_factory=LeverConfig)
    ashby: AshbyConfig = Field(default_factory=AshbyConfig)


class NotificacaoConfig(BaseModel):
    telegram: bool = False


class CurriculoConfig(BaseModel):
    # dado pessoal: fica fora do git, então não existe no runner do Actions.
    mestre: str = "curriculo_mestre.yaml"
    skills: str = "config/skills.yaml"
    # "nenhum" mantém a feature 100% determinística e sem custo; nome errado
    # explode aqui, na carga, e não no meio da geração do currículo.
    provedor: Literal["nenhum", "claude-cli"] = "nenhum"
    timeout_ia: float = 60.0
    # alternativa versionável pro Actions: só a lista de skills canônicas,
    # sem nome, contato ou histórico. Vazio = sem pontuação lá.
    skills_perfil: list[str] = Field(default_factory=list)


class Config(BaseModel):
    filtros: FiltrosConfig = Field(default_factory=FiltrosConfig)
    fontes: FontesConfig = Field(default_factory=FontesConfig)
    notificacao: NotificacaoConfig = Field(default_factory=NotificacaoConfig)
    curriculo: CurriculoConfig = Field(default_factory=CurriculoConfig)
    # None = mantém o histórico de dedup pra sempre (comportamento anterior).
    retencao_dias: int | None = None
    # None = notifica tudo; sem fonte de pontuação, o corte é ignorado.
    aderencia_minima: int | None = None


def carregar_config(caminho: str | Path = "config.yaml") -> Config:
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de config não encontrado: {caminho}")
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    return Config.model_validate(dados)
