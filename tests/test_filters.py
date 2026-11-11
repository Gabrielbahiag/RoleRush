from monitor.config import FiltrosConfig
from monitor.filters import aplicar_filtros, impressao_digital, vaga_passa_filtro
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


# --- normalização: acento, HTML e variações de palavra ---


def test_palavra_chave_ignora_acento_nos_dois_sentidos():
    filtros = FiltrosConfig(palavras_chave=["inteligência artificial"])
    vaga = _vaga(titulo="Analista de Inteligencia Artificial", descricao="")
    assert vaga_passa_filtro(vaga, filtros)


def test_palavra_chave_casa_dentro_de_html_com_entidades():
    # Remotive/Jobicy mandam HTML cru; o Greenhouse manda escapado duas vezes.
    filtros = FiltrosConfig(palavras_chave=["inteligencia artificial"])
    cru = _vaga(titulo="Analista", descricao="<p>Intelig&ecirc;ncia Artificial</p>")
    escapado = _vaga(titulo="Analista", descricao="&lt;p&gt;Intelig&amp;ecirc;ncia Artificial&lt;/p&gt;")
    assert vaga_passa_filtro(cru, filtros)
    assert vaga_passa_filtro(escapado, filtros)


def test_asterisco_casa_variacoes_da_palavra():
    filtros = FiltrosConfig(palavras_chave=["desenvolvedor*", "software engineer*"])
    assert vaga_passa_filtro(_vaga(titulo="Desenvolvedora Back-end", descricao=""), filtros)
    assert vaga_passa_filtro(_vaga(titulo="Vaga para desenvolvedores", descricao=""), filtros)
    assert vaga_passa_filtro(_vaga(titulo="Software Engineering Lead", descricao=""), filtros)


def test_sem_asterisco_continua_exigindo_a_palavra_inteira():
    filtros = FiltrosConfig(palavras_chave=["desenvolvedor"])
    assert not vaga_passa_filtro(_vaga(titulo="Desenvolvedora Back-end", descricao=""), filtros)


def test_termo_terminado_em_simbolo_casa():
    filtros = FiltrosConfig(palavras_chave=["c++"])
    assert vaga_passa_filtro(_vaga(titulo="Dev C++ embarcado", descricao=""), filtros)


# --- remoto inferido: fontes que não informam o regime ---


def test_remoto_desconhecido_com_remoto_no_titulo_passa_pelo_filtro_de_local():
    # o caso dos repositórios de vagas do GitHub: remoto=None, sem citar Brasília.
    filtros = FiltrosConfig(palavras_chave=["python"], localizacao=["brasilia"])
    vaga = _vaga(titulo="[Remoto] Desenvolvedor Python Pleno", descricao="stack Django", remoto=None, localizacao=None)
    assert vaga_passa_filtro(vaga, filtros)


def test_remoto_desconhecido_sem_sinal_de_remoto_ainda_exige_a_regiao():
    filtros = FiltrosConfig(localizacao=["brasilia"])
    vaga = _vaga(titulo="Dev Python", descricao="presencial em Recife", remoto=None, localizacao=None)
    assert not vaga_passa_filtro(vaga, filtros)


def test_remoto_false_explicito_nao_e_sobrescrito_pelo_titulo():
    filtros = FiltrosConfig(localizacao=["brasilia"])
    vaga = _vaga(titulo="Ex-remoto, agora presencial", descricao="", remoto=False, localizacao="Recife")
    assert not vaga_passa_filtro(vaga, filtros)


# --- remoto com restrição de país ---

_REMOTO_ACEITO = ["brasil", "brazil", "latam", "worldwide", "anywhere"]


def test_remota_restrita_a_outro_pais_e_rejeitada():
    filtros = FiltrosConfig(localizacao=["brasilia"], remoto_aceito=_REMOTO_ACEITO)
    vaga = _vaga(remoto=True, localizacao="USA")
    assert not vaga_passa_filtro(vaga, filtros)


def test_remota_aceita_quando_a_restricao_inclui_o_brasil():
    filtros = FiltrosConfig(localizacao=["brasilia"], remoto_aceito=_REMOTO_ACEITO)
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao="Argentina,  Brazil"), filtros)
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao="APAC, EMEA, LATAM, USA"), filtros)


def test_remota_sem_restricao_declarada_passa():
    filtros = FiltrosConfig(localizacao=["brasilia"], remoto_aceito=_REMOTO_ACEITO)
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao=None), filtros)
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao="Remoto"), filtros)
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao="Remote - "), filtros)


def test_remota_restrita_a_regiao_configurada_passa():
    filtros = FiltrosConfig(localizacao=["brasilia"], remoto_aceito=_REMOTO_ACEITO)
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao="Remoto - Brasília"), filtros)


def test_remota_restrita_sem_remoto_aceito_configurado_passa_como_antes():
    filtros = FiltrosConfig(localizacao=["brasilia"])
    assert vaga_passa_filtro(_vaga(remoto=True, localizacao="USA"), filtros)


def test_config_real_aceita_as_vagas_que_antes_eram_descartadas():
    # regressão da auditoria: com o config.yaml versionado, vagas típicas dos
    # repositórios brasileiros precisam passar.
    from pathlib import Path

    from monitor.config import carregar_config

    filtros = carregar_config(Path(__file__).resolve().parents[1] / "config.yaml").filtros
    casos = [
        _vaga(titulo="[Remoto] Desenvolvedor Python Pleno", descricao="Django", remoto=None, localizacao=None),
        _vaga(titulo="Desenvolvedora Back-end", descricao="Node e Go", remoto=True, localizacao=None),
        _vaga(titulo="Engenheiro de Software Pleno", descricao="Java", remoto=True, localizacao="Brazil"),
    ]
    for vaga in casos:
        assert vaga_passa_filtro(vaga, filtros), vaga.titulo
    assert not vaga_passa_filtro(
        _vaga(titulo="Security Engineer (Remote - Denmark)", descricao="python", remoto=True, localizacao="Denmark"),
        filtros,
    )


# --- impressão digital: mesma vaga em fontes/anúncios diferentes ---


def test_impressao_digital_ignora_qualificador_de_regime_e_pais():
    a = _vaga(titulo="Security Engineer (Remote - Denmark)", empresa="Acme")
    b = _vaga(titulo="Security Engineer (Remote - Croatia)", empresa="ACME")
    c = _vaga(titulo="[Remoto] Security Engineer", empresa="Acme")
    assert impressao_digital(a) == impressao_digital(b) == impressao_digital(c) == "acme|security engineer"


def test_impressao_digital_mantem_vagas_realmente_diferentes_separadas():
    backend = _vaga(titulo="Software Engineer (Backend)", empresa="Acme")
    frontend = _vaga(titulo="Software Engineer (Frontend)", empresa="Acme")
    outra_empresa = _vaga(titulo="Software Engineer (Backend)", empresa="Globex")
    assert len({impressao_digital(v) for v in (backend, frontend, outra_empresa)}) == 3


def test_sem_empresa_nao_ha_impressao_digital():
    assert impressao_digital(_vaga(titulo="Dev Python Pleno", empresa="")) is None
