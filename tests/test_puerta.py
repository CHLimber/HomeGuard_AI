"""Detector de puerta con el video sintético (cerrada 0-4 s, abierta 4-9 s, cerrada 9-12 s)."""
from datetime import datetime

import pytest

from homeguard.analizador import Analizador
from homeguard.detectores.base import Zona
from homeguard.detectores.modelos import Modelos
from homeguard.detectores.puerta import DetectorPuerta, en_horario
from homeguard.reglas.motor import MotorReglas
from tests.conftest import leer_video, verdad

ZONA = Zona(id=1, camara_id="sint", nombre="Puerta principal", tipo="puerta",
            puntos=[[0.40, 0.20], [0.60, 0.20], [0.60, 0.85], [0.40, 0.85]])
NOCHE = datetime(2026, 10, 14, 23, 30)


def correr(cfg, ruta, hora=NOCHE):
    analizador = Analizador(Modelos(), {"puerta": DetectorPuerta()})
    motor = MotorReglas(cfg.alarmas, cfg.motor)
    fps = verdad(ruta)["fps"]
    resultados, disparos = [], []
    for i, frame in enumerate(leer_video(ruta)):
        t = i / fps
        ctx, obs = analizador.analizar("sint", frame, t, cfg, [ZONA], ["puerta"], hora=hora)
        assert len(obs) == 1
        resultados.append((t, obs[0]))
        disparos += motor.procesar(obs)
    return resultados, disparos


@pytest.mark.parametrize("metodo", ["absdiff", "xor"])
def test_puerta_abierta_dispara_despues_de_2_segundos(cfg, videos_sinteticos, metodo):
    cfg = cfg.model_copy(deep=True)
    cfg.detectores.puerta.metodo = metodo
    cfg.detectores.puerta.horarios_permitidos = []
    resultados, disparos = correr(cfg, videos_sinteticos / "puerta.mp4")

    for t, o in resultados:
        if t < 4.0 or t >= 9.1:
            assert not o.activo, f"falso positivo en t={t:.2f} ({o.detalle})"
        if 4.0 <= t < 9.0:
            assert o.detalle["porcentaje"] > cfg.detectores.puerta.porcentaje_min, f"t={t:.2f}"
        if 6.1 <= t < 9.0:
            assert o.activo, f"debería estar activo en t={t:.2f}"
    assert len(disparos) == 1
    assert 6.0 <= disparos[0].t <= 6.3  # 4 s (apertura) + 2 s (duracion_min_s)


def test_puerta_en_horario_permitido_no_dispara(cfg, videos_sinteticos):
    cfg = cfg.model_copy(deep=True)
    cfg.detectores.puerta.horarios_permitidos = ["07:00-23:59"]
    _, disparos = correr(cfg, videos_sinteticos / "puerta.mp4", hora=datetime(2026, 10, 14, 12, 0))
    assert disparos == []


def test_en_horario():
    assert en_horario(datetime(2026, 1, 1, 12, 0), ["07:00-22:00"])
    assert not en_horario(datetime(2026, 1, 1, 23, 0), ["07:00-22:00"])
    assert en_horario(datetime(2026, 1, 1, 23, 0), ["22:00-06:00"])  # cruza medianoche
    assert en_horario(datetime(2026, 1, 1, 5, 0), ["22:00-06:00"])
    assert not en_horario(datetime(2026, 1, 1, 12, 0), [])
