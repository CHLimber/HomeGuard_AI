"""Prueba con video (modo exposición): subir medios, reproducirlos como cámara y que disparen la alarma."""
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from homeguard.analizador import Analizador
from homeguard.captura.camaras import Camara
from homeguard.config import CfgCamara, CfgCaptura
from homeguard.db import modelos as m
from homeguard.detectores.base import Zona
from homeguard.detectores.fuego import DetectorFuego
from homeguard.detectores.modelos import Modelos
from homeguard.reglas.motor import MotorReglas
from homeguard.web.app import crear_app
from tests.conftest import leer_video
from tests.test_fuego import Capa2Falsa


def esperar(condicion, segundos: float = 6.0):
    limite = time.time() + segundos
    while time.time() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(0.05)
    return None


@pytest.fixture
def cliente(sistema):
    with TestClient(crear_app(sistema, iniciar_sistema=False)) as c:
        yield c
    sistema.pipeline.detener()
    sistema.camaras.detener_todas()


def subir(cliente, archivos: list[tuple[str, bytes]], detectores: list[str], **extra):
    datos = {"nombre": "Prueba", "detectores": detectores, **{k: str(v).lower() for k, v in extra.items()}}
    return cliente.post("/api/pruebas", data=datos, files=[("archivos", (n, b)) for n, b in archivos])


