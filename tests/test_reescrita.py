import json
from pathlib import Path

import pytest

from monitor.curriculo.extracao import RequisitosVaga
from monitor.curriculo.llm import LLMProvider, ProvedorNenhum
from monitor.curriculo.mestre import carregar_curriculo
from monitor.curriculo.reescrita import reescrever
from monitor.curriculo.selecao import selecionar
from monitor.curriculo.skills import carregar_skills

RAIZ = Path(__file__).resolve().parents[1]


class _ProvedorFake(LLMProvider):
    nome = "fake"

    def __init__(self, resposta: str | None) -> None:
        self.resposta = resposta
        self.prompt: str | None = None

    def gerar(self, prompt: str) -> str | None:
        self.prompt = prompt
        return self.resposta


@pytest.fixture(scope="module")
def dicionario():
    return carregar_skills(RAIZ / "config" / "skills.yaml")


@pytest.fixture(scope="module")
def mestre():
    return carregar_curriculo(RAIZ / "curriculo_mestre.example.yaml")


@pytest.fixture
def adaptado(mestre, dicionario):
    requisitos = RequisitosVaga(obrigatorios=["Python", "SQL"], idioma="pt")
    return selecionar(mestre, requisitos, dicionario)


def _primeiro_bullet(adaptado):
    return adaptado.experiencias[0].bullets[0]


def _resposta(itens: list[dict]) -> str:
    return json.dumps(itens, ensure_ascii=False)


def test_provedor_nenhum_nao_reescreve_nada(adaptado, mestre, dicionario):
    resultado = reescrever(adaptado, ProvedorNenhum(), mestre, dicionario)

    assert resultado.textos == {}
    assert resultado.rejeicoes == []


def test_resposta_vazia_do_modelo_cai_pro_fallback(adaptado, mestre, dicionario):
    resultado = reescrever(adaptado, _ProvedorFake(None), mestre, dicionario)

    assert resultado.textos == {}


def test_json_invalido_cai_pro_fallback_sem_reescrita(adaptado, mestre, dicionario):
    provedor = _ProvedorFake("desculpe, não consegui responder em JSON")

    resultado = reescrever(adaptado, provedor, mestre, dicionario)

    assert resultado.textos == {}


def test_reescrita_valida_e_aplicada(adaptado, mestre, dicionario):
    bullet = _primeiro_bullet(adaptado)
    novo = "Estruturei pipelines de ingestão em Python consolidando dados de APIs públicas."
    provedor = _ProvedorFake(_resposta([{"id": bullet.id, "texto": novo}]))

    resultado = reescrever(adaptado, provedor, mestre, dicionario)

    assert resultado.textos == {bullet.id: novo}
    assert resultado.rejeicoes == []


def test_json_dentro_de_cerca_de_codigo_e_lido(adaptado, mestre, dicionario):
    bullet = _primeiro_bullet(adaptado)
    novo = "Estruturei pipelines de ingestão em Python."
    bruto = f"Claro! Aqui está:\n```json\n{_resposta([{'id': bullet.id, 'texto': novo}])}\n```"

    resultado = reescrever(adaptado, _ProvedorFake(bruto), mestre, dicionario)

    assert resultado.textos == {bullet.id: novo}


def test_reescrita_reprovada_no_guardrail_nao_entra_e_registra_o_motivo(adaptado, mestre, dicionario):
    bullet = _primeiro_bullet(adaptado)
    inventado = "Reduzi em 87% o custo de ingestão com Kubernetes na Google."
    provedor = _ProvedorFake(_resposta([{"id": bullet.id, "texto": inventado}]))

    resultado = reescrever(adaptado, provedor, mestre, dicionario)

    assert resultado.textos == {}
    assert [rejeicao.id for rejeicao in resultado.rejeicoes] == [bullet.id]
    assert resultado.rejeicoes[0].motivo


def test_bullet_fora_da_selecao_e_rejeitado(adaptado, mestre, dicionario):
    provedor = _ProvedorFake(_resposta([{"id": "id-que-nao-existe", "texto": "Qualquer coisa."}]))

    resultado = reescrever(adaptado, provedor, mestre, dicionario)

    assert resultado.textos == {}
    assert resultado.rejeicoes


def test_prompt_leva_os_ids_para_a_reescrita_ser_rastreavel(adaptado, mestre, dicionario):
    provedor = _ProvedorFake(_resposta([]))

    reescrever(adaptado, provedor, mestre, dicionario)

    assert _primeiro_bullet(adaptado).id in provedor.prompt


def test_reescrita_nao_altera_o_curriculo_mestre(adaptado, mestre, dicionario):
    bullet = _primeiro_bullet(adaptado)
    texto_antes = bullet.texto_para("pt")
    provedor = _ProvedorFake(_resposta([{"id": bullet.id, "texto": "Estruturei pipelines em Python."}]))

    reescrever(adaptado, provedor, mestre, dicionario)

    assert bullet.texto_para("pt") == texto_antes
