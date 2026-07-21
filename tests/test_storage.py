from monitor.models import Vaga
from monitor.storage import Storage


def _vaga(vaga_id: str) -> Vaga:
    return Vaga(id=vaga_id, titulo="t", empresa="e", url="u", fonte="f")


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
