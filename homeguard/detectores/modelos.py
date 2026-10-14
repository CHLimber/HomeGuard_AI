"""Carga perezosa (lazy) y compartida de los modelos.

Los modelos se cargan la primera vez que se usan: si una cámara no tiene
zona "piscina", nunca se carga el YOLO general, etc. Así el arranque es rápido
y los tests que no usan modelos no los necesitan.
"""
from __future__ import annotations

import logging
import threading
import warnings
from typing import Any

from homeguard.config import ruta_abs

log = logging.getLogger(__name__)

# sv.ByteTrack avisa que está deprecado en supervision >= 0.28 (requirements fija < 0.31)
warnings.filterwarnings("ignore", message=".*ByteTrack.*deprecated.*", category=FutureWarning)


def _silenciar_opencv() -> None:
    """OpenCV 5 avisa 'Targets are not supported by the new graph engine' al crear YuNet/SFace: es inofensivo."""
    try:
        import cv2

        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:  # noqa: BLE001
        pass


class Modelos:
    def __init__(self, hilos_torch: int = 4) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self.hilos_torch = hilos_torch
        self._torch_configurado = False
        _silenciar_opencv()

    def _configurar_torch(self) -> None:
        if not self._torch_configurado:
            import torch

            torch.set_num_threads(self.hilos_torch)
            self._torch_configurado = True

    def yolo(self, ruta: str) -> Any:
        """Modelo Ultralytics (detección o pose), cacheado por ruta."""
        clave = f"yolo:{ruta}"
        with self._lock:
            if clave not in self._cache:
                from ultralytics import YOLO

                self._configurar_torch()
                p = ruta_abs(ruta)
                if not p.exists():
                    raise FileNotFoundError(f"falta el modelo {ruta}: ejecutá python scripts/descargar_modelos.py")
                log.info("Cargando modelo %s ...", p.name)
                self._cache[clave] = YOLO(str(p))
            return self._cache[clave]

    def yunet(self, ruta: str, confianza: float, nms: float, instancia: str | None = None) -> Any:
        """Detector de rostros YuNet. No es thread-safe: una instancia por hilo, o una con nombre (`instancia`)."""
        import cv2

        clave = f"yunet:{ruta}:{instancia or threading.get_ident()}"
        with self._lock:
            if clave not in self._cache:
                p = ruta_abs(ruta)
                if not p.exists():
                    raise FileNotFoundError(f"falta el modelo {ruta}: ejecutá python scripts/descargar_modelos.py")
                self._cache[clave] = cv2.FaceDetectorYN.create(str(p), "", (320, 320), confianza, nms, 50)
            det = self._cache[clave]
        det.setScoreThreshold(confianza)
        det.setNMSThreshold(nms)
        return det

    def sface(self, ruta: str, instancia: str | None = None) -> Any:
        """Reconocedor SFace (una instancia por hilo, o una con nombre)."""
        import cv2

        clave = f"sface:{ruta}:{instancia or threading.get_ident()}"
        with self._lock:
            if clave not in self._cache:
                p = ruta_abs(ruta)
                if not p.exists():
                    raise FileNotFoundError(f"falta el modelo {ruta}: ejecutá python scripts/descargar_modelos.py")
                self._cache[clave] = cv2.FaceRecognizerSF.create(str(p), "")
            return self._cache[clave]
