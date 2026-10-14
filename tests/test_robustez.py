"""Robustez: reconexión de cámaras, cola de Telegram sin internet, errores de detectores y evaluador."""
import shutil
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import requests

from homeguard.analizador import Analizador
from homeguard.captura.camaras import Camara
from homeguard.config import CfgCamara, CfgCaptura, CfgTelegram
from homeguard.detectores.base import Detector
from homeguard.detectores.modelos import Modelos
from homeguard.detectores.puerta import DetectorPuerta
from homeguard.salidas.telegram import EnviadorTelegram, ErrorPermanente, TareaTelegram


def esperar(condicion, segundos=8.0):
    fin = time.time() + segundos
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return False


# -- cámaras -------------------------------------------------------------------------------

def test_camara_se_reconecta_cuando_aparece_la_fuente(tmp_path, videos_sinteticos):
    destino = tmp_path / "cam.mp4"
    cfg = CfgCaptura(reintento_inicial_s=0.1, reintento_max_s=0.2, timeout_sin_frames_s=1.0)
    cam = Camara("x", CfgCamara(nombre="X", fuente=str(destino)), cfg)
    cam.iniciar()
    try:
        assert esperar(lambda: cam.reconexiones >= 2)  # el archivo no existe: reintenta
        assert not cam.conectada and cam.leer() is None and "no existe" in cam.error
        shutil.copy(videos_sinteticos / "puerta.mp4", destino)  # "se enchufa" la cámara
        assert esperar(lambda: cam.conectada and cam.leer() is not None)
        n1 = cam.leer().numero
        assert esperar(lambda: cam.leer().numero > n1)  # sigue entregando frames nuevos
    finally:
        cam.detener()


def test_archivo_se_reproduce_en_bucle(videos_sinteticos):
    cam = Camara("x", CfgCamara(nombre="X", fuente=str(videos_sinteticos / "puerta.mp4")), CfgCaptura())
    cam.iniciar()
    try:
        # 180 frames a 15 FPS = 12 s; no esperamos tanto: verificamos que lee al ritmo real del video
        assert esperar(lambda: cam.leer() is not None)
        n0, t0 = cam.leer().numero, time.time()
        time.sleep(1.0)
        fps = (cam.leer().numero - n0) / (time.time() - t0)
        assert 10 <= fps <= 20
    finally:
        cam.detener()


# -- Telegram --------------------------------------------------------------------------------

def enviador(monkeypatch, fallos: list, **cfg) -> tuple[EnviadorTelegram, list]:
    resultados = []
    e = EnviadorTelegram("token", "123", CfgTelegram(reintento_max_s=0.05, **cfg),
                         al_terminar=lambda *a: resultados.append(a))
    intentos = {"n": 0}

    def enviar_falso(tarea):
        intentos["n"] += 1
        if fallos:
            raise fallos.pop(0)

    monkeypatch.setattr(e, "enviar_ahora", enviar_falso)
    return e, resultados


def test_telegram_reintenta_sin_internet_y_envia_despues(monkeypatch):
    sin_red = requests.ConnectionError("sin internet")
    e, resultados = enviador(monkeypatch, [sin_red, sin_red, sin_red])
    e.iniciar()
    try:
        t0 = time.time()
        e.encolar(TareaTelegram("ev1", "hola", b"jpg", t0))
        assert esperar(lambda: resultados)
        evento_id, latencia, estado = resultados[0]
        assert (evento_id, estado) == ("ev1", "enviado") and latencia >= 0
        assert not e.sin_conexion and e.ultimo_error is None
    finally:
        e.detener()


def test_telegram_no_bloquea_al_que_encola(monkeypatch):
    e, _ = enviador(monkeypatch, [requests.ConnectionError("x")] * 1000)
    e.iniciar()
    try:
        inicio = time.time()
        for i in range(50):
            e.encolar(TareaTelegram(f"ev{i}", "x", None, time.time()))
        assert time.time() - inicio < 0.05
    finally:
        e.detener()


def test_telegram_error_permanente_no_reintenta(monkeypatch):
    e, resultados = enviador(monkeypatch, [ErrorPermanente("HTTP 401")])
    e.iniciar()
    try:
        e.encolar(TareaTelegram("ev1", "x", None, time.time()))
        assert esperar(lambda: resultados)
        assert resultados[0][2] == "error"
    finally:
        e.detener()


def test_telegram_descarta_eventos_viejos(monkeypatch):
    e, resultados = enviador(monkeypatch, [], descartar_tras_min=1)
    e.iniciar()
    try:
        e.encolar(TareaTelegram("viejo", "x", None, time.time() - 120))
        assert esperar(lambda: resultados)
        assert resultados[0][2] == "error"
    finally:
        e.detener()


