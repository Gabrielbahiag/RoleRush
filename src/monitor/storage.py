from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from monitor.models import Vaga

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas_vistas (
    id TEXT PRIMARY KEY,
    visto_em TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_visto TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# snapshot das vagas notificadas, pra `rolerush curriculo --vaga <id>` achar a
# descrição depois. Guarda só o que a adaptação de currículo usa.
_SCHEMA_DETALHES = """
CREATE TABLE IF NOT EXISTS vagas_detalhes (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL DEFAULT '',
    empresa TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    fonte TEXT NOT NULL DEFAULT '',
    localizacao TEXT,
    descricao TEXT NOT NULL DEFAULT '',
    salvo_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_UPSERT_DETALHES = """
INSERT INTO vagas_detalhes (id, titulo, empresa, url, fonte, localizacao, descricao, salvo_em)
VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
ON CONFLICT(id) DO UPDATE SET
    titulo = excluded.titulo,
    empresa = excluded.empresa,
    url = excluded.url,
    fonte = excluded.fonte,
    localizacao = excluded.localizacao,
    descricao = excluded.descricao,
    salvo_em = excluded.salvo_em
"""

# upsert: numa vaga nova, visto_em e ultimo_visto nascem iguais (via DEFAULT
# da coluna); numa vaga que reaparece, só ultimo_visto avança — visto_em
# (primeiro avistamento) nunca muda depois de gravado.
_UPSERT = """
INSERT INTO vagas_vistas (id, ultimo_visto) VALUES (?, datetime('now'))
ON CONFLICT(id) DO UPDATE SET ultimo_visto = excluded.ultimo_visto
"""


class Storage:
    """Persistência de dedup em SQLite: já vi essa vaga antes?

    `visto_em` é a primeira vez que a vaga apareceu; `ultimo_visto` é
    atualizado toda vez que ela reaparece numa execução seguinte. A poda em
    `remover_vistas_antigas` usa `ultimo_visto`, não `visto_em` — uma vaga
    vista em toda execução nunca é podada, por mais antigo que seja o
    primeiro avistamento. Todas as datas são UTC (`datetime('now')` do
    SQLite já é UTC por padrão).
    """

    def __init__(self, caminho: str | Path = "vagas.db") -> None:
        self.caminho = Path(caminho)
        with closing(self._conectar()) as conn:
            conn.execute(_SCHEMA)
            # tabela nova: o CREATE ... IF NOT EXISTS já é a migração segura,
            # não mexe em nada do que o banco antigo tem.
            conn.execute(_SCHEMA_DETALHES)
            self._migrar_ultimo_visto(conn)
            conn.commit()

    def _conectar(self) -> sqlite3.Connection:
        return sqlite3.connect(self.caminho)

    def _migrar_ultimo_visto(self, conn: sqlite3.Connection) -> None:
        colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(vagas_vistas)")}
        if "ultimo_visto" in colunas:
            return
        # vagas.db gravado antes dessa versão não tem a coluna. Ao migrar,
        # tratamos os registros existentes como "vistos agora" — é a opção
        # segura: evita que tudo que já estava no banco seja podado (e
        # portanto renotificado) no primeiro prune logo após a migração.
        conn.execute("ALTER TABLE vagas_vistas ADD COLUMN ultimo_visto TEXT")
        conn.execute("UPDATE vagas_vistas SET ultimo_visto = datetime('now') WHERE ultimo_visto IS NULL")

    def ja_vista(self, vaga_id: str) -> bool:
        with closing(self._conectar()) as conn:
            cursor = conn.execute("SELECT 1 FROM vagas_vistas WHERE id = ?", (vaga_id,))
            return cursor.fetchone() is not None

    def marcar_como_vista(self, vaga_id: str) -> None:
        with closing(self._conectar()) as conn:
            conn.execute(_UPSERT, (vaga_id,))
            conn.commit()

    def filtrar_novas(self, vagas: list[Vaga]) -> list[Vaga]:
        return [vaga for vaga in vagas if not self.ja_vista(vaga.id)]

    def marcar_todas(self, vagas: list[Vaga]) -> None:
        with closing(self._conectar()) as conn:
            conn.executemany(_UPSERT, [(vaga.id,) for vaga in vagas])
            conn.commit()

    def remover_vistas_antigas(self, dias: int) -> int:
        """Remove do histórico de dedup os registros não vistos há mais de `dias`.

        Poda por `ultimo_visto`: uma vaga que continua sendo retornada pela
        fonte em toda execução nunca é removida, mesmo que o primeiro
        avistamento (`visto_em`) seja muito mais antigo que `dias`. Uma vaga
        removida daqui volta a ser tratada como "nova" se a fonte ainda a
        retornar — trade-off aceito em troca de um banco limitado.
        """
        with closing(self._conectar()) as conn:
            cursor = conn.execute(
                "DELETE FROM vagas_vistas WHERE ultimo_visto < datetime('now', ?)",
                (f"-{dias} days",),
            )
            # a retenção vale também pro snapshot: detalhe sem vaga vista
            # correspondente é lixo.
            conn.execute("DELETE FROM vagas_detalhes WHERE id NOT IN (SELECT id FROM vagas_vistas)")
            conn.commit()
            return cursor.rowcount

    def salvar_detalhes(self, vagas: list[Vaga]) -> None:
        """Guarda o snapshot das vagas notificadas (idempotente)."""
        with closing(self._conectar()) as conn:
            conn.executemany(
                _UPSERT_DETALHES,
                [
                    (
                        vaga.id,
                        vaga.titulo,
                        vaga.empresa,
                        vaga.url,
                        vaga.fonte,
                        vaga.localizacao,
                        vaga.descricao,
                    )
                    for vaga in vagas
                ],
            )
            conn.commit()

    def buscar_detalhes(self, vaga_id: str) -> Vaga | None:
        with closing(self._conectar()) as conn:
            linha = conn.execute(
                "SELECT id, titulo, empresa, url, fonte, localizacao, descricao "
                "FROM vagas_detalhes WHERE id = ?",
                (vaga_id,),
            ).fetchone()

        if linha is None:
            return None
        return Vaga(
            id=linha[0],
            titulo=linha[1],
            empresa=linha[2],
            url=linha[3],
            fonte=linha[4],
            localizacao=linha[5],
            descricao=linha[6],
        )
