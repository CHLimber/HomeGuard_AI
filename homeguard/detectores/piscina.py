"""Anomalía 2: piscina.

Usa las detecciones del YOLO general (persona, perro, gato) con tracker_id de
ByteTrack, y supervision.PolygonZone para saber quién está en cada zona.
Por cada zona "piscina" la observación es positiva si:
  (a) hay una persona o mascota dentro de la piscina y NO hay ningún
      "supervisor" (persona en una zona "borde_piscina") durante
      `tiempo_sin_supervisor_s`, o
  (b) un mismo tracker_id está casi inmóvil (su centro se movió menos de
      `inmovil_desplazamiento_px`) durante más de `inmovil_tiempo_s` dentro
      de la piscina (posible ahogamiento), haya o no supervisor.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from homeguard.detectores.base import Anotacion, Contexto, Detector, PosibleEvento

CLASE_PERSONA = 0
NOMBRES = {0: "persona", 15: "gato", 16: "perro"}


@dataclass
class _Track:
    puntos: deque = field(default_factory=deque)  # (t, cx, cy)
    ultimo: float = 0.0


@dataclass
class _EstadoZona:
    t_sin_supervisor: float | None = None
    tracks: dict[int, _Track] = field(default_factory=dict)


class DetectorPiscina(Detector):
    nombre = "piscina"
    tipo = "piscina"

    def __init__(self) -> None:
        self._estados: dict[tuple[str, int], _EstadoZona] = {}

    def reiniciar(self, camara_id: str | None = None) -> None:
        self._estados = {} if camara_id is None else {k: v for k, v in self._estados.items() if k[0] != camara_id}

    @staticmethod
    def _inmovil(track: _Track, t: float, segundos: float, tolerancia: float) -> tuple[bool, float]:
        """¿El centro estuvo dentro de `tolerancia` px durante los últimos `segundos`? Devuelve (inmóvil, s quieto)."""
        if not track.puntos:
            return False, 0.0
        _, cx, cy = track.puntos[-1]
        quieto_desde = track.puntos[-1][0]
        for tp, px, py in reversed(track.puntos):
            if np.hypot(px - cx, py - cy) >= tolerancia:
                break
            quieto_desde = tp
        quieto = t - quieto_desde
        return quieto >= segundos, quieto

    def procesar(self, frame: np.ndarray, ctx: Contexto) -> list[PosibleEvento]:
        zonas = ctx.zonas_de_tipo("piscina")
        if not zonas:
            return []
        cfg = ctx.cfg.detectores.piscina
        det = ctx.detecciones_generales()

        supervisores = 0
        if len(det):
            es_persona = det.class_id == CLASE_PERSONA
            for borde in ctx.zonas_de_tipo("borde_piscina"):
                supervisores += int(np.sum(ctx.dentro_de_zona(borde, det) & es_persona))

        eventos: list[PosibleEvento] = []
        for zona in zonas:
            estado = self._estados.setdefault((ctx.camara_id, zona.id), _EstadoZona())
            dentro = ctx.dentro_de_zona(zona, det) if len(det) else np.zeros(0, bool)
            objetivos = det[dentro] if len(det) else det
            n_personas = int(np.sum(objetivos.class_id == CLASE_PERSONA)) if len(objetivos) else 0
            n_mascotas = len(objetivos) - n_personas

            # (a) alguien en la piscina sin supervisor
            if len(objetivos) and supervisores == 0:
                if estado.t_sin_supervisor is None:
                    estado.t_sin_supervisor = ctx.t
                sin_sup = ctx.t - estado.t_sin_supervisor
            else:
                estado.t_sin_supervisor = None
                sin_sup = 0.0
            regla_a = estado.t_sin_supervisor is not None and sin_sup >= cfg.tiempo_sin_supervisor_s

            # (b) mismo tracker_id casi inmóvil dentro de la piscina
            inmoviles: list[int] = []
            max_quieto = 0.0
            ids = objetivos.tracker_id if len(objetivos) and objetivos.tracker_id is not None else []
            for i, tid in enumerate(ids):
                x0, y0, x1, y1 = objetivos.xyxy[i]
                track = estado.tracks.setdefault(int(tid), _Track())
                track.puntos.append((ctx.t, float(x0 + x1) / 2, float(y0 + y1) / 2))
                track.ultimo = ctx.t
                while track.puntos and track.puntos[0][0] < ctx.t - cfg.inmovil_tiempo_s - 1.0:
                    track.puntos.popleft()
                quieto, segundos = self._inmovil(track, ctx.t, cfg.inmovil_tiempo_s, cfg.inmovil_desplazamiento_px)
                max_quieto = max(max_quieto, segundos)
                if quieto:
                    inmoviles.append(int(tid))
                nombre = NOMBRES.get(int(objetivos.class_id[i]), "objeto")
                ctx.anotaciones.append(Anotacion(tuple(int(v) for v in objetivos.xyxy[i]),
                                                 f"{nombre} #{tid} quieto {segundos:.0f}s", quieto or regla_a))
            for tid in [k for k, tr in estado.tracks.items() if ctx.t - tr.ultimo > cfg.olvidar_track_s]:
                del estado.tracks[tid]
            regla_b = bool(inmoviles)

            activo = regla_a or regla_b
            motivo = " + ".join(m for m, ok in (("sin supervisor", regla_a), ("inmóvil", regla_b)) if ok) or None
            ctx.calibracion.setdefault("piscina", {})[zona.nombre] = {
                "personas_en_piscina": n_personas, "mascotas_en_piscina": n_mascotas,
                "supervisores_en_borde": supervisores,
                "segundos_sin_supervisor": round(sin_sup, 1), "umbral_sin_supervisor_s": cfg.tiempo_sin_supervisor_s,
                "max_segundos_inmovil": round(max_quieto, 1), "umbral_inmovil_s": cfg.inmovil_tiempo_s,
            }
            eventos.append(PosibleEvento(
                tipo=self.tipo, camara_id=ctx.camara_id, zona=zona.nombre, activo=activo, t=ctx.t,
                confianza=float(objetivos.confidence.max()) if len(objetivos) and objetivos.confidence is not None else 0.0,
                detalle={"motivo": motivo, "personas": n_personas, "mascotas": n_mascotas,
                         "supervisores": supervisores, "inmoviles": inmoviles},
            ))
        return eventos
