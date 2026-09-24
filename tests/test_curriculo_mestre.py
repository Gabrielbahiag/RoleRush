from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from monitor.curriculo.mestre import (
    Bullet,
    TextoBilingue,
    carregar_curriculo,
)

RAIZ = Path(__file__).resolve().parents[1]
EXEMPLO = RAIZ / "curriculo_mestre.example.yaml"


def _exemplo_como_dict() -> dict:
    return yaml.safe_load(EXEMPLO.read_text(encoding="utf-8"))


def _gravar(tmp_path, dados: dict) -> Path:
    caminho = tmp_path / "mestre.yaml"
    caminho.write_text(yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8")
    return caminho


def test_exemplo_ficticio_carrega_e_valida():
    curriculo = carregar_curriculo(EXEMPLO)

    assert curriculo.dados.nome
    assert curriculo.experiencias
    assert curriculo.projetos
    assert curriculo.skills


def test_exemplo_tem_ids_de_bullet_unicos():
    curriculo = carregar_curriculo(EXEMPLO)

    ids = [bullet.id for bullet in curriculo.todos_bullets()]

    assert ids
    assert len(ids) == len(set(ids))


def test_todos_bullets_cobre_experiencias_e_projetos():
    curriculo = carregar_curriculo(EXEMPLO)

    ids = {bullet.id for bullet in curriculo.todos_bullets()}

    for experiencia in curriculo.experiencias:
        for bullet in experiencia.bullets:
            assert bullet.id in ids
    for projeto in curriculo.projetos:
        for bullet in projeto.bullets:
            assert bullet.id in ids


def test_id_de_bullet_duplicado_da_erro_claro(tmp_path):
    dados = _exemplo_como_dict()
    repetido = dados["experiencias"][0]["bullets"][0]["id"]
    dados["projetos"][0]["bullets"][0]["id"] = repetido

    with pytest.raises(ValidationError) as excinfo:
        carregar_curriculo(_gravar(tmp_path, dados))

    assert "duplicad" in str(excinfo.value)
    assert repetido in str(excinfo.value)


def test_campo_obrigatorio_faltando_da_erro_claro(tmp_path):
    dados = _exemplo_como_dict()
    del dados["dados"]["nome"]

    with pytest.raises(ValidationError) as excinfo:
        carregar_curriculo(_gravar(tmp_path, dados))

    assert "nome" in str(excinfo.value)


def test_arquivo_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="nao-existe"):
        carregar_curriculo(tmp_path / "nao-existe.yaml")


def test_texto_sem_nenhum_idioma_preenchido_e_rejeitado():
    with pytest.raises(ValidationError, match="ao menos um idioma"):
        TextoBilingue()


def test_bullet_devolve_texto_no_idioma_pedido():
    bullet = Bullet(id="exp-1", texto=TextoBilingue(pt="olá", en="hello"))

    assert bullet.texto_para("pt") == "olá"
    assert bullet.texto_para("en") == "hello"


def test_bullet_so_em_pt_pedido_em_en_da_erro_explicativo():
    bullet = Bullet(id="exp-1", texto=TextoBilingue(pt="Construí o pipeline"))

    with pytest.raises(ValueError) as excinfo:
        bullet.texto_para("en")

    # o erro precisa dizer QUAL bullet e QUAL idioma, senão não dá pra corrigir
    # o currículo-mestre sem caçar na mão.
    assert "exp-1" in str(excinfo.value)
    assert "en" in str(excinfo.value)


def test_resumo_do_exemplo_existe_nos_dois_idiomas():
    curriculo = carregar_curriculo(EXEMPLO)

    assert curriculo.resumo.para("pt", "resumo")
    assert curriculo.resumo.para("en", "resumo")


def test_bullets_do_exemplo_tem_texto_nos_dois_idiomas():
    # o mestre é bilíngue por decisão travada (CURRICULO.md §3): se um bullet
    # só existir em pt, gerar currículo em inglês quebra na hora.
    curriculo = carregar_curriculo(EXEMPLO)

    for bullet in curriculo.todos_bullets():
        assert bullet.texto_para("pt")
        assert bullet.texto_para("en")
