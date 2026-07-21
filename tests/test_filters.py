from monitor.config import FiltrosConfig
from monitor.filters import aplicar_filtros, vaga_passa_filtro
from monitor.models import Vaga


def _vaga(**kwargs) -> Vaga:
    base = dict(
        id="1",
        titulo="Backend Python Jr",
        empresa="Acme",
        url="http://x",
        fonte="teste",
        localizacao="Remoto",
        remoto=True,
        descricao="vaga junior de python",
    )
    base.update(kwargs)
    return Vaga(**base)


def test_passa_quando_bate_palavra_chave():
    filtros = FiltrosConfig(palavras_chave=["python"])
    assert vaga_passa_filtro(_vaga(), filtros)


def test_rejeita_quando_nao_bate_palavra_chave():
    filtros = FiltrosConfig(palavras_chave=["java"])
    assert not vaga_passa_filtro(_vaga(), filtros)


def test_rejeita_por_termo_excluido():
    filtros = FiltrosConfig(excluir=["senior"])
    vaga = _vaga(titulo="Backend Python Senior")
    assert not vaga_passa_filtro(vaga, filtros)


def test_rejeita_vaga_presencial_quando_so_remoto():
    filtros = FiltrosConfig(remoto=True)
    vaga = _vaga(remoto=False)
    assert not vaga_passa_filtro(vaga, filtros)


def test_aceita_remoto_desconhecido_quando_so_remoto():
    # Fontes como a de issues do GitHub não sabem dizer se é remoto;
    # não devemos descartar por falta de informação, só por "False" explícito.
    filtros = FiltrosConfig(remoto=True)
    vaga = _vaga(remoto=None)
    assert vaga_passa_filtro(vaga, filtros)


def test_filtro_sem_criterios_aceita_tudo():
    filtros = FiltrosConfig()
    assert vaga_passa_filtro(_vaga(), filtros)


def test_aplicar_filtros_combina_multiplos_criterios():
    filtros = FiltrosConfig(palavras_chave=["python"], excluir=["senior"])
    vagas = [
        _vaga(id="1", titulo="Python Jr"),
        _vaga(id="2", titulo="Python Senior"),
        _vaga(id="3", titulo="Java Jr", descricao="java"),
    ]
    resultado = aplicar_filtros(vagas, filtros)
    assert [vaga.id for vaga in resultado] == ["1"]


def test_palavra_curta_nao_da_falso_positivo_em_substring():
    # "ia" não pode bater em "engenharia" — precisa ser a palavra isolada.
    filtros = FiltrosConfig(palavras_chave=["ia"])
    vaga = _vaga(titulo="Engenharia de Dados", descricao="vaga de engenharia")
    assert not vaga_passa_filtro(vaga, filtros)


def test_palavra_curta_bate_quando_isolada():
    filtros = FiltrosConfig(palavras_chave=["ia"])
    vaga = _vaga(titulo="Especialista em IA", descricao="foco em ia generativa")
    assert vaga_passa_filtro(vaga, filtros)


def test_localizacao_aceita_vaga_remota_independente_do_texto():
    filtros = FiltrosConfig(localizacao=["brasília"])
    vaga = _vaga(remoto=True, localizacao="Worldwide")
    assert vaga_passa_filtro(vaga, filtros)


def test_localizacao_aceita_presencial_quando_bate_termo():
    filtros = FiltrosConfig(localizacao=["brasília", "df"])
    vaga = _vaga(remoto=False, localizacao="Brasília - DF")
    assert vaga_passa_filtro(vaga, filtros)


def test_localizacao_rejeita_presencial_fora_da_regiao():
    filtros = FiltrosConfig(localizacao=["brasília", "df"])
    vaga = _vaga(remoto=False, localizacao="São Paulo - SP")
    assert not vaga_passa_filtro(vaga, filtros)
