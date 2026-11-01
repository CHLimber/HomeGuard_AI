"""Endpoints de FastAPI y WebSocket del panel (incluye ack y latencia)."""
import time

import numpy as np
from fastapi.testclient import TestClient

from homeguard.db import modelos as m
from homeguard.reglas.motor import Disparo
from homeguard.web.app import crear_app


def disparo_falso(sistema, tipo="puerta") -> Disparo:
    sistema.motor.estado |= 16
    return Disparo(tipo=tipo, camara_id="laptop", zona="Puerta principal", t=time.time(), confianza=0.9,
                   votos=1, estado=sistema.motor.estado, detalle={"porcentaje": 80.0})


def test_paginas_responden(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        for ruta in ("/alarma", "/en-vivo"):
            r = c.get(ruta)
            assert r.status_code == 200, ruta
        assert "ARMAR ALARMA" in c.get("/alarma").text
        assert c.get("/", follow_redirects=False).status_code in (302, 307)


def test_en_vivo_detiene_y_activa_camaras(sistema):
    """En vivo muestra las cámaras detenidas con «Activar» y las activas con «Detener»."""
    sistema.actualizar_overrides({"camaras.cam1": {"nombre": "Cámara 1", "fuente": "no_existe.mp4",
                                                   "activa": False, "detectores": ["puerta"]}})
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        html = c.get("/en-vivo").text
        assert "Cámara 1" in html and "Activar" in html and "/stream/cam1" not in html
        assert c.post("/api/camaras/cam1", json={"activa": True}).status_code == 200
        html = c.get("/en-vivo").text
        assert "Detener" in html and "/stream/cam1" in html
    sistema.camaras.detener_todas()


def test_api_estado_y_silenciar(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        sistema.motor.estado = 0b10100
        assert c.get("/api/estado").json()["estado"] == 20
        assert c.post("/api/silenciar").json()["estado"] == 0
        assert sistema.motor.estado == 0


def test_websocket_alerta_ack_y_latencia(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        with c.websocket_connect("/ws/alarma") as ws:
            inicial = ws.receive_json()
            assert inicial["tipo"] == "estado" and inicial["estado"] == 0

            frame = np.zeros((480, 640, 3), np.uint8)
            evento = sistema.despachar(disparo_falso(sistema), frame)  # desde otro hilo (el del test)
            msg = ws.receive_json()
            while msg["tipo"] != "alerta":
                msg = ws.receive_json()
            assert msg["estado"] == 16 and msg["evento"]["id"] == evento["id"]
            assert msg["evento"]["tipo"] == "puerta"

            ws.send_json({"accion": "ack", "evento_id": evento["id"]})
            ws.send_json({"accion": "ping"})
            while ws.receive_json()["tipo"] != "pong":
                pass

            with sistema.bd.sesion() as s:
                ev = s.get(m.Evento, evento["id"])
                assert ev is not None and ev.latencia_panel_ms is not None
                assert 0 <= ev.latencia_panel_ms < 2000
                assert ev.foto and (sistema.registro.carpeta / ev.foto).exists()

            ws.send_json({"accion": "silenciar"})
            msg = ws.receive_json()
            while msg.get("tipo") != "estado":
                msg = ws.receive_json()
            assert msg["estado"] == 0 and sistema.motor.estado == 0


def test_historial_y_csv(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        sistema.despachar(disparo_falso(sistema), np.zeros((240, 320, 3), np.uint8))
        datos = c.get("/api/eventos").json()
        assert len(datos["eventos"]) == 1 and datos["eventos"][0]["tipo"] == "puerta"
        assert c.get("/api/eventos?tipo=fuego").json()["eventos"] == []
        csv = c.get("/api/eventos.csv")
        assert csv.status_code == 200 and "latencia_panel_ms" in csv.text
        foto = datos["eventos"][0]["foto"]
        assert c.get(foto).status_code == 200


def test_ws_estado_envia_telemetria(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        with c.websocket_connect("/ws/estado") as ws:
            t = ws.receive_json()
            assert t["tipo"] == "telemetria" and "cpu_sistema" in t and "estado" in t
