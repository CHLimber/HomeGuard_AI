"""Registro de eventos: foto en data/eventos/ y fila en la tabla evento."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sqlalchemy import select, update

from homeguard.db.modelos import Evento
from homeguard.db.sesion import BaseDatos

log = logging.getLogger(__name__)


def codificar_jpeg(frame: np.ndarray, ancho: int, calidad: int) -> bytes:
    """Reduce el frame a `ancho` px (si es más grande) y lo codifica en JPEG."""
    alto_orig, ancho_orig = frame.shape[:2]
    if ancho_orig > ancho:
        frame = cv2.resize(frame, (ancho, round(alto_orig * ancho / ancho_orig)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(calidad)])
    if not ok:
        raise RuntimeError("no se pudo codificar el JPEG")
    return buf.tobytes()


class Registro:
    def __init__(self, bd: BaseDatos, carpeta_eventos: Path) -> None:
        self.bd = bd
        self.carpeta = Path(carpeta_eventos)
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def guardar_foto(self, evento_id: str, foto_jpeg: bytes) -> str:
        nombre = f"{evento_id}.jpg"
        (self.carpeta / nombre).write_bytes(foto_jpeg)
        return nombre

    def guardar_evento(self, *, evento_id: str, tipo: str, camara_id: str, zona: str, confianza: float,
                       detalle: dict[str, Any], foto: str | None, t_deteccion: float,
                       telegram_estado: str) -> dict[str, Any]:
        with self.bd.sesion() as s:
            ev = Evento(id=evento_id, tipo=tipo, camara_id=camara_id, zona=zona, confianza=float(confianza),
                        detalle=detalle, foto=foto, t_deteccion=t_deteccion,
                        telegram_estado=telegram_estado)
            s.add(ev)
            s.flush()
            return ev.a_dict()

    def registrar_latencia_panel(self, evento_id: str, ahora: float | None = None) -> float | None:
        """Guarda la latencia detección -> ack del panel (solo el primer ack cuenta). Devuelve ms."""
        ahora = time.time() if ahora is None else ahora
        with self.bd.sesion() as s:
            ev = s.get(Evento, evento_id)
            if ev is None or ev.latencia_panel_ms is not None:
                return None
            ev.latencia_panel_ms = (ahora - ev.t_deteccion) * 1000.0
            return ev.latencia_panel_ms

    def registrar_telegram(self, evento_id: str, latencia_ms: float | None, estado: str) -> None:
        with self.bd.sesion() as s:
            ev = s.get(Evento, evento_id)
            if ev is not None:
                ev.telegram_estado = estado
                if latencia_ms is not None:
                    ev.latencia_telegram_ms = latencia_ms

    def marcar_silenciados(self) -> None:
        with self.bd.sesion() as s:
            s.execute(update(Evento).where(Evento.silenciado.is_(False)).values(silenciado=True))

    def pendientes_telegram(self, max_edad_min: float) -> list[Evento]:
        limite = time.time() - max_edad_min * 60
        with self.bd.sesion() as s:
            return list(s.scalars(select(Evento).where(
                Evento.telegram_estado == "pendiente", Evento.t_deteccion >= limite).order_by(Evento.t_deteccion)))

    def ruta_foto(self, nombre: str | None) -> Path | None:
        return None if not nombre else self.carpeta / nombre
