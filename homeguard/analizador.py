"""Análisis de un frame: preproceso bitwise + detectores.

Lo usan el pipeline en vivo y el evaluador de videos (scripts/evaluar_detector.py).
No decide alarmas: devuelve observaciones para el motor de reglas.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import cv2
import numpy as np

from homeguard.config import Config
from homeguard.detectores.base import Contexto, Detector, EstadoCamara, PosibleEvento, Zona
from homeguard.detectores.modelos import Modelos
from homeguard.preproceso import bitwise

log = logging.getLogger(__name__)


def crear_detectores(modelos: Modelos) -> dict[str, Detector]:
    """Instancia todos los detectores disponibles (clave = nombre en config.yaml)."""
    from homeguard.detectores.caidas import DetectorCaidas
    from homeguard.detectores.fuego import DetectorFuego
    from homeguard.detectores.piscina import DetectorPiscina
    from homeguard.detectores.puerta import DetectorPuerta
    from homeguard.detectores.rostros import DetectorRostros

    return {
        "rostros": DetectorRostros(modelos),
        "piscina": DetectorPiscina(),
        "fuego": DetectorFuego(modelos),
        "caidas": DetectorCaidas(modelos),
        "puerta": DetectorPuerta(),
    }


def redimensionar(imagen: np.ndarray, ancho: int) -> np.ndarray:
    alto_o, ancho_o = imagen.shape[:2]
    if ancho_o == ancho:
        return imagen
    alto = round(alto_o * ancho / ancho_o)
    interp = cv2.INTER_AREA if ancho < ancho_o else cv2.INTER_LINEAR
    return cv2.resize(imagen, (ancho, alto), interpolation=interp)


class Analizador:
    def __init__(self, modelos: Modelos, detectores: dict[str, Detector] | None = None) -> None:
        self.modelos = modelos
        self.detectores = detectores if detectores is not None else crear_detectores(modelos)
        self.estados: dict[str, EstadoCamara] = {}
        # permite reemplazar el YOLO general en tests: f(frame) -> sv.Detections
        self.detector_general: Callable[[np.ndarray], Any] | None = None
        self._ultimo_error: dict[str, float] = {}
        self.tiempos_ms: dict[str, float] = {}  # tiempo del último análisis por detector (para el dashboard)

    def reiniciar(self, camara_id: str | None = None) -> None:
        if camara_id is None:
            self.estados.clear()
        else:
            self.estados.pop(camara_id, None)
        for d in self.detectores.values():
            d.reiniciar(camara_id)

    def _detectar_general(self, estado: EstadoCamara, cfg: Config, frame: np.ndarray) -> Any:
        import supervision as sv

        if self.detector_general is not None:
            det = self.detector_general(frame)
        else:
            modelo = self.modelos.yolo(cfg.yolo_general.modelo)
            r = modelo.predict(frame, imgsz=cfg.procesamiento.imgsz_yolo, conf=cfg.yolo_general.confianza,
                               classes=cfg.yolo_general.clases, verbose=False)[0]
            det = sv.Detections.from_ultralytics(r)
        if estado.tracker is None:
            estado.tracker = sv.ByteTrack(frame_rate=int(cfg.procesamiento.fps_objetivo))
        return estado.tracker.update_with_detections(det)

    def analizar(self, camara_id: str, imagen: np.ndarray, t: float, cfg: Config, zonas: list[Zona],
                 nombres_detectores: list[str], hora: datetime | None = None) -> tuple[Contexto, list[PosibleEvento]]:
        frame = redimensionar(imagen, cfg.procesamiento.ancho_proceso)
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        estado = self.estados.setdefault(camara_id, EstadoCamara(camara_id))

        movimiento = None
        if estado.gris_anterior is not None and estado.gris_anterior.shape == gris.shape:
            movimiento = bitwise.mascara_movimiento_xor(estado.gris_anterior, gris, cfg.preproceso.bits_movimiento,
                                                        cfg.preproceso.apertura_movimiento_px)
        ctx = Contexto(camara_id=camara_id, frame=frame, t=t, cfg=cfg, zonas=zonas, estado=estado, gris=gris,
                       mascara_movimiento=movimiento, frame_original=imagen, hora=hora,
                       detector_general=lambda f: self._detectar_general(estado, cfg, f))

        observaciones: list[PosibleEvento] = []
        for nombre in nombres_detectores:
            detector = self.detectores.get(nombre)
            if detector is None:
                continue
            inicio = time.perf_counter()
            try:
                observaciones.extend(detector.procesar(frame, ctx))
            except Exception:  # noqa: BLE001 - un detector roto no puede tirar abajo a los demás
                ahora = time.time()
                if ahora - self._ultimo_error.get(nombre, 0) > 10:  # no inundar el log
                    self._ultimo_error[nombre] = ahora
                    log.exception("Error en el detector %s (cámara %s)", nombre, camara_id)
            self.tiempos_ms[nombre] = (time.perf_counter() - inicio) * 1000
        estado.gris_anterior = gris
        estado.indice += 1
        return ctx, observaciones
