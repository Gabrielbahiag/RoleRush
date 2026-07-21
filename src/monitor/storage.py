from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from monitor.models import Vaga

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas_vistas (
    id TEXT PRIMARY KEY,
    visto_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Storage:
    """Persistência de dedup em SQLite: já vi essa vaga antes?"""

    def __init__(self, caminho: str | Path = "vagas.db") -> None:
        self.caminho = Path(caminho)
        with closing(self._conectar()) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def _conectar(self) -> sqlite3.Connection:
        return sqlite3.connect(self.caminho)

    def ja_vista(self, vaga_id: str) -> bool:
        with closing(self._conectar()) as conn:
            cursor = conn.execute("SELECT 1 FROM vagas_vistas WHERE id = ?", (vaga_id,))
            return cursor.fetchone() is not None

    def marcar_como_vista(self, vaga_id: str) -> None:
        with closing(self._conectar()) as conn:
            conn.execute("INSERT OR IGNORE INTO vagas_vistas (id) VALUES (?)", (vaga_id,))
            conn.commit()

    def filtrar_novas(self, vagas: list[Vaga]) -> list[Vaga]:
        return [vaga for vaga in vagas if not self.ja_vista(vaga.id)]

    def marcar_todas(self, vagas: list[Vaga]) -> None:
        with closing(self._conectar()) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO vagas_vistas (id) VALUES (?)",
                [(vaga.id,) for vaga in vagas],
            )
            conn.commit()