def jpg(imagen: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", imagen)[1].tobytes()


def test_subir_video_y_reproducir_como_camara(cliente, sistema, videos_sinteticos):
    video = (videos_sinteticos / "puerta.mp4").read_bytes()
    r = subir(cliente, [("puerta.mp4", video)], ["puerta"])
    assert r.status_code == 200, r.text
    medio = r.json()
    cid = medio["camara_id"]
    assert medio["tipo"] == "video" and medio["duracion_s"] == pytest.approx(12, abs=0.5)
    assert cid in sistema.config.camaras and sistema.config.camaras[cid].activa
    assert [z.tipo for z in sistema.zonas(cid)] == ["puerta"]  # zona de cuadro completo

    cam = esperar(lambda: sistema.camaras.obtener(cid))
    assert cam is not None and esperar(cam.leer) is not None  # la cámara virtual entrega frames

    lista = cliente.get("/api/pruebas").json()
    assert lista["activa"] == cid and lista["medios"][0]["activa"]
    assert cid not in [c["id"] for c in cliente.get("/api/camaras").json()["camaras"]]  # no se mezcla con las reales
    assert cliente.post(f"/api/camaras/{cid}", json={"activa": False}).status_code == 400
    assert cliente.get("/prueba").status_code == 200

    assert cliente.post("/api/pruebas/detener").json() == {"activa": None}
    assert sistema.camaras.obtener(cid) is None and not sistema.config.camaras[cid].activa


def test_presentacion_de_fotos_dispara_la_puerta_de_punta_a_punta(cliente, sistema, videos_sinteticos):
    frames = list(leer_video(videos_sinteticos / "puerta.mp4"))
    cerrada, abierta = frames[0], frames[90]  # el sintético abre la puerta entre 4 y 9 s (15 FPS)
    fotos = [("1.jpg", jpg(cerrada)), ("2.jpg", jpg(abierta)), ("3.jpg", jpg(abierta)), ("4.jpg", jpg(abierta))]
    r = subir(cliente, fotos, ["puerta"], segundos_por_imagen=1, zonas_completas=False, reproducir=False)
    assert r.status_code == 200, r.text
    cid = r.json()["camara_id"]
    assert r.json()["imagenes"] == 4 and sistema.zonas(cid) == []
    # la puerta sintética ocupa una franja del cuadro: con todo el cuadro como zona solo cambia ~10 % (< 25 %),
    # así que se dibuja la zona sobre la puerta, como se haría en la página Zonas
    zona = {"camara_id": cid, "nombre": "Puerta", "tipo": "puerta",
            "puntos": [[0.40, 0.20], [0.60, 0.20], [0.60, 0.85], [0.40, 0.85]]}
    assert cliente.post("/api/zonas", json=zona).status_code == 200
    cliente.post(f"/api/pruebas/{r.json()['id']}/reproducir")

    sistema.pipeline.iniciar()
    evento = esperar(lambda: sistema.ultimo_evento, segundos=8)
    assert evento is not None, "la presentación cerrada -> abierta no disparó la alarma de la puerta"
    assert evento["tipo"] == "puerta" and evento["camara_id"] == cid and evento["camara"] == "Prueba: Prueba"
    with sistema.bd.sesion() as s:
        assert s.scalars(select(m.Evento).where(m.Evento.camara_id == cid)).first() is not None

    # "Reproducir" de nuevo borra el cooldown de esa cámara: la alarma puede volver a sonar
    assert sistema.motor._ultimo_disparo
    cliente.post(f"/api/pruebas/{r.json()['id']}/reproducir")
    assert not [c for c in sistema.motor._ultimo_disparo if c[1] == cid]


def test_fuego_en_imagen_fija_usa_solo_el_color(cfg, videos_sinteticos):
    frames = list(leer_video(videos_sinteticos / "fuego.mp4"))
    llama = frames[100]  # entre 3 y 10 s hay una llama naranja
    zona = Zona(id=1, camara_id="foto", nombre="Cocina", tipo="fuego",
                puntos=[[0.20, 0.25], [0.80, 0.25], [0.80, 0.90], [0.20, 0.90]])

    def correr(estatica: bool) -> list:
        detector = DetectorFuego(Modelos(), inferir_capa2=Capa2Falsa(0.9))
        analizador = Analizador(Modelos(), {"fuego": detector})
        motor = MotorReglas(cfg.alarmas, cfg.motor)
        disparos = []
        for i in range(10):  # la misma foto repetida: el XOR entre frames da cero movimiento
            _, obs = analizador.analizar("foto", llama, i / 10, cfg, [zona], ["fuego"], hora=datetime.now(),
                                         fuente_estatica=estatica)
            disparos += motor.procesar(obs)
        return disparos

    assert correr(estatica=False) == []          # cámara normal: sin movimiento no hay capa 1
    assert [d.tipo for d in correr(estatica=True)] == ["fuego"]


def test_camara_de_carpeta_pasa_las_fotos_en_orden(tmp_path):
    for i, gris in enumerate((50, 200), start=1):
        cv2.imwrite(str(tmp_path / f"{i}.png"), np.full((48, 64, 3), gris, np.uint8))
    cam = Camara("fotos", CfgCamara(nombre="Fotos", fuente=str(tmp_path), segundos_por_imagen=0.3), CfgCaptura())
    assert cam.tipo_fuente == "imagenes"
    cam.iniciar()
    try:
        assert esperar(lambda: cam.leer() is not None and cam.leer().imagen[0, 0, 0] == 50, 2)
        assert esperar(lambda: cam.leer().imagen[0, 0, 0] == 200, 2)
        assert esperar(lambda: cam.leer().imagen[0, 0, 0] == 50, 2)  # vuelve a empezar (bucle)
    finally:
        cam.detener()


def test_rechaza_archivos_invalidos_sin_dejar_basura(cliente, sistema, ruta_config_prueba):
    carpeta = ruta_config_prueba.parent / "pruebas"
    foto = jpg(np.full((48, 64, 3), 90, np.uint8))
    assert subir(cliente, [("a.jpg", foto)], []).status_code == 400                      # sin anomalía
    assert subir(cliente, [("a.jpg", foto), ("b.mp4", b"x")], ["fuego"]).status_code == 400  # mezcla
    assert subir(cliente, [("a.txt", b"hola")], ["fuego"]).status_code == 400            # formato
    r = subir(cliente, [("roto.mp4", b"esto no es un video")], ["fuego"])
    assert r.status_code == 400 and "OpenCV" in r.json()["detail"]
    assert subir(cliente, [("roto.jpg", b"no es imagen")], ["fuego"]).status_code == 400
    assert not carpeta.exists() or not any(carpeta.iterdir())
    assert cliente.get("/api/pruebas").json()["medios"] == []


def test_borrar_prueba_quita_archivo_zonas_y_camara(cliente, sistema):
    r = subir(cliente, [("1.jpg", jpg(np.full((48, 64, 3), 90, np.uint8)))], ["rostros", "caidas"])
    assert r.status_code == 200, r.text
    medio = r.json()
    cid = medio["camara_id"]
    assert [z.tipo for z in sistema.zonas(cid)] == ["acceso"]  # caídas no necesita zona
    carpeta = Path(sistema.config.camaras[cid].fuente)
    assert carpeta.is_dir()

    assert cliente.delete(f"/api/pruebas/{medio['id']}").status_code == 200
    assert not carpeta.exists() and cid not in sistema.config.camaras
    assert sistema.zonas(cid) == [] and sistema.prueba_activa is None
    assert cliente.delete(f"/api/pruebas/{medio['id']}").status_code == 404


def test_reiniciar_camara_solo_borra_esa_camara(cfg):
    from homeguard.detectores.base import PosibleEvento

    motor = MotorReglas(cfg.alarmas, cfg.motor)
    for cam in ("a", "b"):
        motor.procesar([PosibleEvento(tipo="puerta", camara_id=cam, zona="z", activo=True, confianza=1.0, t=1.0)])
    assert {c[1] for c in motor._ultimo_disparo} == {"a", "b"}
    motor.reiniciar_camara("a")
    assert {c[1] for c in motor._ultimo_disparo} == {"b"}


@pytest.fixture
def servidor_videos(videos_sinteticos, tmp_path):
    """Sirve los videos sintéticos (y una página HTML) por HTTP local, para probar el alta desde un enlace."""
    import functools
    import shutil
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    shutil.copy(videos_sinteticos / "puerta.mp4", tmp_path / "puerta.mp4")
    (tmp_path / "pagina.html").write_text("<html>no soy un video</html>", encoding="utf-8")

    class Manejador(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Manejador, directory=str(tmp_path)))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{servidor.server_port}"
    servidor.shutdown()


