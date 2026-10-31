"""Anomalía 4: caída de una persona (YOLOv8n-pose, 17 keypoints COCO).

Una persona está "en el suelo" si:
  - relación ancho/alto del bbox > `ratio_min` (cuerpo horizontal), y
  - el torso (punto medio de hombros 5-6 -> punto medio de caderas 11-12)
    forma menos de `angulo_max_grados` con la horizontal.
Es una CAÍDA si además:
  - hubo un descenso brusco: menos de `ventana_descenso_s` antes, cerca
    (en x) había una persona de pie cuyo centro estaba más arriba en al menos
    `descenso_min_relativo` x su altura, y
  - después queda inmóvil (centro dentro de `inmovil_desplazamiento_px`)
    durante más de `inmovil_tiempo_s`.

La persona caída se asocia con la que estaba de pie por cercanía y no por
tracker_id: cuando el cuerpo pasa de vertical a horizontal el bbox cambia
tanto que los trackers suelen perder la identidad justo en la caída.
La pose se calcula cada `cada_n_frames` frames para ahorrar CPU.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from homeguard.detectores.base import ZONA_GLOBAL, Anotacion, Contexto, Detector, PosibleEvento
from homeguard.detectores.modelos import Modelos

HOMBROS = (5, 6)
CADERAS = (11, 12)


@dataclass
class Persona:
    bbox: tuple[float, float, float, float]   # x0, y0, x1, y1 (frame de proceso)
    keypoints: np.ndarray                      # (17, 2)
    conf_keypoints: np.ndarray                 # (17,)
    confianza: float = 1.0

    @property
    def centro(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.bbox
        return (x0 + x1) / 2, (y0 + y1) / 2

    @property
    def alto(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def ratio(self) -> float:
        x0, y0, x1, y1 = self.bbox
        return (x1 - x0) / max(y1 - y0, 1.0)


def angulo_torso(p: Persona, conf_min: float) -> float | None:
    """Ángulo (grados) entre el torso y la horizontal: 0 = acostado, 90 = de pie. None si no hay keypoints."""
    def medio(indices: tuple[int, int]) -> np.ndarray | None:
        validos = [p.keypoints[i] for i in indices if p.conf_keypoints[i] >= conf_min]
        return np.mean(validos, axis=0) if validos else None

    hombros, caderas = medio(HOMBROS), medio(CADERAS)
    if hombros is None or caderas is None:
        return None
    dx, dy = caderas - hombros
    if dx == 0 and dy == 0:
        return None
    # Informe, ecuación del ángulo del torso: θ = atan2(|dy|, |dx|); horizontal si θ < angulo_max_grados
    return math.degrees(math.atan2(abs(dy), abs(dx)))


@dataclass
class _Candidato:
    """Persona que cayó: se sigue hasta confirmar la inmovilidad."""
    cx: float
    cy: float
    t_caida: float
    ancla: tuple[float, float]
    t_ancla: float
    ultimo_visto: float
    descenso: float


@dataclass
class _EstadoCamara:
    historial: deque = field(default_factory=lambda: deque(maxlen=200))  # (t, cx, cy, alto, acostado)
    candidatos: list[_Candidato] = field(default_factory=list)
    ultima_calibracion: dict = field(default_factory=dict)


class DetectorCaidas(Detector):
    nombre = "caidas"
    tipo = "caida"

    def __init__(self, modelos: Modelos, inferir_pose: Callable[[np.ndarray, Any], list[Persona]] | None = None):
        self.modelos = modelos
        self.inferir_pose = inferir_pose or self._yolo_pose
        self._estados: dict[str, _EstadoCamara] = {}

    def reiniciar(self, camara_id: str | None = None) -> None:
        if camara_id is None:
            self._estados.clear()
        else:
            self._estados.pop(camara_id, None)

    def _yolo_pose(self, frame: np.ndarray, cfg_global) -> list[Persona]:
        cfg = cfg_global.detectores.caidas
        r = self.modelos.yolo(cfg.modelo).predict(frame, imgsz=cfg_global.procesamiento.imgsz_yolo,
                                                   conf=cfg.confianza, verbose=False)[0]
        if r.keypoints is None or len(r.boxes) == 0:
            return []
        cajas = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        kps = r.keypoints.xy.cpu().numpy()
        kconf = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else np.ones(kps.shape[:2])
        return [Persona(tuple(map(float, cajas[i])), kps[i], kconf[i], float(confs[i])) for i in range(len(cajas))]

    def procesar(self, frame: np.ndarray, ctx: Contexto) -> list[PosibleEvento]:
        cfg = ctx.cfg.detectores.caidas
        estado = self._estados.setdefault(ctx.camara_id, _EstadoCamara())
        if ctx.indice % cfg.cada_n_frames != 0:  # frame salteado: se reutiliza la última calibración
            if estado.ultima_calibracion:
                ctx.calibracion["caidas"] = estado.ultima_calibracion
            return []

        t = ctx.t
        personas = self.inferir_pose(frame, ctx.cfg)
        detalle_personas = []
        for p in personas:
            ang = angulo_torso(p, cfg.confianza_keypoint)
            acostado = p.ratio > cfg.ratio_min and ang is not None and ang < cfg.angulo_max_grados
            cx, cy = p.centro
            if acostado:
                self._seguir_o_crear(estado, cfg, t, cx, cy)
            else:  # de pie / sentado: si estaba cerca de un candidato, se levantó
                estado.candidatos = [c for c in estado.candidatos
                                     if abs(c.cx - cx) >= cfg.radio_asociacion_px or abs(c.cy - cy) >= p.alto]
            estado.historial.append((t, cx, cy, p.alto, acostado))
            detalle_personas.append({"ratio": round(p.ratio, 2),
                                     "angulo_torso": None if ang is None else round(ang, 0),
                                     "acostado": acostado})
            ctx.anotaciones.append(Anotacion(tuple(int(v) for v in p.bbox),
                                             f"r {p.ratio:.1f} ang {'-' if ang is None else f'{ang:.0f}'}", acostado))

        estado.candidatos = [c for c in estado.candidatos if t - c.ultimo_visto <= cfg.olvidar_tras_s]
        while estado.historial and estado.historial[0][0] < t - max(cfg.ventana_descenso_s, cfg.olvidar_tras_s) - 1:
            estado.historial.popleft()

        quietos = [t - c.t_ancla for c in estado.candidatos]
        activo = any(q >= cfg.inmovil_tiempo_s for q in quietos)
        descenso = max((c.descenso for c in estado.candidatos), default=0.0)
        calib = {
            "personas": detalle_personas, "ratio_min": cfg.ratio_min, "angulo_max": cfg.angulo_max_grados,
            "caidas_en_seguimiento": len(estado.candidatos),
            "descenso_relativo": round(descenso, 2), "umbral_descenso": cfg.descenso_min_relativo,
            "segundos_inmovil": round(max(quietos, default=0.0), 1), "umbral_inmovil_s": cfg.inmovil_tiempo_s,
        }
        ctx.calibracion["caidas"] = estado.ultima_calibracion = calib
        return [PosibleEvento(
            tipo=self.tipo, camara_id=ctx.camara_id, zona=ZONA_GLOBAL, activo=activo, t=t,
            confianza=max((p.confianza for p in personas), default=0.0),
            detalle={"segundos_inmovil": calib["segundos_inmovil"], "descenso_relativo": calib["descenso_relativo"]},
        )]

    @staticmethod
    def _seguir_o_crear(estado: _EstadoCamara, cfg, t: float, cx: float, cy: float) -> None:
        cercanos = [c for c in estado.candidatos if math.hypot(c.cx - cx, c.cy - cy) < cfg.radio_asociacion_px]
        if cercanos:
            c = min(cercanos, key=lambda c: math.hypot(c.cx - cx, c.cy - cy))
            c.cx, c.cy, c.ultimo_visto = cx, cy, t
            if math.hypot(cx - c.ancla[0], cy - c.ancla[1]) > cfg.inmovil_desplazamiento_px:
                c.ancla, c.t_ancla = (cx, cy), t  # se movió: la inmovilidad empieza de nuevo
            return
        # ¿hubo una persona de pie cerca, más arriba, hace menos de ventana_descenso_s?
        mejor = 0.0
        for (tr, rx, ry, alto, acostado) in estado.historial:
            if acostado or not (t - cfg.ventana_descenso_s <= tr < t):
                continue
            if abs(rx - cx) < cfg.radio_asociacion_px and alto > 0:
                mejor = max(mejor, (cy - ry) / alto)
        if mejor >= cfg.descenso_min_relativo:
            estado.candidatos.append(_Candidato(cx, cy, t, (cx, cy), t, t, mejor))
