"""Anomalía 5: puerta abierta fuera del horario permitido.

Se compara la zona "puerta" con una imagen de referencia de la puerta cerrada:
  - método "absdiff": |gris - referencia| > umbral_diferencia
  - método "xor":     binarizar(gris) XOR binarizar(referencia)
Si más del `porcentaje_min` % de los píxeles de la zona cambió durante
`duracion_min_s` segundos y la hora está fuera de `horarios_permitidos`,
la observación es positiva.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import cv2
import numpy as np

from homeguard.config import ruta_abs
from homeguard.detectores.base import Anotacion, Contexto, Detector, PosibleEvento, Zona
from homeguard.preproceso import bitwise

log = logging.getLogger(__name__)


def en_horario(hora: datetime, rangos: list[str]) -> bool:
    """¿La hora cae dentro de alguno de los rangos 'HH:MM-HH:MM'? Soporta rangos que cruzan medianoche."""
    actual = hora.time()
    for rango in rangos:
        ini_txt, fin_txt = rango.split("-")
        ini = time(*map(int, ini_txt.split(":")))
        fin = time(*map(int, fin_txt.split(":")))
        if ini <= fin:
            if ini <= actual <= fin:
                return True
        elif actual >= ini or actual <= fin:  # ej. 22:00-06:00
            return True
    return False


@dataclass
class _EstadoZona:
    referencia: np.ndarray            # gris (ya desenfocado) del recorte de la zona, puerta cerrada
    origen: str                       # "archivo:<ruta>@<mtime>" o "automatica"
    umbral_bin: float = 0.0           # umbral de binarización fijado sobre la referencia (método xor)
    t_inicio_cambio: float | None = None


class DetectorPuerta(Detector):
    nombre = "puerta"
    tipo = "puerta"

    def __init__(self) -> None:
        self._estados: dict[tuple[str, int], _EstadoZona] = {}

    def reiniciar(self, camara_id: str | None = None) -> None:
        if camara_id is None:
            self._estados.clear()
        else:
            self._estados = {k: v for k, v in self._estados.items() if k[0] != camara_id}

    # -- referencia -----------------------------------------------------------

    @staticmethod
    def _preparar(gris: np.ndarray, desenfoque: int) -> np.ndarray:
        if desenfoque > 0:
            k = desenfoque | 1  # el kernel tiene que ser impar: OR con 1 enciende el bit 0
            gris = cv2.GaussianBlur(gris, (k, k), 0)
        return gris

    def _estado_zona(self, ctx: Contexto, zona: Zona, recorte: np.ndarray, desenfoque: int) -> _EstadoZona | None:
        clave = (ctx.camara_id, zona.id)
        estado = self._estados.get(clave)
        origen_archivo = None
        if zona.referencia:
            ruta = ruta_abs(zona.referencia)
            if ruta.exists():
                origen_archivo = f"archivo:{ruta}@{ruta.stat().st_mtime}"
        if estado is not None and (origen_archivo is None or estado.origen == origen_archivo):
            return estado
        if origen_archivo is not None:
            ref_completa = cv2.imread(str(ruta_abs(zona.referencia)), cv2.IMREAD_GRAYSCALE)
            if ref_completa is not None:
                ref_completa = cv2.resize(ref_completa, (ctx.ancho, ctx.alto))
                x0, y0, x1, y1 = bitwise.bbox_poligono(zona.puntos_px(ctx.ancho, ctx.alto), ctx.alto, ctx.ancho)
                ref = self._preparar(ref_completa[y0:y1, x0:x1], desenfoque)
                estado = _EstadoZona(ref, origen_archivo)
                log.info("Puerta '%s' (%s): referencia cargada de %s", zona.nombre, ctx.camara_id, Path(zona.referencia).name)
        if estado is None:
            if not ctx.cfg.detectores.puerta.referencia_automatica:
                return None
            estado = _EstadoZona(recorte.copy(), "automatica")
            log.info("Puerta '%s' (%s): sin referencia capturada, se usa el primer frame", zona.nombre, ctx.camara_id)
        estado.umbral_bin, _ = cv2.threshold(estado.referencia, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        self._estados[clave] = estado
        return estado

    # -- análisis -------------------------------------------------------------

    def procesar(self, frame: np.ndarray, ctx: Contexto) -> list[PosibleEvento]:
        cfg = ctx.cfg.detectores.puerta
        eventos: list[PosibleEvento] = []
        permitido = en_horario(ctx.hora, cfg.horarios_permitidos)
        for zona in ctx.zonas_de_tipo("puerta"):
            pts = zona.puntos_px(ctx.ancho, ctx.alto)
            x0, y0, x1, y1 = bitwise.bbox_poligono(pts, ctx.alto, ctx.ancho)
            if x1 - x0 < 2 or y1 - y0 < 2:
                continue
            roi = ctx.mascara_zona(zona)[y0:y1, x0:x1]
            recorte = self._preparar(ctx.gris[y0:y1, x0:x1], cfg.desenfoque_px)
            estado = self._estado_zona(ctx, zona, recorte, cfg.desenfoque_px)
            if estado is None:
                continue
            if estado.referencia.shape != recorte.shape:  # la zona cambió de tamaño: nueva referencia
                self._estados.pop((ctx.camara_id, zona.id), None)
                continue

            if cfg.metodo == "xor":
                umbral = cfg.umbral_binarizacion or estado.umbral_bin
                _, b_ref = cv2.threshold(estado.referencia, umbral, 255, cv2.THRESH_BINARY)
                _, b_act = cv2.threshold(recorte, umbral, 255, cv2.THRESH_BINARY)
                cambio = bitwise.xor_binarizadas(b_ref, b_act)
            else:
                _, cambio = cv2.threshold(cv2.absdiff(recorte, estado.referencia), cfg.umbral_diferencia, 255,
                                          cv2.THRESH_BINARY)
            porcentaje = bitwise.porcentaje_activos(cambio, roi)

            if porcentaje >= cfg.porcentaje_min:
                if estado.t_inicio_cambio is None:
                    estado.t_inicio_cambio = ctx.t
                duracion = ctx.t - estado.t_inicio_cambio
            else:
                estado.t_inicio_cambio = None
                duracion = 0.0
            abierta = estado.t_inicio_cambio is not None and duracion >= cfg.duracion_min_s
            activo = abierta and not permitido

            ctx.calibracion.setdefault("puerta", {})[zona.nombre] = {
                "porcentaje_cambiado": round(porcentaje, 1),
                "umbral_porcentaje": cfg.porcentaje_min,
                "segundos_abierta": round(duracion, 1),
                "en_horario_permitido": permitido,
            }
            ctx.anotaciones.append(Anotacion((x0, y0, x1, y1), f"{zona.nombre} {porcentaje:.0f}% {duracion:.1f}s", activo))
            eventos.append(PosibleEvento(
                tipo=self.tipo, camara_id=ctx.camara_id, zona=zona.nombre, activo=activo, t=ctx.t,
                confianza=min(1.0, porcentaje / 100.0),
                detalle={"porcentaje": round(porcentaje, 1), "duracion_s": round(duracion, 1),
                         "horario_permitido": permitido, "metodo": cfg.metodo},
                bbox=(x0, y0, x1, y1),
            ))
        return eventos

    def referencia_actual(self, camara_id: str, zona_id: int) -> np.ndarray | None:
        estado = self._estados.get((camara_id, zona_id))
        return None if estado is None else estado.referencia
