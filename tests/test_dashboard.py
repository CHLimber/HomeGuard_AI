"""API del dashboard: zonas, referencia de puerta, configuración, residentes y cámaras."""
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from homeguard.captura.camaras import FrameCapturado
from homeguard.web.app import crear_app

ZONA = {"camara_id": "cam", "nombre": "Puerta", "tipo": "puerta",
        "puntos": [[0.4, 0.2], [0.6, 0.2], [0.6, 0.85], [0.4, 0.85]]}


class CamaraFalsa:
    def __init__(self):
        self.id = "cam"
        self.imagen = np.full((480, 640, 3), 120, np.uint8)

    def leer(self):
        return FrameCapturado(self.imagen, time.time(), 1)

    def resumen(self):
        return {"id": "cam", "nombre": "Falsa", "fuente": "0", "tipo": "webcam", "conectada": True,
                "fps_captura": 10.0, "error": None, "reconexiones": 0, "resolucion": "640x480"}

    def detener(self):
        pass


@pytest.fixture
def cliente(sistema):
    sistema.actualizar_overrides({})  # fuerza recarga
    from homeguard.config import CfgCamara

    sistema.config.camaras["cam"] = CfgCamara(nombre="Falsa", fuente=0, activa=True, detectores=["puerta"])
    sistema.camaras.camaras["cam"] = CamaraFalsa()
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        yield c


def test_paginas_del_dashboard(cliente):
    for ruta in ("/en-vivo", "/calibracion", "/zonas", "/residentes", "/configuracion", "/historial", "/alarma"):
        assert cliente.get(ruta).status_code == 200, ruta


