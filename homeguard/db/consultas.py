"""Lecturas de la BD que comparten el sistema en vivo y los scripts (evaluador, reportes)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select

from homeguard.config import Config, cargar_config
from homeguard.db import modelos as m
from homeguard.db.sesion import BaseDatos
from homeguard.detectores.base import Zona

# Claves de la tabla `config` que guardan estado del sistema y no son overrides de config.yaml.
# Empiezan con "_" para que nunca se validen contra Config ni se borren al restaurar config.yaml.
PREFIJO_INTERNO = "_"
CLAVE_ARMADO = "_sistema.armado"


def leer_overrides(bd: BaseDatos) -> dict[str, Any]:
    with bd.sesion() as s:
        return {o.clave: o.valor for o in s.scalars(select(m.ConfigOverride))
                if not o.clave.startswith(PREFIJO_INTERNO)}


def leer_armado(bd: BaseDatos) -> bool:
    """Si el sistema está armado. Sin dato guardado, arranca armado."""
    with bd.sesion() as s:
        fila = s.get(m.ConfigOverride, CLAVE_ARMADO)
        return True if fila is None else bool(fila.valor)


def guardar_armado(bd: BaseDatos, armado: bool) -> None:
    with bd.sesion() as s:
        s.merge(m.ConfigOverride(clave=CLAVE_ARMADO, valor=armado))


def config_efectiva(bd: BaseDatos, ruta_config: Path, demo: bool = False) -> tuple[Config, str | None]:
    """config.yaml + overrides del dashboard. Si los overrides son inválidos se ignoran (devuelve el error)."""
    try:
        return cargar_config(ruta_config, leer_overrides(bd), demo=demo), None
    except Exception as e:  # noqa: BLE001
        return cargar_config(ruta_config, demo=demo), str(e)


def zonas_de_camara(bd: BaseDatos, camara_id: str) -> list[Zona]:
    with bd.sesion() as s:
        filas = s.scalars(select(m.Zona).where(m.Zona.camara_id == camara_id).order_by(m.Zona.id))
        return [Zona(id=z.id, camara_id=z.camara_id, nombre=z.nombre, tipo=z.tipo, puntos=z.puntos,
                     referencia=z.referencia) for z in filas]


def embeddings_residentes(bd: BaseDatos) -> tuple[np.ndarray, list[str]]:
    """Matriz (n, 128) con todos los vectores de rostro y el nombre del residente de cada fila."""
    with bd.sesion() as s:
        filas = s.execute(select(m.EmbeddingRostro.vector, m.Residente.nombre)
                          .join(m.Residente, m.Residente.id == m.EmbeddingRostro.residente_id)).all()
    if not filas:
        return np.zeros((0, 128), np.float32), []
    return np.stack([np.frombuffer(v, dtype=np.float32) for v, _ in filas]), [n for _, n in filas]


def eventos(bd: BaseDatos, desde: datetime | None = None) -> list[m.Evento]:
    """Eventos registrados (opcionalmente desde una fecha), del más viejo al más nuevo."""
    q = select(m.Evento).order_by(m.Evento.creado_en)
    if desde is not None:
        q = q.where(m.Evento.creado_en >= desde)
    with bd.sesion() as s:
        return list(s.scalars(q))