def desde_enlace(cliente, enlace: str, detectores: list[str] = ["puerta"]):
    return cliente.post("/api/pruebas", data={"nombre": "Enlace", "detectores": detectores, "enlace": enlace,
                                              "reproducir": "false"})


def test_prueba_desde_enlace_directo(cliente, sistema, servidor_videos):
    r = desde_enlace(cliente, f"{servidor_videos}/puerta.mp4")
    assert r.status_code == 200, r.text
    medio = r.json()
    assert medio["tipo"] == "video" and medio["duracion_s"] == pytest.approx(12, abs=0.5)
    assert Path(sistema.config.camaras[medio["camara_id"]].fuente).exists()  # quedó guardado en disco
    assert [z.tipo for z in sistema.zonas(medio["camara_id"])] == ["puerta"]


def test_prueba_desde_enlace_invalido(cliente, sistema, servidor_videos):
    assert "http" in desde_enlace(cliente, "ftp://servidor/video.mp4").json()["detail"]
    assert "página web" in desde_enlace(cliente, f"{servidor_videos}/pagina.html").json()["detail"]
    assert desde_enlace(cliente, f"{servidor_videos}/no_existe.mp4").status_code == 400
    assert cliente.get("/api/pruebas").json()["medios"] == []  # no queda nada a medias
    carpeta = Path(sistema.config.general.carpeta_pruebas)
    assert not carpeta.exists() or not any(carpeta.iterdir())


def test_prueba_desde_youtube_sin_yt_dlp(cliente, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "yt_dlp", None)  # simula que no está instalado
    r = desde_enlace(cliente, "https://www.youtube.com/watch?v=abc")
    assert r.status_code == 400 and "yt-dlp" in r.json()["detail"]