def test_zonas_crud_y_referencia(cliente, sistema):
    r = cliente.post("/api/zonas", json=ZONA)
    assert r.status_code == 200
    zid = r.json()["id"]
    assert [z.nombre for z in sistema.zonas("cam")] == ["Puerta"]  # el pipeline ve la zona nueva

    assert cliente.post("/api/zonas", json={**ZONA, "tipo": "jardin"}).status_code == 400
    assert cliente.post("/api/zonas", json={**ZONA, "puntos": [[0, 0], [1, 1]]}).status_code == 400
    assert cliente.post("/api/zonas", json={**ZONA, "puntos": [[0, 0], [2, 0], [1, 1]]}).status_code == 400

    r = cliente.post(f"/api/zonas/{zid}/referencia")
    assert r.status_code == 200
    img = cliente.get(r.json()["referencia"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert sistema.zonas("cam")[0].referencia  # el detector de puerta la va a usar

    assert cliente.get("/api/zonas?camara=cam").json()["zonas"][0]["referencia"]
    assert cliente.delete(f"/api/zonas/{zid}").status_code == 200
    assert sistema.zonas("cam") == []


def test_snapshot_de_camara(cliente):
    r = cliente.get("/snapshot/cam.jpg")
    assert r.status_code == 200
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    assert img.shape[1] == 640


def test_config_leer_guardar_invalido_restaurar(cliente, sistema):
    datos = cliente.get("/api/config").json()
    assert datos["valores"]["detectores.puerta.porcentaje_min"] == 25.0
    assert "píxeles" in datos["descripciones"]["detectores.puerta.porcentaje_min"]  # sale del comentario de config.yaml

    r = cliente.post("/api/config", json={"cambios": {"detectores.puerta.porcentaje_min": 40}})
    assert r.status_code == 200
    assert sistema.config.detectores.puerta.porcentaje_min == 40
    assert cliente.get("/api/config").json()["overrides"] == {"detectores.puerta.porcentaje_min": 40}

    # valores inválidos se rechazan y no se guardan
    assert cliente.post("/api/config", json={"cambios": {"alarmas.fuego.votos_m": 1}}).status_code == 400  # M < N
    assert cliente.post("/api/config", json={"cambios": {"detectores.puerta.metodo": "magia"}}).status_code == 400
    assert cliente.post("/api/config", json={"cambios": {"general.base_datos": "x.db"}}).status_code == 400
    assert sistema.config.alarmas.fuego.votos_m == 5

    # el motor de reglas recibe la config nueva
    cliente.post("/api/config", json={"cambios": {"alarmas.puerta.cooldown_s": 5}})
    assert sistema.motor.alarmas.puerta.cooldown_s == 5

    assert cliente.post("/api/config/restaurar").status_code == 200
    assert sistema.config.detectores.puerta.porcentaje_min == 25.0


def test_editar_camara(ruta_config_prueba):
    import yaml

    from homeguard.db import modelos as m
    from homeguard.sistema import Sistema

    datos = yaml.safe_load(ruta_config_prueba.read_text(encoding="utf-8"))
    datos["camaras"] = {"patio": {"nombre": "Patio", "fuente": 0, "activa": False, "detectores": ["fuego"]}}
    ruta_config_prueba.write_text(yaml.safe_dump(datos), encoding="utf-8")
    sis = Sistema(sin_telegram=True, ruta_config=ruta_config_prueba)
    try:
        with TestClient(crear_app(sis, iniciar_sistema=False)) as c:
            r = c.post("/api/camaras/patio", json={"fuente": "http://192.168.0.9:8080/video", "activa": False})
            assert r.status_code == 200
            assert sis.config.camaras["patio"].fuente == "http://192.168.0.9:8080/video"
            with sis.bd.sesion() as s:
                assert s.get(m.Camara, "patio").fuente == "http://192.168.0.9:8080/video"
            assert c.post("/api/camaras/patio", json={"fuente": "1"}).status_code == 200
            assert sis.config.camaras["patio"].fuente == 1  # un número se guarda como índice de webcam
            assert c.post("/api/camaras/patio", json={"fuente": "  "}).status_code == 400
            assert c.post("/api/camaras/nada", json={"fuente": "0"}).status_code == 404
            assert c.get("/api/camaras").json()["camaras"][0]["id"] == "patio"
    finally:
        sis.camaras.detener_todas()
        sis.telegram.detener()
        sis.bd.cerrar()


def test_residentes_alta_y_baja(cliente, sistema, monkeypatch):
    from homeguard.detectores import rostros

    vector = rostros.normalizar(np.arange(128, dtype=np.float32))

    def falso(img, modelos, cfg, tamano_min=0, instancia=None):
        # una foto "con rostro" es la clara; la oscura no tiene rostro
        return [rostros.Rostro((10, 10, 50, 50), vector)] if img.mean() > 100 else []

    monkeypatch.setattr(rostros, "extraer_rostros", falso)
    clara = cv2.imencode(".png", np.full((60, 60, 3), 200, np.uint8))[1].tobytes()
    oscura = cv2.imencode(".png", np.zeros((60, 60, 3), np.uint8))[1].tobytes()
    archivos = [("fotos", ("a.png", clara, "image/png")), ("fotos", ("b.png", clara, "image/png")),
                ("fotos", ("c.png", oscura, "image/png")), ("fotos", ("d.txt", b"hola", "text/plain"))]
    r = cliente.post("/api/residentes", data={"nombre": "Ana"}, files=archivos)
    assert r.status_code == 200, r.text
    assert r.json()["aceptadas"] == 2 and len(r.json()["rechazadas"]) == 2
    assert sistema.pipeline.analizador.detectores["rostros"].cantidad_residentes == 1

    lista = cliente.get("/api/residentes").json()["residentes"]
    assert lista[0]["nombre"] == "Ana" and lista[0]["vectores"] == 2

    r = cliente.post("/api/residentes", data={"nombre": "Nadie"}, files=[("fotos", ("c.png", oscura, "image/png"))])
    assert r.status_code == 400

    assert cliente.delete(f"/api/residentes/{lista[0]['id']}").status_code == 200
    assert sistema.pipeline.analizador.detectores["rostros"].cantidad_residentes == 0
    with sistema.bd.sesion() as s:
        from sqlalchemy import func, select

        from homeguard.db import modelos as m
        assert s.scalar(select(func.count()).select_from(m.EmbeddingRostro)) == 0  # borrado en cascada
