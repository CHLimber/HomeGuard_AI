"""Detector de fuego con el video sintético (llama naranja que parpadea entre 3 y 10 s)."""
from datetime import datetime

import cv2
import numpy as np
import pytest

from homeguard.analizador import Analizador
from homeguard.detectores.base import Zona
from homeguard.detectores.fuego import DetectorFuego
from homeguard.detectores.modelos import Modelos
from homeguard.reglas.motor import MotorReglas
from tests.conftest import leer_video, verdad

ZONA = Zona(id=1, camara_id="sint", nombre="Cocina", tipo="fuego",
            puntos=[[0.20, 0.25], [0.80, 0.25], [0.80, 0.90], [0.20, 0.90]])


class Capa2Falsa:
    """Simula el YOLO fire-smoke: devuelve 'fuego' con la confianza indicada en el centro de la imagen."""

    def __init__(self, confianza: float) -> None:
        self.confianza = confianza
        self.llamadas = 0

    def __call__(self, frame, cfg):
        self.llamadas += 1
        return [(1, self.confianza, (280, 220, 360, 320))]


def correr(cfg, frames, fps, capa2, zonas=(ZONA,)):
    detector = DetectorFuego(Modelos(), inferir_capa2=capa2)
    analizador = Analizador(Modelos(), {"fuego": detector})
    motor = MotorReglas(cfg.alarmas, cfg.motor)
    obs_t, disparos = [], []
    for i, frame in enumerate(frames):
        _, obs = analizador.analizar("sint", frame, i / fps, cfg, list(zonas), ["fuego"], hora=datetime.now())
        obs_t.append((i / fps, obs[0]))
        disparos += motor.procesar(obs)
    return obs_t, disparos


def test_capa1_solo_con_llama_y_capa2_solo_si_capa1(cfg, videos_sinteticos):
    ruta = videos_sinteticos / "fuego.mp4"
    capa2 = Capa2Falsa(0.8)
    obs_t, disparos = correr(cfg, leer_video(ruta), verdad(ruta)["fps"], capa2)
    capa1 = [(t, o.detalle["capa1_pct"] >= cfg.detectores.fuego.umbral_capa1_pct) for t, o in obs_t]
    assert not any(c for t, c in capa1 if t < 3.0 or t >= 10.1), "capa 1 activa sin llama"
    durante = [c for t, c in capa1 if 3.1 <= t < 10.0]
    assert sum(durante) / len(durante) > 0.9, "la capa 1 debería activarse casi siempre con la llama"
    # la capa 2 (YOLO) solo corrió en los frames con capa 1 activa
    assert capa2.llamadas == sum(c for _, c in capa1)
    assert len(disparos) == 1 and 3.0 <= disparos[0].t <= 3.6  # 3 de 5 frames


def test_capa2_con_baja_confianza_no_dispara(cfg, videos_sinteticos):
    ruta = videos_sinteticos / "fuego.mp4"
    _, disparos = correr(cfg, leer_video(ruta), verdad(ruta)["fps"], Capa2Falsa(0.3))
    assert disparos == []


def test_objeto_naranja_quieto_no_activa_capa1(cfg):
    """Sin movimiento (XOR = 0) el color solo no alcanza: la capa 1 no se activa y el YOLO nunca corre."""
    fondo = np.full((480, 640, 3), 170, np.uint8)
    cv2.ellipse(fondo, (320, 290), (40, 80), 0, 0, 360, (0, 140, 255), -1)
    capa2 = Capa2Falsa(0.9)
    obs_t, disparos = correr(cfg, [fondo.copy() for _ in range(30)], 15, capa2)
    assert capa2.llamadas == 0 and disparos == []
    assert obs_t[-1][1].detalle["capa1_pct"] == 0.0


def test_sin_zona_analiza_toda_la_imagen(cfg, videos_sinteticos):
    ruta = videos_sinteticos / "fuego.mp4"
    obs_t, disparos = correr(cfg, leer_video(ruta), verdad(ruta)["fps"], Capa2Falsa(0.8), zonas=())
    assert obs_t[0][1].zona == "toda la imagen"
    assert len(disparos) == 1


@pytest.mark.parametrize("modo", ["lut9", "hsv"])
def test_otros_modos_de_capa1_detectan_la_llama(cfg, videos_sinteticos, modo):
    """Los modos lut9 (índice de 9 bits) y hsv (inRange) también activan la capa 1 con la llama sintética."""
    cfg_modo = cfg.model_copy(deep=True)
    cfg_modo.detectores.fuego.modo_capa1 = modo
    ruta = videos_sinteticos / "fuego.mp4"
    obs_t, disparos = correr(cfg_modo, leer_video(ruta), verdad(ruta)["fps"], Capa2Falsa(0.8))
    umbral = cfg.detectores.fuego.umbral_capa1_pct
    assert not any(o.detalle["capa1_pct"] >= umbral for t, o in obs_t if t < 3.0)
    assert len(disparos) == 1


def test_lut_desde_archivo(cfg, tmp_path):
    """lut_archivo carga la tabla del .npy y valida que su tamaño coincida con el modo."""
    tabla = np.full(512, 255, np.uint8)   # todo es "fuego"
    ruta = tmp_path / "lut.npy"
    np.save(ruta, tabla)
    cfg_arch = cfg.model_copy(deep=True)
    cfg_arch.detectores.fuego.modo_capa1 = "lut9"
    cfg_arch.detectores.fuego.lut_archivo = str(ruta)
    det = DetectorFuego(Modelos())
    assert np.array_equal(det._tabla(cfg_arch.detectores.fuego), tabla)
    cfg_arch.detectores.fuego.modo_capa1 = "lut332"
    with pytest.raises(ValueError):
        det._tabla(cfg_arch.detectores.fuego)
