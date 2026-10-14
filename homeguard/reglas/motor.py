"""Motor de reglas: el único componente que decide si suena la alarma.

Recibe las observaciones de los detectores (PosibleEvento con activo True/False)
y aplica, por cada (tipo, cámara, zona):
  1. Votación N de M: la condición tiene que cumplirse en al menos N de las
     últimas M observaciones.
  2. Cooldown: después de disparar, ese (tipo, cámara, zona) no vuelve a
     disparar durante cooldown_s segundos.
Cuando dispara, enciende el bit de la anomalía en el byte de estado (ver
estado.py). El byte queda encendido hasta que alguien toca "SILENCIAR" (o
pasan motor.auto_limpiar_s segundos, si está configurado).
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from homeguard.config import CfgAlarmas, CfgMotor
from homeguard.detectores.base import PosibleEvento
from homeguard.reglas import estado as est

Clave = tuple[str, str, str]  # (tipo, camara_id, zona)

# una observación más vieja que esto ya no cuenta para el semáforo "activos"
VIGENCIA_ACTIVOS_S = 2.0


@dataclass
class Disparo:
    """Alarma confirmada por el motor."""
    tipo: str
    camara_id: str
    zona: str
    t: float                  # instante de la observación que confirmó la alarma
    confianza: float
    votos: int                # cuántas de las últimas M observaciones fueron positivas
    estado: int               # byte de estado después del disparo
    detalle: dict[str, Any] = field(default_factory=dict)
    observacion: PosibleEvento | None = None


class MotorReglas:
    def __init__(self, alarmas: CfgAlarmas, motor: CfgMotor) -> None:
        self._lock = threading.Lock()
        self.alarmas = alarmas
        self.cfg_motor = motor
        self.estado = 0  # byte de alarmas enclavadas
        self._ventanas: dict[Clave, deque[bool]] = {}
        self._ultimo_disparo: dict[Clave, float] = {}
        self._ultima_obs: dict[Clave, tuple[bool, float]] = {}
        self._t_ultimo_disparo_global: float | None = None
        self._t_actual = 0.0

    def actualizar_config(self, alarmas: CfgAlarmas, motor: CfgMotor) -> None:
        with self._lock:
            self.alarmas = alarmas
            self.cfg_motor = motor

    def _regla(self, tipo: str):
        return getattr(self.alarmas, tipo)

    def en_cooldown(self, clave: Clave, t: float) -> bool:
        ultimo = self._ultimo_disparo.get(clave)
        return ultimo is not None and (t - ultimo) < self._regla(clave[0]).cooldown_s

    def procesar(self, observaciones: list[PosibleEvento]) -> list[Disparo]:
        """Registra las observaciones y devuelve las alarmas que se confirman ahora."""
        disparos: list[Disparo] = []
        with self._lock:
            for obs in observaciones:
                self._t_actual = max(self._t_actual, obs.t)
                clave: Clave = (obs.tipo, obs.camara_id, obs.zona)
                regla = self._regla(obs.tipo)
                ventana = self._ventanas.get(clave)
                if ventana is None or ventana.maxlen != regla.votos_m:  # nueva clave o cambió M
                    ventana = deque(ventana or (), maxlen=regla.votos_m)
                    self._ventanas[clave] = ventana
                ventana.append(obs.activo)
                self._ultima_obs[clave] = (obs.activo, obs.t)

                votos = sum(ventana)
                if not obs.activo or votos < regla.votos_n or self.en_cooldown(clave, obs.t):
                    continue
                self._ultimo_disparo[clave] = obs.t
                self._t_ultimo_disparo_global = obs.t
                self.estado = est.activar(self.estado, obs.tipo)
                disparos.append(Disparo(
                    tipo=obs.tipo, camara_id=obs.camara_id, zona=obs.zona, t=obs.t,
                    confianza=obs.confianza, votos=votos, estado=self.estado,
                    detalle=dict(obs.detalle), observacion=obs,
                ))
            self._auto_limpiar()
        return disparos

    def _auto_limpiar(self) -> None:
        espera = self.cfg_motor.auto_limpiar_s
        if espera > 0 and self.estado and self._t_ultimo_disparo_global is not None:
            if self._t_actual - self._t_ultimo_disparo_global >= espera:
                self.estado = 0

    def silenciar(self) -> int:
        """Apaga todas las alarmas (el cooldown sigue corriendo, así no vuelve a sonar de inmediato)."""
        with self._lock:
            self.estado = 0
            return self.estado

    @property
    def activos(self) -> int:
        """Byte con las anomalías cuya última observación (reciente) fue positiva: para el semáforo."""
        byte = 0
        with self._lock:
            for (tipo, _, _), (activo, t) in self._ultima_obs.items():
                if activo and self._t_actual - t <= VIGENCIA_ACTIVOS_S:
                    byte = est.activar(byte, tipo)
        return byte

    def reiniciar(self) -> None:
        with self._lock:
            self.estado = 0
            self._ventanas.clear()
            self._ultimo_disparo.clear()
            self._ultima_obs.clear()
            self._t_ultimo_disparo_global = None
