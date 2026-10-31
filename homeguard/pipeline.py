"""Hilo de procesamiento: cámaras -> análisis -> motor de reglas -> salidas.

Un único hilo recorre las cámaras activas, analiza el frame más reciente de
cada una (si hay uno nuevo), pasa las observaciones al motor de reglas y
despacha las alarmas confirmadas. Además produce el JPEG anotado del stream y
la telemetría (FPS, CPU, valores de calibración) para el dashboard.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

import cv2
import psutil

from homeguard.analizador import Analizador
from homeguard.anotador import anotar

if TYPE_CHECKING:
    from homeguard.sistema import Sistema

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, sistema: Sistema) -> None:
        self.sistema = sistema
        self.analizador = Analizador(sistema.modelos)
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None
        self._ultimo_numero: dict[str, int] = {}
        self._tiempos: dict[str, deque[float]] = {}
        self.jpeg: dict[str, bytes] = {}           # último frame anotado por cámara (stream MJPEG)
        self.jpeg_t: dict[str, float] = {}         # cuándo se generó (para mostrar "sin señal" si es viejo)
        self.calibracion: dict[str, dict] = {}     # valores crudos de los detectores por cámara
        self.fps: dict[str, float] = {}            # FPS de procesamiento por cámara
        self.ms_por_frame: dict[str, float] = {}
        self._proceso = psutil.Process()
        self._proceso.cpu_percent(None)
        psutil.cpu_percent(None)

    # -- ciclo de vida ----------------------------------------------------------

    def iniciar(self) -> None:
        self._hilo = threading.Thread(target=self._bucle, name="procesamiento", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._detener.set()
        if self._hilo:
            self._hilo.join(timeout=5)

    # -- bucle ------------------------------------------------------------------

    def _bucle(self) -> None:
        t_telemetria = 0.0
        while not self._detener.is_set():
            try:
                t_telemetria = self._ciclo(t_telemetria)
            except Exception:  # noqa: BLE001 - el hilo de procesamiento nunca debe morir
                log.exception("Error inesperado en el ciclo de procesamiento; se continúa")
                self._detener.wait(1.0)

    def _ciclo(self, t_telemetria: float) -> float:
        """Una vuelta por todas las cámaras. Devuelve el instante de la última telemetría enviada."""
        cfg = self.sistema.config
        periodo = 1.0 / cfg.procesamiento.fps_objetivo
        inicio = time.time()
        for cam in list(self.sistema.camaras.camaras.values()):
            capturado = cam.leer()
            if capturado is None or capturado.numero == self._ultimo_numero.get(cam.id):
                continue
            self._ultimo_numero[cam.id] = capturado.numero
            try:
                self.procesar(cam.id, capturado.imagen, cam.cfg.detectores, cam.cfg.nombre,
                              fuente_estatica=cam.tipo_fuente == "imagenes")
            except Exception:  # noqa: BLE001 - una cámara con problemas no frena a las demás
                log.exception("Error procesando la cámara %s", cam.id)
        if inicio - t_telemetria >= cfg.procesamiento.intervalo_telemetria_s:
            t_telemetria = inicio
            self._emitir_telemetria()
        restante = periodo - (time.time() - inicio)
        self._detener.wait(max(restante, 0.005))
        return t_telemetria

    def procesar(self, camara_id: str, imagen, detectores: list[str], nombre: str,
                 fuente_estatica: bool = False) -> list:
        """Analiza un frame de una cámara y despacha las alarmas que confirme el motor."""
        cfg = self.sistema.config
        t = time.time()
        zonas = self.sistema.zonas(camara_id)
        ctx, observaciones = self.analizador.analizar(camara_id, imagen, t, cfg, zonas, detectores,
                                                      fuente_estatica=fuente_estatica)
        disparos = self.sistema.motor.procesar(observaciones)

        tiempos = self._tiempos.setdefault(camara_id, deque(maxlen=20))
        tiempos.append(t)
        if len(tiempos) > 1:
            self.fps[camara_id] = (len(tiempos) - 1) / max(tiempos[-1] - tiempos[0], 1e-6)
        anotado = anotar(ctx.frame, ctx, zonas, nombre, self.fps.get(camara_id, 0.0))
        for d in disparos:
            self.sistema.despachar(d, anotado)
        ok, buf = cv2.imencode(".jpg", anotado, [cv2.IMWRITE_JPEG_QUALITY, cfg.procesamiento.calidad_jpeg_stream])
        if ok:
            self.jpeg[camara_id] = buf.tobytes()
            self.jpeg_t[camara_id] = time.time()
        self.calibracion[camara_id] = ctx.calibracion
        self.ms_por_frame[camara_id] = (time.time() - t) * 1000
        return disparos

    # -- telemetría -------------------------------------------------------------

    def telemetria(self) -> dict[str, Any]:
        s = self.sistema
        camaras = []
        for r in s.camaras.resumen():
            r["fps_proceso"] = round(self.fps.get(r["id"], 0.0), 1)
            r["ms_por_frame"] = round(self.ms_por_frame.get(r["id"], 0.0), 1)
            camaras.append(r)
        return {
            "tipo": "telemetria",
            "estado": s.motor.estado,
            "activos": s.motor.activos,
            "armado": s.motor.armado,
            "camaras": camaras,
            "calibracion": self.calibracion,
            "ms_detectores": {k: round(v, 1) for k, v in self.analizador.tiempos_ms.items()},
            "cpu_sistema": psutil.cpu_percent(None),
            "cpu_proceso": round(self._proceso.cpu_percent(None) / (psutil.cpu_count() or 1), 1),
            "ram_mb": round(self._proceso.memory_info().rss / 1e6),
            "telegram": {"habilitado": s.telegram.habilitado, "pendientes": s.telegram.pendientes,
                         "sin_conexion": s.telegram.sin_conexion, "error": s.telegram.ultimo_error},
            "paneles_conectados": s.ws.cantidad("alarma"),
            "ultimo_evento": s.ultimo_evento,
        }

    def _emitir_telemetria(self) -> None:
        s = self.sistema
        s.ws.emitir_desde_hilo("estado", self.telemetria())
        # el panel recibe el estado periódicamente: sirve de latido y corrige mensajes perdidos
        s.ws.emitir_desde_hilo("alarma", {"tipo": "estado", "estado": s.motor.estado,
                                          "armado": s.motor.armado})