def test_telegram_sin_token_solo_registra():
    resultados = []
    e = EnviadorTelegram("", "", CfgTelegram(), al_terminar=lambda *a: resultados.append(a))
    assert not e.habilitado
    e.encolar(TareaTelegram("ev1", "x", None, time.time()))
    assert resultados == [("ev1", None, "desactivado")]


def test_sistema_reencola_pendientes_al_arrancar(sistema, monkeypatch):
    """Si se cerró el programa con eventos sin enviar, al arrancar se vuelven a encolar."""
    sistema.registro.guardar_evento(evento_id="pend", tipo="fuego", camara_id="c", zona="z", confianza=0.9,
                                    detalle={}, foto=None, t_deteccion=time.time(), telegram_estado="pendiente")
    sistema.telegram.habilitado = True
    encolados = []
    monkeypatch.setattr(sistema.telegram, "encolar", lambda t: encolados.append(t))
    monkeypatch.setattr(sistema.telegram, "iniciar", lambda: None)
    monkeypatch.setattr(sistema.pipeline, "iniciar", lambda: None)
    sistema.iniciar()
    assert [t.evento_id for t in encolados] == ["pend"]
    assert "envío diferido" in encolados[0].texto


# -- errores en detectores ---------------------------------------------------------------------

class DetectorRoto(Detector):
    nombre = "roto"
    tipo = "fuego"

    def procesar(self, frame, ctx):
        raise RuntimeError("falla simulada")


def test_un_detector_con_error_no_frena_a_los_demas(cfg):
    from homeguard.detectores.base import Zona

    analizador = Analizador(Modelos(), {"roto": DetectorRoto(), "puerta": DetectorPuerta()})
    zona = Zona(1, "c", "P", "puerta", [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]])
    frame = np.zeros((480, 640, 3), np.uint8)
    for i in range(3):
        _, obs = analizador.analizar("c", frame, i * 0.1, cfg, [zona], ["roto", "puerta"], hora=datetime.now())
        assert [o.tipo for o in obs] == ["puerta"]


def test_pipeline_sobrevive_a_un_error_en_el_ciclo(sistema, monkeypatch):
    llamadas = {"n": 0}

    def ciclo_que_falla(t):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("falla simulada")
        sistema.pipeline._detener.set()
        return t

    monkeypatch.setattr(sistema.pipeline, "_ciclo", ciclo_que_falla)
    monkeypatch.setattr(sistema.pipeline._detener, "wait", lambda s: None)
    h = threading.Thread(target=sistema.pipeline._bucle)
    h.start()
    h.join(3)
    assert llamadas["n"] == 2 and not h.is_alive()


# -- evaluador de detectores ---------------------------------------------------------------------

def test_evaluar_detector_puerta(tmp_path, videos_sinteticos):
    from scripts import evaluar_detector as ev

    (tmp_path / "positivos").mkdir()
    (tmp_path / "negativos").mkdir()
    shutil.copy(videos_sinteticos / "puerta.mp4", tmp_path / "positivos" / "abre.mp4")
    # negativo: la misma escena con la puerta siempre cerrada (primer frame repetido)
    cap = cv2.VideoCapture(str(videos_sinteticos / "puerta.mp4"))
    _, cerrada = cap.read()
    cap.release()
    w = cv2.VideoWriter(str(tmp_path / "negativos" / "cerrada.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 15, (640, 480))
    rng = np.random.default_rng(0)
    for _ in range(90):
        w.write(np.clip(cerrada.astype(int) + rng.integers(-3, 4, cerrada.shape), 0, 255).astype(np.uint8))
    w.release()
    # zona de la puerta al lado del video positivo; el negativo usa la misma por sidecar
    zona = '[{"nombre": "Puerta", "tipo": "puerta", "puntos": [[0.4,0.2],[0.6,0.2],[0.6,0.85],[0.4,0.85]]}]'
    (tmp_path / "positivos" / "abre.zonas.json").write_text(zona)
    (tmp_path / "negativos" / "cerrada.zonas.json").write_text(zona)

    salida = tmp_path / "PRUEBAS.md"
    salida.write_text("# Pruebas\n\n<!-- puerta:INICIO -->\n(pendiente)\n<!-- puerta:FIN -->\n", encoding="utf-8")
    assert ev.main(["--detector", "puerta", "--carpeta", str(tmp_path), "--salida", str(salida),
                    "--bd", str(tmp_path / "eval.db")]) == 0
    texto = salida.read_text(encoding="utf-8")
    assert "(pendiente)" not in texto
    assert "| 1 | 0 | 1 | 0 | 1.00 | 1.00 | 1.00 | 1.00 |" in texto
    assert "**VP**" in texto and "**VN**" in texto
