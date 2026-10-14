"""Tipos comunes a todos los detectores.

Un detector NUNCA decide si suena la alarma: devuelve "posibles eventos"
(observaciones) y el motor de reglas decide con votación N de M y cooldown.

Cada detector emite una observación por cada zona que evaluó, con
`activo=True` si la condición se cumple en ese frame y `activo=False` si no.
Las observaciones negativas son necesarias para que la votación N de M sepa
cuántos frames se evaluaron.

Los detectores usan el tiempo de `ctx.t` (nunca time.time()), así los tests y
el evaluador de videos pueden correr más rápido que el tiempo real.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import numpy as np

from homeguard.preproceso import bitwise

if TYPE_CHECKING:
    import supervision as sv

    from homeguard.config import Config

ZONA_GLOBAL = "toda la imagen"


@dataclass
class Zona:
    id: int
    camara_id: str
    nombre: str
    tipo: str                      # acceso, piscina, borde_piscina, puerta, fuego
    puntos: list[list[float]]      # coordenadas normalizadas 0-1
    referencia: str | None = None  # ruta de la imagen de referencia (zona puerta)

    def puntos_px(self, ancho: int, alto: int) -> np.ndarray:
        pts = np.asarray(self.puntos, dtype=np.float32) * np.array([ancho, alto], dtype=np.float32)
        return pts.round().astype(np.int32)


@dataclass
class PosibleEvento:
    tipo: str                 # intrusion, piscina, fuego, caida, puerta
    camara_id: str
    zona: str                 # nombre de la zona (ZONA_GLOBAL si es toda la imagen)
    activo: bool              # ¿se cumple la condición en este frame?
    t: float                  # instante de la observación (segundos)
    confianza: float = 0.0
    detalle: dict[str, Any] = field(default_factory=dict)
    bbox: tuple[int, int, int, int] | None = None


@dataclass
class Anotacion:
    """Algo que el detector quiere dibujar sobre el stream del dashboard."""
    bbox: tuple[int, int, int, int]
    texto: str
    alerta: bool = False


class EstadoCamara:
    """Estado persistente entre frames de una cámara (lo comparte el pipeline)."""

    def __init__(self, camara_id: str) -> None:
        self.camara_id = camara_id
        self.gris_anterior: np.ndarray | None = None
        self.indice = 0
        self.tracker: Any = None  # sv.ByteTrack, se crea al primer uso
        self._mascaras: dict[tuple, np.ndarray] = {}

    def mascara_zona(self, zona: Zona, alto: int, ancho: int) -> np.ndarray:
        clave = (zona.id, alto, ancho, tuple(map(tuple, zona.puntos)))
        if clave not in self._mascaras:
            if len(self._mascaras) > 64:
                self._mascaras.clear()
            self._mascaras[clave] = bitwise.mascara_poligono(alto, ancho, zona.puntos_px(ancho, alto))
        return self._mascaras[clave]


class Contexto:
    """Todo lo que un detector necesita para analizar un frame."""

    def __init__(
        self,
        camara_id: str,
        frame: np.ndarray,
        t: float,
        cfg: Config,
        zonas: list[Zona],
        estado: EstadoCamara,
        gris: np.ndarray,
        mascara_movimiento: np.ndarray | None,
        frame_original: np.ndarray | None = None,
        hora: datetime | None = None,
        detector_general: Callable[[np.ndarray], sv.Detections] | None = None,
    ) -> None:
        self.camara_id = camara_id
        self.frame = frame
        self.frame_original = frame if frame_original is None else frame_original
        self.t = t
        self.hora = hora or datetime.now()
        self.cfg = cfg
        self.zonas = zonas
        self.estado = estado
        self.gris = gris
        self.mascara_movimiento = mascara_movimiento
        self.alto, self.ancho = frame.shape[:2]
        self._detector_general = detector_general
        self._detecciones: sv.Detections | None = None
        self.calibracion: dict[str, dict[str, Any]] = {}
        self.anotaciones: list[Anotacion] = []

    @property
    def indice(self) -> int:
        return self.estado.indice

    def zonas_de_tipo(self, tipo: str) -> list[Zona]:
        return [z for z in self.zonas if z.tipo == tipo]

    def mascara_zona(self, zona: Zona) -> np.ndarray:
        return self.estado.mascara_zona(zona, self.alto, self.ancho)

    def detecciones_generales(self) -> sv.Detections:
        """Personas/mascotas con tracker_id (YOLO general + ByteTrack), calculado una vez por frame."""
        if self._detecciones is None:
            if self._detector_general is None:
                import supervision as sv

                self._detecciones = sv.Detections.empty()
            else:
                self._detecciones = self._detector_general(self.frame)
        return self._detecciones

    @property
    def detecciones_calculadas(self) -> bool:
        return self._detecciones is not None


class Detector(ABC):
    nombre: str = ""  # nombre en config.yaml (rostros, piscina, fuego, caidas, puerta)
    tipo: str = ""    # anomalía que reporta (intrusion, piscina, fuego, caida, puerta)

    @abstractmethod
    def procesar(self, frame: np.ndarray, ctx: Contexto) -> list[PosibleEvento]:
        """Analiza un frame y devuelve una observación por zona evaluada."""

    def reiniciar(self, camara_id: str | None = None) -> None:
        """Olvida el estado interno (de una cámara o de todas)."""
