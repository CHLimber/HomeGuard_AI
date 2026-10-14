"""Detector de rostros: comparación coseno, zona, condición de persona y K frames consecutivos."""
from datetime import datetime

import numpy as np
import supervision as sv

from homeguard.analizador import Analizador
from homeguard.detectores.base import Zona
from homeguard.detectores.modelos import Modelos
from homeguard.detectores.rostros import DetectorRostros, Rostro, comparar, normalizar
from homeguard.reglas.motor import MotorReglas

ACCESO = Zona(1, "sint", "Entrada", "acceso", [[0.25, 0.0], [0.75, 0.0], [0.75, 1.0], [0.25, 1.0]])
rng = np.random.default_rng(7)
ANA = normalizar(rng.normal(size=128))
BETO = normalizar(rng.normal(size=128))
EXTRANO = normalizar(rng.normal(size=128))


def parecido(base: np.ndarray, ruido: float) -> np.ndarray:
    return normalizar(base + rng.normal(scale=ruido, size=128))


def test_comparar_coseno():
    residentes = np.stack([ANA, BETO])
    sim, nombre = comparar(parecido(ANA, 0.02), residentes, ["Ana", "Beto"])
    assert nombre == "Ana" and sim > 0.9
    sim, _ = comparar(EXTRANO, residentes, ["Ana", "Beto"])
    assert sim < 0.363  # vectores al azar en 128 dimensiones: coseno cercano a 0
    assert comparar(ANA, np.zeros((0, 128), np.float32), []) == (-1.0, None)


def correr(cfg, embedding_por_frame, persona_en_zona=True, cara_x=300, frames=20):
    caras = iter(embedding_por_frame)

    def detectar_falso(recorte, c):
        emb = next(caras)
        # la caja es relativa al recorte de la zona (que empieza en x = 0.25 * 640 = 160)
        return [] if emb is None else [Rostro((cara_x - 160, 100, 60, 60), emb)]

    def yolo_falso(frame):
        caja = [250, 50, 350, 400] if persona_en_zona else [10, 50, 100, 400]
        return sv.Detections(xyxy=np.array([caja], np.float32), confidence=np.array([0.9], np.float32),
                             class_id=np.array([0]))

    detector = DetectorRostros(Modelos(), detectar=detectar_falso)
    detector.fijar_residentes(np.stack([ANA, BETO]), ["Ana", "Beto"])
    analizador = Analizador(Modelos(), {"rostros": detector})
    analizador.detector_general = yolo_falso
    motor = MotorReglas(cfg.alarmas, cfg.motor)
    frame = np.zeros((480, 640, 3), np.uint8)
    obs_t, disparos = [], []
    for i in range(frames):
        _, obs = analizador.analizar("sint", frame, i / 10, cfg, [ACCESO], ["rostros"], hora=datetime.now())
        obs_t.append(obs[0])
        disparos += motor.procesar(obs)
    return obs_t, disparos


def test_residente_no_dispara(cfg):
    obs, disparos = correr(cfg, [parecido(ANA, 0.05) for _ in range(20)])
    assert disparos == [] and not any(o.activo for o in obs)


def test_desconocido_k_frames_consecutivos_dispara(cfg):
    k = cfg.alarmas.intrusion.votos_n
    _, disparos = correr(cfg, [EXTRANO] * 20)
    assert len(disparos) == 1 and abs(disparos[0].t - (k - 1) / 10) < 1e-6


def test_desconocido_intermitente_no_dispara(cfg):
    secuencia = [EXTRANO, EXTRANO, None, EXTRANO, EXTRANO, EXTRANO, None] * 3
    _, disparos = correr(cfg, secuencia[:20])
    assert disparos == []  # nunca 5 frames seguidos


def test_sin_persona_en_zona_no_busca_rostros(cfg):
    llamadas = []
    obs, disparos = correr(cfg, iter(lambda: llamadas.append(1) or EXTRANO, None), persona_en_zona=False)
    assert llamadas == [] and disparos == []
    assert all(o.detalle["personas"] == 0 for o in obs)


def test_rostro_fuera_del_poligono_se_ignora(cfg):
    obs, disparos = correr(cfg, [EXTRANO] * 20, cara_x=30)  # cara en x=30, fuera de la zona (x 160..480)
    assert disparos == [] and all(o.detalle["rostros"] == 0 for o in obs)
