import sqlite3
from datetime import UTC, datetime, timedelta

from monitor.models import Vaga
from monitor.storage import Storage


def _vaga(vaga_id: str) -> Vaga:
    return Vaga(id=vaga_id, titulo="t", empresa="e", url="u", fonte="f")


def _fmt(quando: datetime) -> str:
    return quando.strftime("%Y-%m-%d %H:%M:%S")


def _inserir_com_data(
    caminho, vaga_id: str, visto_em: datetime, ultimo_visto: datetime | None = None
) -> None:
    if ultimo_visto is None:
        ultimo_visto = visto_em
    with sqlite3.connect(caminho) as conn:
        conn.execute(
            "INSERT INTO vagas_vistas (id, visto_em, ultimo_visto) VALUES (?, ?, ?)",
            (vaga_id, _fmt(visto_em), _fmt(ultimo_visto)),
        )


def test_vaga_nova_nao_esta_vista(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    assert not storage.ja_vista("1")


def test_marcar_como_vista(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.marcar_como_vista("1")
    assert storage.ja_vista("1")


def test_filtrar_novas_ignora_ja_vistas(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.marcar_como_vista("1")
    novas = storage.filtrar_novas([_vaga("1"), _vaga("2")])
    assert [vaga.id for vaga in novas] == ["2"]


def test_marcar_todas_e_idempotente(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    vagas = [_vaga("1"), _vaga("2")]
    storage.marcar_todas(vagas)
    storage.marcar_todas(vagas)  # rodar duas vezes não pode quebrar nem duplicar
    assert storage.ja_vista("1")
    assert storage.ja_vista("2")


def test_storage_persiste_entre_instancias(tmp_path):
    caminho = tmp_path / "db.sqlite"
    Storage(caminho).marcar_como_vista("1")
    assert Storage(caminho).ja_vista("1")


def test_remover_vistas_antigas_remove_so_o_que_passou_do_limite(tmp_path):
    caminho = tmp_path / "db.sqlite"
    storage = Storage(caminho)  # cria o schema
    agora = datetime.now(UTC)
    _inserir_com_data(caminho, "antiga:1", agora - timedelta(days=120))
    _inserir_com_data(caminho, "recente:1", agora - timedelta(days=10))

    removidas = storage.remover_vistas_antigas(dias=90)

    assert removidas == 1
    assert storage.ja_vista("antiga:1") is False
    assert storage.ja_vista("recente:1") is True


def test_remover_vistas_antigas_nao_quebra_dedup_de_vagas_recentes(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.marcar_como_vista("hoje:1")

    storage.remover_vistas_antigas(dias=90)

    assert storage.ja_vista("hoje:1") is True


def test_remover_vistas_antigas_sem_registros_antigos_nao_remove_nada(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.marcar_como_vista("1")
    storage.marcar_como_vista("2")

    removidas = storage.remover_vistas_antigas(dias=90)

    assert removidas == 0
    assert storage.ja_vista("1") is True
    assert storage.ja_vista("2") is True


def test_vaga_vista_continuamente_nao_e_removida_nem_precisa_ser_renotificada(tmp_path):
    """Reproduz o bug: poda deve olhar quando a vaga foi vista PELA ÚLTIMA
    VEZ, não quando foi vista PELA PRIMEIRA VEZ. Uma vaga que apareceu há
    120 dias mas segue aparecendo em toda execução (viu de novo ontem) não
    pode ser podada nem tratada como nova de novo."""
    caminho = tmp_path / "db.sqlite"
    storage = Storage(caminho)
    agora = datetime.now(UTC)

    _inserir_com_data(
        caminho,
        "sempre-ativa:1",
        visto_em=agora - timedelta(days=120),
        ultimo_visto=agora - timedelta(days=1),
    )

    removidas = storage.remover_vistas_antigas(dias=90)

    assert removidas == 0
    assert storage.ja_vista("sempre-ativa:1") is True


def test_reaparecer_atualiza_ultimo_visto_sem_mudar_a_data_de_primeiro_avistamento(tmp_path):
    caminho = tmp_path / "db.sqlite"
    storage = Storage(caminho)
    agora = datetime.now(UTC)
    _inserir_com_data(caminho, "antiga:1", visto_em=agora - timedelta(days=120), ultimo_visto=agora - timedelta(days=120))

    # a vaga reaparece numa nova execução.
    storage.marcar_como_vista("antiga:1")

    # como acabou de reaparecer, não pode ser podada mesmo com dias=1.
    removidas = storage.remover_vistas_antigas(dias=1)
    assert removidas == 0
    assert storage.ja_vista("antiga:1") is True


def test_salvar_e_buscar_detalhes_da_vaga(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    vaga = Vaga(
        id="remotive:1",
        titulo="Dev Python",
        empresa="Acme",
        url="https://exemplo.com/1",
        fonte="remotive",
        localizacao="Remoto",
        descricao="Vaga de backend em Python.",
    )

    storage.salvar_detalhes([vaga])
    recuperada = storage.buscar_detalhes("remotive:1")

    assert recuperada is not None
    assert recuperada.id == vaga.id
    assert recuperada.titulo == vaga.titulo
    assert recuperada.empresa == vaga.empresa
    assert recuperada.url == vaga.url
    assert recuperada.fonte == vaga.fonte
    assert recuperada.localizacao == vaga.localizacao
    assert recuperada.descricao == vaga.descricao


def test_buscar_detalhes_de_vaga_desconhecida_devolve_none(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")

    assert storage.buscar_detalhes("nao-existe:1") is None


def test_salvar_detalhes_e_idempotente_e_atualiza_o_snapshot(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    antes = Vaga(id="x:1", titulo="Título antigo", empresa="Acme", url="u", fonte="f")
    depois = Vaga(id="x:1", titulo="Título novo", empresa="Acme", url="u", fonte="f")

    storage.salvar_detalhes([antes])
    storage.salvar_detalhes([depois])  # rodar de novo não pode duplicar nem quebrar

    recuperada = storage.buscar_detalhes("x:1")
    assert recuperada is not None
    assert recuperada.titulo == "Título novo"


def test_retencao_remove_tambem_os_detalhes_da_vaga_podada(tmp_path):
    caminho = tmp_path / "db.sqlite"
    storage = Storage(caminho)
    agora = datetime.now(UTC)
    _inserir_com_data(caminho, "antiga:1", visto_em=agora - timedelta(days=120))
    storage.salvar_detalhes([Vaga(id="antiga:1", titulo="t", empresa="e", url="u", fonte="f")])

    storage.remover_vistas_antigas(dias=90)

    assert storage.ja_vista("antiga:1") is False
    assert storage.buscar_detalhes("antiga:1") is None


def test_retencao_mantem_detalhes_de_vaga_ainda_vista(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.marcar_como_vista("recente:1")
    storage.salvar_detalhes([Vaga(id="recente:1", titulo="t", empresa="e", url="u", fonte="f")])

    storage.remover_vistas_antigas(dias=90)

    assert storage.buscar_detalhes("recente:1") is not None


def test_migracao_para_tabela_de_detalhes_preserva_dados_existentes(tmp_path):
    caminho = tmp_path / "db.sqlite"
    # banco no formato antigo: só vagas_vistas, sem ultimo_visto e sem a
    # tabela de detalhes — é o vagas.db que está em produção hoje.
    with sqlite3.connect(caminho) as conn:
        conn.execute(
            """
            CREATE TABLE vagas_vistas (
                id TEXT PRIMARY KEY,
                visto_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("INSERT INTO vagas_vistas (id) VALUES ('legado:1')")
        conn.commit()

    storage = Storage(caminho)

    assert storage.ja_vista("legado:1") is True  # dedup antigo preservado
    storage.salvar_detalhes([Vaga(id="legado:1", titulo="t", empresa="e", url="u", fonte="f")])
    assert storage.buscar_detalhes("legado:1") is not None


def test_migracao_adiciona_coluna_ultimo_visto_em_banco_existente(tmp_path):
    caminho = tmp_path / "db.sqlite"
    # simula um vagas.db no formato anterior a essa mudança, sem a coluna
    # ultimo_visto — é o que existe hoje em produção.
    with sqlite3.connect(caminho) as conn:
        conn.execute(
            """
            CREATE TABLE vagas_vistas (
                id TEXT PRIMARY KEY,
                visto_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO vagas_vistas (id, visto_em) VALUES (?, ?)",
            ("legado:1", _fmt(datetime.now(UTC) - timedelta(days=120))),
        )
        conn.commit()

    storage = Storage(caminho)  # deve migrar o schema sem quebrar o banco existente

    assert storage.ja_vista("legado:1") is True
    # migração trata registros existentes como "vistos agora" — evita que
    # tudo que já estava no banco seja removido/renotificado no primeiro
    # prune logo após a migração.
    removidas = storage.remover_vistas_antigas(dias=90)
    assert removidas == 0
    assert storage.ja_vista("legado:1") is True
