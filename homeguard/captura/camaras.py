"""Captura de video: un hilo por cámara que guarda solo el último frame.

- Webcam (índice), URL HTTP/MJPEG (IP Webcam, DroidCam) o archivo de video.
- Leer siempre lo más rápido posible y quedarse con el último frame evita que
  el procesamiento trabaje con imágenes viejas (el buffer no se acumula).
- Los archivos se reproducen en bucle a su FPS real, como si fueran cámaras.
- Si la cámara se cae o deja de mandar frames, se reconecta con espera
  exponencial (reintento_inicial_s, x2, ... hasta reintento_max_s).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from homeguard.config import CfgCamara, CfgCaptura, ruta_abs

log = logging.getLogger(__name__)


def resolver_fuente(fuente: int | str) -> tuple[int | str, str]:
    """Devuelve (fuente para cv2, tipo) con tipo en {'webcam', 'url', 'archivo'}."""
    if isinstance(fuente, int):
        return fuente, "webcam"
    texto = str(fuente).strip()
    if texto.isdigit():
        return int(texto), "webcam"
    if texto.lower().startswith(("http://", "https://", "rtsp://")):
        return texto, "url"
    return str(ruta_abs(texto)), "archivo"


@dataclass
class FrameCapturado:
    imagen: np.ndarray
    t: float       # time.time() de la captura
    numero: int    # contador creciente (para saber si hay frame nuevo)


class Camara:
    def __init__(self, camara_id: str, cfg: CfgCamara, cfg_captura: CfgCaptura) -> None:
        self.id = camara_id
        self.cfg = cfg
        self.cfg_captura = cfg_captura
        self.fuente, self.tipo_fuente = resolver_fuente(cfg.fuente)
        self._lock = threading.Lock()
        self._ultimo: FrameCapturado | None = None
        self._contador = 0
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None
        self.conectada = False
        self.error: str | None = None
        self.fps = 0.0
        self.reconexiones = 0

    # -- API ---------------------------------------------------------------------

    def iniciar(self) -> None:
        self._hilo = threading.Thread(target=self._bucle, name=f"captura-{self.id}", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._detener.set()
        if self._hilo:
            self._hilo.join(timeout=3)

    def leer(self) -> FrameCapturado | None:
        with self._lock:
            return self._ultimo

    def resumen(self) -> dict:
        ultimo = self._ultimo
        return {
            "id": self.id, "nombre": self.cfg.nombre, "fuente": str(self.cfg.fuente), "tipo": self.tipo_fuente,
            "conectada": self.conectada, "fps_captura": round(self.fps, 1), "error": self.error,
            "reconexiones": self.reconexiones,
            "resolucion": None if ultimo is None else f"{ultimo.imagen.shape[1]}x{ultimo.imagen.shape[0]}",
        }

    # -- internos ----------------------------------------------------------------

    def _abrir(self) -> cv2.VideoCapture:
        if self.tipo_fuente == "url":
            ms = int(self.cfg_captura.timeout_sin_frames_s * 1000)
            cap = cv2.VideoCapture(self.fuente, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, ms])
        elif self.tipo_fuente == "archivo":
            if not Path(self.fuente).exists():
                raise FileNotFoundError(f"no existe el video {self.fuente}")
            cap = cv2.VideoCapture(self.fuente)
        else:
            cap = cv2.VideoCapture(self.fuente)
        if not cap.isOpened():
            cap.release()
            raise ConnectionError(f"no se pudo abrir {self.cfg.fuente}")
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _publicar(self, imagen: np.ndarray) -> None:
        with self._lock:
            self._contador += 1
            self._ultimo = FrameCapturado(imagen, time.time(), self._contador)

    def _bucle(self) -> None:
        espera = self.cfg_captura.reintento_inicial_s
        while not self._detener.is_set():
            try:
                cap = self._abrir()
            except Exception as e:  # noqa: BLE001
                self.conectada = False
                self.error = str(e)
                log.warning("Cámara %s: %s. Reintento en %.0f s", self.id, e, espera)
                self._detener.wait(espera)
                espera = min(espera * 2, self.cfg_captura.reintento_max_s)
                self.reconexiones += 1
                continue

            log.info("Cámara %s conectada (%s)", self.id, self.cfg.fuente)
            self.conectada, self.error = True, None
            espera = self.cfg_captura.reintento_inicial_s
            self._leer_hasta_fallar(cap)
            cap.release()
            self.conectada = False
            if not self._detener.is_set():
                log.warning("Cámara %s: se perdió la señal, reconectando...", self.id)
                self.reconexiones += 1
                self._detener.wait(espera)

    def _leer_hasta_fallar(self, cap: cv2.VideoCapture) -> None:
        es_archivo = self.tipo_fuente == "archivo"
        periodo = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 25.0) if es_archivo else 0.0
        proximo = time.time()
        t_fps, n_fps = time.time(), 0
        ultimo_ok = time.time()
        while not self._detener.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                if es_archivo:  # fin del video: vuelve al principio (bucle)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                    if not ok:
                        self.error = "no se puede leer el video"
                        return
                elif time.time() - ultimo_ok > self.cfg_captura.timeout_sin_frames_s:
                    self.error = "sin frames"
                    return
                else:
                    time.sleep(0.05)
                    continue
            ultimo_ok = time.time()
            self._publicar(frame)
            n_fps += 1
            if ultimo_ok - t_fps >= 1.0:
                self.fps = n_fps / (ultimo_ok - t_fps)
                t_fps, n_fps = ultimo_ok, 0
            if es_archivo:  # reproducir a velocidad real
                proximo += periodo
                pausa = proximo - time.time()
                if pausa > 0:
                    self._detener.wait(pausa)
                else:
                    proximo = time.time()


class GestorCamaras:
    """Arranca, detiene y reinicia cámaras según la configuración vigente."""

    def __init__(self, cfg_captura: CfgCaptura) -> None:
        self.cfg_captura = cfg_captura
        self.camaras: dict[str, Camara] = {}

    def sincronizar(self, camaras_cfg: dict[str, CfgCamara]) -> None:
        for cid in list(self.camaras):
            cfg = camaras_cfg.get(cid)
            actual = self.camaras[cid]
            if cfg is None or not cfg.activa or cfg.fuente != actual.cfg.fuente:
                actual.detener()
                del self.camaras[cid]
            else:
                actual.cfg = cfg  # cambios de nombre/detectores no requieren reiniciar
        for cid, cfg in camaras_cfg.items():
            if cfg.activa and cid not in self.camaras:
                cam = Camara(cid, cfg, self.cfg_captura)
                cam.iniciar()
                self.camaras[cid] = cam

    def obtener(self, camara_id: str) -> Camara | None:
        return self.camaras.get(camara_id)

    def resumen(self) -> list[dict]:
        return [c.resumen() for c in self.camaras.values()]

    def detener_todas(self) -> None:
        for c in self.camaras.values():
            c.detener()
        self.camaras.clear()
