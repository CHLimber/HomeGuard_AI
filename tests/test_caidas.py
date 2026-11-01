"""Detector de caídas con secuencias de pose simuladas (no hace falta el modelo)."""
from datetime import datetime

import numpy as np

from homeguard.analizador import Analizador
from homeguard.detectores.caidas import DetectorCaidas, Persona, angulo_torso
from homeguard.detectores.modelos import Modelos
from homeguard.reglas.motor import MotorReglas

FPS = 10


def de_pie(cx=200.0, pie=400.0, alto=240.0) -> Persona:
    x0, x1, y0, y1 = cx - 35, cx + 35, pie - alto, pie
    kps = np.zeros((17, 2), np.float32)
    kps[5], kps[6] = (cx - 20, y0 + 50), (cx + 20, y0 + 50)      # hombros arriba
    kps[11], kps[12] = (cx - 15, y0 + 130), (cx + 15, y0 + 130)  # caderas abajo
    return Persona((x0, y0, x1, y1), kps, np.ones(17, np.float32))


def acostado(cx=200.0, piso=400.0, largo=220.0) -> Persona:
    x0, x1, y0, y1 = cx - largo / 2, cx + largo / 2, piso - 70, piso
    kps = np.zeros((17, 2), np.float32)
    kps[5], kps[6] = (x0 + 40, y0 + 25), (x0 + 40, y0 + 45)        # hombros a la izquierda
    kps[11], kps[12] = (x0 + 120, y0 + 30), (x0 + 120, y0 + 50)    # caderas a la derecha, casi misma altura
    return Persona((x0, y0, x1, y1), kps, np.ones(17, np.float32))


def correr(cfg, secuencia):
    """secuencia: función t -> list[Persona]. Devuelve (observaciones con t, disparos)."""
    reloj = {"t": 0.0}
    detector = DetectorCaidas(Modelos(), inferir_pose=lambda frame, c: secuencia(reloj["t"]))
    analizador = Analizador(Modelos(), {"caidas": detector})
    motor = MotorReglas(cfg.alarmas, cfg.motor)
    frame = np.zeros((480, 640, 3), np.uint8)
    obs_t, disparos = [], []
    for i in range(12 * FPS):
        reloj["t"] = t = i / FPS
        _, obs = analizador.analizar("sint", frame, t, cfg, [], ["caidas"], hora=datetime.now())
        for o in obs:
            obs_t.append((t, o))
        disparos += motor.procesar(obs)
    return obs_t, disparos


def test_angulo_torso():
    assert angulo_torso(de_pie(), 0.3) > 80
    assert angulo_torso(acostado(), 0.3) < 15
    sin_kps = de_pie()
    sin_kps.conf_keypoints[:] = 0
    assert angulo_torso(sin_kps, 0.3) is None


def test_caida_brusca_e_inmovil_dispara(cfg):
    _, disparos = correr(cfg, lambda t: [de_pie()] if t < 2.0 else [acostado()])
    assert len(disparos) == 1
    assert 5.0 <= disparos[0].t <= 5.5  # caída en t=2 s + 3 s de inmovilidad


def test_pose_cada_n_frames(cfg):
    obs_t, _ = correr(cfg, lambda t: [de_pie()])
    assert len(obs_t) == 12 * FPS // cfg.detectores.caidas.cada_n_frames


def test_acostado_desde_el_principio_no_es_caida(cfg):
    _, disparos = correr(cfg, lambda t: [acostado()])
    assert disparos == []


def test_se_levanta_antes_de_3_segundos(cfg):
    _, disparos = correr(cfg, lambda t: [de_pie()] if t < 2.0 or t >= 4.0 else [acostado()])
    assert disparos == []


def test_descenso_lento_no_es_caida(cfg):
    """Se agacha de a poco durante 4 s (acostarse a propósito): nunca hay un descenso brusco en < 1 s."""
    def secuencia(t):
        if t < 2.0:
            return [de_pie()]
        if t < 6.0:  # baja gradualmente: la altura se reduce sin quedar horizontal
            return [de_pie(alto=240 - (t - 2.0) * 40)]
        return [acostado()]
    _, disparos = correr(cfg, secuencia)
    assert disparos == []


def test_se_mueve_en_el_suelo_reinicia_inmovilidad(cfg):
    def secuencia(t):
        if t < 2.0:
            return [de_pie()]
        if t < 5.0:  # se arrastra
            return [acostado(cx=200 + (t - 2.0) * 30)]
        return [acostado(cx=290)]
    _, disparos = correr(cfg, secuencia)
    # sin arrastre dispararía en t=5 s; el ancla se reinicia mientras se mueve más de la tolerancia (15 % de
    # los 220 px del cuerpo = 33 px; último reinicio en t=4,4 s, el tramo final de 18 px queda dentro), así que
    # dispara en t=7,4 s
    assert len(disparos) == 1 and 7.0 <= disparos[0].t <= 8.0


def test_ruido_de_la_pose_en_el_suelo_no_reinicia_inmovilidad(cfg):
    """El centro de un cuerpo grande tiembla ±15 px (30 de pico a pico) por el ruido de la pose: no es movimiento
    (la tolerancia es el 15 % de los 220 px del cuerpo = 33 px; con los 20 px fijos de antes reiniciaba la cuenta)."""
    _, disparos = correr(cfg, lambda t: [de_pie()] if t < 2.0 else [acostado(cx=200 + (15 if int(t * 5) % 2 else -15))])
    assert len(disparos) == 1 and 5.0 <= disparos[0].t <= 5.5


def test_detecciones_de_pie_falsas_sobre_la_caida_no_la_cancelan(cfg):
    """Tendida en el suelo, la pose a ratos devuelve un recuadro «de pie» al ras del suelo: no es que se levantó."""
    def secuencia(t):
        if t < 2.0:
            return [de_pie()]
        return [de_pie(cx=205, pie=400, alto=100)] if int(t * 5) % 3 == 0 else [acostado()]  # centro 15 px más arriba
    _, disparos = correr(cfg, secuencia)
    assert len(disparos) == 1


def test_si_la_pose_pierde_a_la_persona_caida_sigue_contando(cfg):
    """Acostada se detecta mal: si deja de verse (sin que nadie se levante) la caída se mantiene hasta olvidar_tras_s."""
    _, disparos = correr(cfg, lambda t: [de_pie()] if t < 2.0 else [acostado()] if t < 2.6 else [])
    assert len(disparos) == 1 and 5.0 <= disparos[0].t <= 5.5


def test_se_sienta_claramente_mas_arriba_cancela_la_caida(cfg):
    """Sentada (160 px de alto: su centro queda 45 px más arriba que acostada, más del 25 % de su altura) se levantó."""
    _, disparos = correr(cfg, lambda t: [de_pie()] if t < 2.0 else [acostado()] if t < 3.0 else [de_pie(pie=400, alto=160)])
    assert disparos == []
