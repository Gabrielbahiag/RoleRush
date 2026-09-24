from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from monitor.curriculo.normalizacao import Idioma


class IdiomaIndisponivelError(ValueError):
    """O currículo foi pedido num idioma que aquele texto não tem."""


class TextoBilingue(BaseModel):
    """Texto do currículo nos dois idiomas suportados.

    O mestre é bilíngue de propósito: traduzir por IA na hora de gerar
    poderia alterar o sentido do que foi realmente feito.
    """

    pt: str | None = None
    en: str | None = None

    @model_validator(mode="after")
    def _ao_menos_um_idioma(self) -> TextoBilingue:
        if not (self.pt or self.en):
            raise ValueError("texto precisa ter ao menos um idioma preenchido (pt ou en)")
        return self

    def para(self, idioma: Idioma, contexto: str) -> str:
        valor = self.pt if idioma == "pt" else self.en
        if not valor:
            raise IdiomaIndisponivelError(f"{contexto} não tem texto em '{idioma}'")
        return valor


class Bullet(BaseModel):
    """Uma linha de realização do currículo.

    O `id` é a âncora do guardrail anti-invenção: toda reescrita por IA
    precisa apontar para um bullet real, e é por esse id que se rastreia
    a origem. Por isso ele tem que ser único no currículo inteiro.
    """

    id: str
    texto: TextoBilingue
    # skills que este bullet comprova; alimentam a seleção por relevância.
    tags: list[str] = Field(default_factory=list)

    def texto_para(self, idioma: Idioma) -> str:
        return self.texto.para(idioma, f"bullet '{self.id}'")


class Contato(BaseModel):
    email: str
    telefone: str | None = None
    cidade: str | None = None


class Links(BaseModel):
    github: str | None = None
    linkedin: str | None = None
    portfolio: str | None = None


class Dados(BaseModel):
    nome: str
    contato: Contato
    links: Links = Field(default_factory=Links)


class Experiencia(BaseModel):
    cargo: str
    empresa: str
    periodo: str
    bullets: list[Bullet] = Field(default_factory=list)


class Projeto(BaseModel):
    nome: str
    descricao: TextoBilingue
    stack: list[str] = Field(default_factory=list)
    link: str | None = None
    bullets: list[Bullet] = Field(default_factory=list)


class Formacao(BaseModel):
    curso: str
    instituicao: str
    status: str | None = None


class Skill(BaseModel):
    nome: str
    categoria: str | None = None
    nivel: str | None = None


class IdiomaFalado(BaseModel):
    nome: str
    nivel: str | None = None


class Certificacao(BaseModel):
    nome: str
    emissor: str | None = None
    ano: int | None = None


class CurriculoMestre(BaseModel):
    dados: Dados
    resumo: TextoBilingue
    experiencias: list[Experiencia] = Field(default_factory=list)
    projetos: list[Projeto] = Field(default_factory=list)
    formacao: list[Formacao] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    idiomas: list[IdiomaFalado] = Field(default_factory=list)
    certificacoes: list[Certificacao] = Field(default_factory=list)

    def todos_bullets(self) -> list[Bullet]:
        bullets: list[Bullet] = []
        for experiencia in self.experiencias:
            bullets.extend(experiencia.bullets)
        for projeto in self.projetos:
            bullets.extend(projeto.bullets)
        return bullets

    @model_validator(mode="after")
    def _ids_de_bullet_unicos(self) -> CurriculoMestre:
        vistos: set[str] = set()
        duplicados: set[str] = set()
        for bullet in self.todos_bullets():
            if bullet.id in vistos:
                duplicados.add(bullet.id)
            vistos.add(bullet.id)
        if duplicados:
            raise ValueError(
                "ids de bullet duplicados (precisam ser únicos no currículo "
                f"inteiro): {', '.join(sorted(duplicados))}"
            )
        return self


def carregar_curriculo(caminho: str | Path = "curriculo_mestre.yaml") -> CurriculoMestre:
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Currículo-mestre não encontrado: {caminho}")
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    return CurriculoMestre.model_validate(dados)
