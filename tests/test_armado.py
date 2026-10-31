"""Armar/desarmar el sistema y probabilidad de falsa alarma de la votación N de M."""
import math

import pytest
from fastapi.testclient import TestClient

from homeguard.db import consultas
from homeguard.reglas import estado as est
from homeguard.reglas.motor import probabilidad_falsa_alarma
from homeguard.web.app import crear_app
from tests.test_motor import alimentar, motor


# -- P(falsa alarma) ------------------------------------------------------------------

def test_binomial_ejemplo_del_docstring():
    # p = 0,05, N = 3, M = 5 calculado a mano término por término
    a_mano = 10 * 0.05 ** 3 * 0.95 ** 2 + 5 * 0.05 ** 4 * 0.95 + 0.05 ** 5
    assert probabilidad_falsa_alarma(0.05, 3, 5) == pytest.approx(a_mano)
    assert round(probabilidad_falsa_alarma(0.05, 3, 5), 5) == 0.00116


def test_binomial_casos_borde():
    assert probabilidad_falsa_alarma(0.2, 1, 1) == pytest.approx(0.2)        # 1 de 1 = p
    assert probabilidad_falsa_alarma(0.2, 5, 5) == pytest.approx(0.2 ** 5)   # N = M = p^M
    assert probabilidad_falsa_alarma(0.0, 3, 5) == 0.0
    assert probabilidad_falsa_alarma(1.0, 3, 5) == pytest.approx(1.0)
    # 1 de M = 1 - P(ningún falso positivo)
    assert probabilidad_falsa_alarma(0.1, 1, 4) == pytest.approx(1 - 0.9 ** 4)
    # más votos exigidos => menos falsas alarmas
    assert probabilidad_falsa_alarma(0.1, 4, 5) < probabilidad_falsa_alarma(0.1, 3, 5)
    assert sum(math.comb(5, k) * 0.3 ** k * 0.7 ** (5 - k) for k in range(6)) == pytest.approx(1.0)


def test_binomial_valida_parametros():
    with pytest.raises(ValueError):
        probabilidad_falsa_alarma(1.5, 3, 5)
    with pytest.raises(ValueError):
        probabilidad_falsa_alarma(0.1, 6, 5)


def test_api_falsa_alarma_usa_n_y_m_de_la_config(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        r = c.get("/api/falsa-alarma", params={"p": 0.05}).json()
        assert set(r["anomalias"]) == set(est.BIT_POR_TIPO)
        for tipo, a in r["anomalias"].items():
            regla = getattr(sistema.config.alarmas, tipo)
            assert (a["n"], a["m"]) == (regla.votos_n, regla.votos_m)
            assert a["probabilidad"] == pytest.approx(probabilidad_falsa_alarma(0.05, a["n"], a["m"]))
        assert c.get("/api/falsa-alarma", params={"p": 2}).status_code == 400
        assert "falsa alarma" in c.get("/calibracion").text


# -- motor armado/desarmado -------------------------------------------------------------

def test_desarmado_no_dispara_y_limpia_estado():
    mt = motor(3, 5)
    alimentar(mt, [1, 1, 1])
    assert mt.estado == est.FUEGO
    mt.fijar_armado(False)
    assert mt.estado == 0
    assert alimentar(mt, [1, 1, 1, 1, 1], t0=100) == []
    assert mt.estado == 0 and mt.activos == 0


def test_rearmar_reinicia_ventanas_de_votacion():
    mt = motor(3, 5, cooldown=0)
    alimentar(mt, [1, 1])                    # 2 votos, no alcanza
    mt.fijar_armado(False)
    mt.fijar_armado(True)
    assert alimentar(mt, [1], t0=10) == []   # los 2 votos de antes no cuentan
    assert len(alimentar(mt, [1, 1], t0=11)) == 1


# -- sistema, API y WebSockets -----------------------------------------------------------

def test_armado_se_persiste_y_no_es_override(sistema, ruta_config_prueba):
    from homeguard.sistema import Sistema

    assert sistema.motor.armado is True
    sistema.fijar_armado(False)
    assert consultas.leer_armado(sistema.bd) is False
    assert sistema.leer_overrides() == {}            # no se valida contra config.yaml
    sistema.restaurar_config()                       # restaurar no lo borra
    assert consultas.leer_armado(sistema.bd) is False
    sistema.telegram.detener()
    sistema.bd.cerrar()

    otro = Sistema(sin_telegram=True, ruta_config=ruta_config_prueba)  # "reinicio"
    try:
        assert otro.motor.armado is False
        assert otro.estado_actual()["armado"] is False
    finally:
        otro.telegram.detener()
        otro.bd.cerrar()


def test_api_armado_y_aviso_por_websocket(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        assert c.get("/api/armado").json() == {"armado": True}
        with c.websocket_connect("/ws/alarma") as ws:
            assert ws.receive_json()["armado"] is True
            sistema.motor.estado = est.PUERTA
            assert c.post("/api/armado", json={"armado": False}).json() == {"armado": False}
            msg = ws.receive_json()
            assert msg["tipo"] == "estado" and msg["armado"] is False and msg["estado"] == 0
        assert sistema.pipeline.telemetria()["armado"] is False
        assert c.post("/api/armado", json={"armado": True}).json() == {"armado": True}
        assert sistema.motor.armado is True
        assert c.post("/api/armado", json={}).status_code == 422
        assert "Armar sistema" in c.get("/configuracion").text
