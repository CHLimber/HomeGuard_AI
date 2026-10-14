"""Detector de piscina con el video sintético 'zona' y detecciones simuladas a partir de la verdad de terreno.

El rectángulo del video no es una persona para YOLO, así que se reemplaza el
YOLO general por las cajas reales del .json: se prueban zonas, ByteTrack,
reglas (a) y (b) y el motor de reglas sin depender del modelo.
"""
from datetime import datetime

import numpy as np
import supervision as sv

from homeguard.analizador import Analizador
from homeguard.detectores.base import Zona
from homeguard.detectores.modelos import Modelos
from homeguard.detectores.piscina import DetectorPiscina
from homeguard.reglas.motor import MotorReglas
from tests.conftest import leer_video, verdad

PISCINA = Zona(1, "sint", "Piscina", "piscina", [[0.50, 0.30], [0.95, 0.30], [0.95, 0.90], [0.50, 0.90]])
BORDE = Zona(2, "sint", "Borde", "borde_piscina", [[0.35, 0.30], [0.48, 0.30], [0.48, 0.90], [0.35, 0.90]])
SUPERVISOR = [240, 200, 290, 400]  # caja de un adulto parado en el borde


def correr(cfg, ruta, con_supervisor=False, clase=0):
    datos = verdad(ruta)
    cajas = iter(datos["cajas_persona"])

    def yolo_falso(frame):
        xyxy = [next(cajas)] + ([SUPERVISOR] if con_supervisor else [])
        return sv.Detections(xyxy=np.array(xyxy, np.float32), confidence=np.full(len(xyxy), 0.9, np.float32),
                             class_id=np.array([clase] + [0] * (len(xyxy) - 1)))

    analizador = Analizador(Modelos(), {"piscina": DetectorPiscina()})
    analizador.detector_general = yolo_falso
    motor = MotorReglas(cfg.alarmas, cfg.motor)
    obs_t, disparos = [], []
    for i, frame in enumerate(leer_video(ruta)):
        t = i / datos["fps"]
        _, obs = analizador.analizar("sint", frame, t, cfg, [PISCINA, BORDE], ["piscina"], hora=datetime.now())
        obs_t.append((t, obs[0]))
        disparos += motor.procesar(obs)
    return obs_t, disparos


def test_sin_supervisor_dispara(cfg, videos_sinteticos):
    obs_t, disparos = correr(cfg, videos_sinteticos / "zona.mp4")
    # la base de la caja cruza el borde izquierdo de la piscina (x=320) cerca de t=3.5 s
    entrada = next(t for t, o in obs_t if o.detalle["personas"] > 0)
    assert 3.0 <= entrada <= 4.0
    assert not any(o.activo for t, o in obs_t if t < entrada + cfg.detectores.piscina.tiempo_sin_supervisor_s - 0.1)
    assert len(disparos) == 1
    assert disparos[0].detalle["motivo"].startswith("sin supervisor")


def test_con_supervisor_no_dispara_por_regla_a(cfg, videos_sinteticos):
    obs_t, disparos = correr(cfg, videos_sinteticos / "zona.mp4", con_supervisor=True)
    assert all(o.detalle["supervisores"] >= 1 for _, o in obs_t)  # 2 mientras la persona cruza el borde
    assert disparos == []  # inmóvil solo 7 s (< 10 s de inmovil_tiempo_s)


def test_inmovil_dispara_aunque_haya_supervisor(cfg, videos_sinteticos):
    cfg = cfg.model_copy(deep=True)
    cfg.detectores.piscina.inmovil_tiempo_s = 4.0
    obs_t, disparos = correr(cfg, videos_sinteticos / "zona.mp4", con_supervisor=True)
    assert len(disparos) == 1
    assert disparos[0].detalle["motivo"] == "inmóvil"
    assert 9.0 <= disparos[0].t <= 9.6  # quieto desde t=5 s + 4 s (+ votos 3 de 5)


def test_mascota_tambien_cuenta(cfg, videos_sinteticos):
    _, disparos = correr(cfg, videos_sinteticos / "zona.mp4", clase=16)  # perro
    assert len(disparos) == 1 and disparos[0].detalle["mascotas"] == 1
