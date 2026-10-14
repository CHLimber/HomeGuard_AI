"""Servidor web (FastAPI): dashboard, panel de alarma, WebSockets, stream MJPEG y API."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from homeguard.web import api

if TYPE_CHECKING:
    from homeguard.sistema import Sistema

log = logging.getLogger(__name__)
SEGUNDOS_SIN_SENAL = 3.0
CARPETA_WEB = Path(__file__).resolve().parent


def _imagen_sin_senal(texto: str) -> bytes:
    img = np.zeros((360, 640, 3), np.uint8)
    img[:] = (40, 30, 30)
    cv2.putText(img, texto, (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA)
    return cv2.imencode(".jpg", img)[1].tobytes()


def crear_app(sistema: Sistema, iniciar_sistema: bool = True) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        sistema.ws.fijar_loop(asyncio.get_running_loop())
        if iniciar_sistema:
            sistema.iniciar()
        yield
        if iniciar_sistema:
            sistema.detener()

    app = FastAPI(title="HomeGuard AI", lifespan=ciclo_de_vida)
    app.state.sistema = sistema
    plantillas = Jinja2Templates(directory=str(CARPETA_WEB / "templates"))
    app.state.plantillas = plantillas
    app.mount("/static", StaticFiles(directory=str(CARPETA_WEB / "static")), name="static")
    app.mount("/fotos", StaticFiles(directory=str(sistema.registro.carpeta), check_dir=False), name="fotos")
    app.include_router(api.router)

    sin_senal = _imagen_sin_senal("Sin senal de la camara")

    # -- páginas ----------------------------------------------------------------

    def pagina(nombre: str, request: Request, **extra):
        contexto = {"demo": sistema.demo, "camaras": sistema.config.camaras, **extra}
        return plantillas.TemplateResponse(request, nombre, contexto)

    @app.get("/", include_in_schema=False)
    def inicio() -> RedirectResponse:
        return RedirectResponse("/en-vivo")

    @app.get("/alarma", include_in_schema=False)
    def panel_alarma(request: Request):
        return pagina("panel_alarma.html", request)

    @app.get("/en-vivo", include_in_schema=False)
    def en_vivo(request: Request):
        return pagina("en_vivo.html", request, seccion="en_vivo")

    @app.get("/calibracion", include_in_schema=False)
    def calibracion(request: Request):
        return pagina("calibracion.html", request, seccion="calibracion")

    @app.get("/residentes", include_in_schema=False)
    def residentes(request: Request):
        return pagina("residentes.html", request, seccion="residentes")

    @app.get("/zonas", include_in_schema=False)
    def zonas(request: Request):
        return pagina("zonas.html", request, seccion="zonas")

    @app.get("/configuracion", include_in_schema=False)
    def configuracion(request: Request):
        return pagina("configuracion.html", request, seccion="configuracion")

    @app.get("/historial", include_in_schema=False)
    def historial(request: Request):
        return pagina("historial.html", request, seccion="historial")

    # -- video ------------------------------------------------------------------

    @app.get("/stream/{camara_id}")
    async def stream(camara_id: str, request: Request) -> StreamingResponse:
        if camara_id not in sistema.config.camaras:
            raise HTTPException(404, "cámara desconocida")

        async def generador():
            ultimo = None
            while not await request.is_disconnected():
                jpeg = sistema.pipeline.jpeg.get(camara_id)
                if jpeg is None or time.time() - sistema.pipeline.jpeg_t.get(camara_id, 0) > SEGUNDOS_SIN_SENAL:
                    jpeg = sin_senal  # la cámara se cayó: no dejar congelada la última imagen
                if jpeg is not ultimo:
                    ultimo = jpeg
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                           + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                await asyncio.sleep(1.0 / sistema.config.procesamiento.fps_stream)

        return StreamingResponse(generador(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/snapshot/{camara_id}.jpg")
    def snapshot(camara_id: str) -> Response:
        """Frame crudo actual (sin anotaciones), al ancho de proceso: para el editor de zonas."""
        from homeguard.analizador import redimensionar

        cam = sistema.camaras.obtener(camara_id)
        capturado = cam.leer() if cam else None
        if capturado is None:
            return Response(sin_senal, media_type="image/jpeg")
        img = redimensionar(capturado.imagen, sistema.config.procesamiento.ancho_proceso)
        return Response(cv2.imencode(".jpg", img)[1].tobytes(), media_type="image/jpeg")

    # -- WebSockets -------------------------------------------------------------

    @app.websocket("/ws/alarma")
    async def ws_alarma(ws: WebSocket) -> None:
        await sistema.ws.conectar("alarma", ws)
        try:
            await ws.send_text(json.dumps(sistema.estado_actual(), default=str))
            while True:
                datos = json.loads(await ws.receive_text())
                accion = datos.get("accion")
                if accion == "ack" and datos.get("evento_id"):
                    await asyncio.to_thread(sistema.recibir_ack, str(datos["evento_id"]))
                elif accion == "silenciar":
                    await asyncio.to_thread(sistema.silenciar)
                elif accion == "ping":
                    await ws.send_text('{"tipo":"pong"}')
        except (WebSocketDisconnect, RuntimeError):
            pass
        except json.JSONDecodeError:
            log.warning("Mensaje inválido en /ws/alarma")
        finally:
            sistema.ws.desconectar("alarma", ws)

    @app.websocket("/ws/estado")
    async def ws_estado(ws: WebSocket) -> None:
        await sistema.ws.conectar("estado", ws)
        try:
            await ws.send_text(json.dumps(sistema.pipeline.telemetria(), default=str))
            while True:
                datos = json.loads(await ws.receive_text())
                if datos.get("accion") == "silenciar":
                    await asyncio.to_thread(sistema.silenciar)
        except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
            pass
        finally:
            sistema.ws.desconectar("estado", ws)

    return app
