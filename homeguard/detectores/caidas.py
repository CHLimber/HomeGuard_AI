"""Anomalía 3: caída de una persona (YOLOv8n-pose, 17 keypoints COCO).

Una persona está "en el suelo" si cumple uno de estos dos criterios:
  a) Horizontal: relación ancho/alto del bbox > `ratio_min` y el torso (punto
     medio de hombros 5-6 -> punto medio de caderas 11-12) forma menos de
     `angulo_max_grados` con la horizontal. Solo se cumple si la cámara la ve
     de costado.
  b) Desplome: respecto de la persona de pie que había ahí menos de
     `ventana_descenso_s` antes, el alto del bbox quedó por debajo de
     `colapso_alto_max` x el alto de pie, la cabeza (borde superior) bajó al
     menos `descenso_min_relativo` x ese alto y el bbox no es angosto
     (ancho/alto >= `colapso_ratio_min`; en cuclillas queda angosto). Vale
     para quien cae hacia la cámara o con la cámara alta. No cuenta si quien
     estaba de pie sigue de pie (es otra persona), si ya venía bajando de a
     poco, o si esa persona baja ya estaba ahí.
Es una CAÍDA si además:
  - hubo un descenso brusco: menos de `ventana_descenso_s` antes, cerca
    (en x) había una persona de pie cuyo centro (o cabeza, en el desplome)
    estaba más arriba en al menos `descenso_min_relativo` x su altura, y
  - después queda inmóvil durante más de `inmovil_tiempo_s`: el centro no se
    aleja más de `inmovil_desplazamiento_px` (o `inmovil_desplazamiento_relativo`
    x el largo del cuerpo, lo que sea mayor; así el ruido de la pose en un cuerpo
    grande no reinicia la cuenta).
La caída se descarta si alguien de pie o sentado aparece cerca y claramente más
arriba (`levantarse_relativo` x su altura): una detección «de pie» que apenas
sube respecto del suelo es ruido de la pose, no una persona que se levantó.
Quien ya estaba de pie al lado cuando ocurrió la caída no cuenta como «se
levantó» (si no, cualquier acompañante cancelaba la caída).

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
# Desplome: la referencia «de pie» tiene que medir al menos FRACCION_ERGUIDA del alto máximo que tuvo esa persona
# en las últimas VENTANAS_ERGUIDA x ventana_descenso_s (si no, ya venía agachándose de a poco).
FRACCION_ERGUIDA = 0.6  # sentada en el suelo mide ~0,5 del alto de pie; más alto descarta a quien se aleja de la cámara
VENTANAS_ERGUIDA = 3
# Una detección «no acostada» junto a una caída se toma por la misma persona si no es más alta que esto x el largo
# del cuerpo caído (alguien de pie delante de la caída mide bastante más y no la mantiene viva ni la cancela).
MARGEN_CUERPO_CAIDO = 1.25


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
    tam: float  # largo del cuerpo caído (lado mayor de su bbox): escala la tolerancia de movimiento
    acompanantes: int = 0  # personas de pie que ya estaban al lado (y más arriba) cuando cayó: no son «se levantó»


@dataclass
class _Muestra:
    """Persona que NO estaba en el suelo en un frame: referencia «de pie» para medir el descenso."""
    t: float
    cx: float
    cy: float
    y0: float    # borde superior del bbox (la cabeza)
    alto: float


@dataclass
class _EstadoCamara:
    historial: deque = field(default_factory=lambda: deque(maxlen=600))  # _Muestra
    candidatos: list[_Candidato] = field(default_factory=list)
    ultima_calibracion: dict = field(default_factory=dict)


def _radio(cfg, alto: float) -> float:
    """Distancia horizontal máxima para asociar dos detecciones de la misma persona: al caer de costado el centro
    se corre más o menos media altura, así que un radio fijo en px se queda corto con la persona cerca de la cámara."""
    return max(cfg.radio_asociacion_px, cfg.radio_asociacion_relativo * alto)


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
        r = self.modelos.yolo(cfg.modelo).predict(frame, imgsz=cfg.imgsz or cfg_global.procesamiento.imgsz_yolo,
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
        arriba: dict[int, int] = {}  # por caída en seguimiento: personas de pie cerca y claramente más arriba
        for p in personas:
            ang = angulo_torso(p, cfg.confianza_keypoint)
            cx, cy = p.centro
            x0, y0, x1, y1 = p.bbox
            horizontal = p.ratio > cfg.ratio_min and ang is not None and ang < cfg.angulo_max_grados
            # Desplome: respecto de la persona de pie que había ahí hace menos de ventana_descenso_s, el bbox
            # perdió altura y la cabeza bajó. No depende de que el cuerpo se vea horizontal (cae hacia la cámara
            # o la cámara está alta). Informe, ecuación del desplome:
            #   alto / alto_de_pie <= colapso_alto_max  y  (y0 - y0_de_pie) / alto_de_pie >= descenso_min_relativo
            otras = [(o.centro[0], o.alto) for o in personas if o is not p]
            colapso, baja_cabeza, baja_centro = self._descenso(estado, cfg, t, cx, cy, y0, p.alto, otras)
            desplomado = (colapso is not None and colapso <= cfg.colapso_alto_max
                          and baja_cabeza >= cfg.descenso_min_relativo and p.ratio >= cfg.colapso_ratio_min)
            acostado = horizontal or desplomado
            cerca = [c for c in estado.candidatos if abs(c.cx - cx) < _radio(cfg, max(p.alto, c.tam))]
            if acostado:
                descenso = max(baja_centro, baja_cabeza if desplomado else 0.0)
                tam = max(x1 - x0, y1 - y0)
                al_lado = sum(1 for o in personas if o is not p and abs(o.centro[0] - cx) < _radio(cfg, max(o.alto, tam))
                              and cy - o.centro[1] >= cfg.levantarse_relativo * o.alto)
                self._seguir_o_crear(estado, cfg, t, cx, cy, tam, descenso, al_lado)
            elif cerca:
                # de pie / sentado cerca de una caída y claramente más arriba: o se levantó, o es alguien que ya
                # estaba ahí (se decide al final del frame, contando). Si no está más arriba y mide más o menos
                # lo que el cuerpo caído, es la misma persona en el suelo que la pose ya no ve horizontal: se la
                # sigue (si se arrastra reinicia la inmovilidad) y no sirve de referencia de pie.
                encima = [c for c in cerca if c.cy - cy >= cfg.levantarse_relativo * p.alto]
                for c in encima:
                    arriba[id(c)] = arriba.get(id(c), 0) + 1
                if encima:
                    estado.historial.append(_Muestra(t, cx, cy, y0, p.alto))
                elif any(p.alto <= MARGEN_CUERPO_CAIDO * c.tam for c in cerca):
                    self._seguir_o_crear(estado, cfg, t, cx, cy, max(x1 - x0, y1 - y0), 0.0, 0)
            else:
                estado.historial.append(_Muestra(t, cx, cy, y0, p.alto))
            detalle_personas.append({"ratio": round(p.ratio, 2),
                                     "angulo_torso": None if ang is None else round(ang, 0),
                                     "alto_relativo": None if colapso is None else round(colapso, 2),
                                     "acostado": acostado})
            ctx.anotaciones.append(Anotacion(tuple(int(v) for v in p.bbox),
                                             f"r {p.ratio:.1f} ang {'-' if ang is None else f'{ang:.0f}'}", acostado))

        # se levantó: hay más personas de pie sobre la caída que las que ya la acompañaban cuando ocurrió
        estado.candidatos = [c for c in estado.candidatos if arriba.get(id(c), 0) <= c.acompanantes]
        estado.candidatos = [c for c in estado.candidatos if t - c.ultimo_visto <= cfg.olvidar_tras_s]
        memoria = max(VENTANAS_ERGUIDA * cfg.ventana_descenso_s, cfg.olvidar_tras_s) + 1
        while estado.historial and estado.historial[0].t < t - memoria:
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
    def _descenso(estado: _EstadoCamara, cfg, t: float, cx: float, cy: float, y0: float, alto: float,
                  otras: list[tuple[float, float]]) -> tuple[float | None, float, float]:
        """Compara con las personas de pie que había cerca hace menos de `ventana_descenso_s`.

        Devuelve (alto actual / alto de pie, descenso de la cabeza, descenso del centro); los descensos son
        relativos al alto de pie. La referencia de alto y cabeza es la muestra más alta (la más erguida: durante
        la caída el bbox se va achicando). Sin referencia: (None, 0, 0).
        `otras` = (cx, alto) de las demás personas del frame: una referencia no vale si las personas que había
        de pie ahí siguen todas de pie (entonces quien está abajo es otra persona, no la que cayó).
        """
        ref: _Muestra | None = None
        baja_centro = 0.0
        recientes = [m for m in estado.historial if t - cfg.ventana_descenso_s <= m.t < t and m.alto > 0]
        # muestras de alguien de su mismo tamaño en el mismo lugar; valen si se repiten (una sola es ruido de la pose)
        ya_estaba = [o for o in recientes if 0.7 <= o.alto / alto <= 1.4
                     and math.hypot(o.cx - cx, o.cy - cy) < 0.75 * alto]
        if len({o.t for o in ya_estaba}) < 3:
            ya_estaba = []
        for m in recientes:
            radio = _radio(cfg, m.alto)
            if abs(m.cx - cx) >= radio:
                continue
            alto_min = cfg.colapso_alto_max * m.alto  # por debajo de esto no es «la misma persona, todavía de pie»
            habia = sum(1 for o in recientes if o.t == m.t and abs(o.cx - m.cx) < radio and o.alto > alto_min)
            siguen = sum(1 for ox, oalto in otras if abs(ox - m.cx) < radio and oalto > alto_min)
            if siguen >= habia:
                continue
            # ...ni si en ese mismo frame ya había, donde está ahora, alguien de su tamaño: es una persona baja
            # (un niño, alguien sentado) que ya estaba ahí, y quien se fue es la que estaba de pie a su lado.
            if any(o.t == m.t and o is not m for o in ya_estaba):
                continue
            # Informe, ecuación del descenso: (cy - cy_de_pie) / alto_de_pie >= descenso_min_relativo
            baja_centro = max(baja_centro, (cy - m.cy) / m.alto)
            if ref is None or m.alto > ref.alto:
                ref = m
        if ref is None:
            return None, 0.0, 0.0
        # La referencia tiene que estar erguida: si poco antes esa persona era bastante más alta, ya venía
        # bajando de a poco (se agacha o se acuesta despacio) y lo de ahora no es un desplome brusco.
        desde = t - VENTANAS_ERGUIDA * cfg.ventana_descenso_s
        alto_de_pie = max(m.alto for m in estado.historial
                          if desde <= m.t < t and abs(m.cx - ref.cx) < _radio(cfg, m.alto))
        if ref.alto < FRACCION_ERGUIDA * alto_de_pie:
            return None, 0.0, baja_centro
        return alto / ref.alto, (y0 - ref.y0) / ref.alto, baja_centro

    @staticmethod
    def _seguir_o_crear(estado: _EstadoCamara, cfg, t: float, cx: float, cy: float, tam: float,
                        descenso: float, acompanantes: int) -> None:
        cercanos = [c for c in estado.candidatos
                    if math.hypot(c.cx - cx, c.cy - cy) < _radio(cfg, max(tam, c.tam))]
        if cercanos:
            c = min(cercanos, key=lambda c: math.hypot(c.cx - cx, c.cy - cy))
            c.cx, c.cy, c.ultimo_visto, c.tam = cx, cy, t, tam
            tolerancia = max(cfg.inmovil_desplazamiento_px, cfg.inmovil_desplazamiento_relativo * tam)
            if math.hypot(cx - c.ancla[0], cy - c.ancla[1]) > tolerancia:
                c.ancla, c.t_ancla = (cx, cy), t  # se movió: la inmovilidad empieza de nuevo
            return
        # caída nueva solo si hubo una persona de pie cerca, más arriba, hace menos de ventana_descenso_s
        if descenso >= cfg.descenso_min_relativo:
            estado.candidatos.append(_Candidato(cx, cy, t, (cx, cy), t, t, descenso, tam, acompanantes))
