"""Conexión a SQLite y helpers de sesión.

SQLite se usa desde varios hilos (procesamiento, Telegram, servidor web):
check_same_thread=False + modo WAL + busy_timeout evitan bloqueos en la demo.
Cada operación abre y cierra su propia sesión con `with bd.sesion() as s:`.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from homeguard.db.modelos import Base


class BaseDatos:
    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)
        if str(ruta) != ":memory:":
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{self.ruta.as_posix()}"
        else:
            url = "sqlite://"
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})
        event.listen(self.engine, "connect", self._pragmas)
        self._fabrica = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _pragmas(conexion, _registro) -> None:  # noqa: ANN001
        cur = conexion.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    @contextmanager
    def sesion(self) -> Iterator[Session]:
        s = self._fabrica()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def cerrar(self) -> None:
        self.engine.dispose()
