"""Gestor de conexiones WebSocket y broadcast seguro entre hilos.

FastAPI/uvicorn corre en el hilo principal con su loop de asyncio; el pipeline
corre en otro hilo. Para enviar desde el pipeline se usa
`asyncio.run_coroutine_threadsafe(..., loop)`, que agenda la corrutina en el
loop de FastAPI sin bloquear al hilo de procesamiento.

Canales:
  - "alarma": paneles de alarma (/ws/alarma)
  - "estado": dashboard (/ws/estado): semáforo, FPS, CPU, calibración
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger(__name__)

TIMEOUT_ENVIO_S = 2.0  # un cliente lento no puede trabar a los demás


class GestorWebSocket:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.conexiones: dict[str, set[WebSocket]] = {"alarma": set(), "estado": set()}

    def fijar_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def conectar(self, canal: str, ws: WebSocket) -> None:
        await ws.accept()
        self.conexiones[canal].add(ws)
        log.info("WebSocket %s conectado (%d clientes)", canal, len(self.conexiones[canal]))

    def desconectar(self, canal: str, ws: WebSocket) -> None:
        if ws in self.conexiones[canal]:
            self.conexiones[canal].discard(ws)
            log.info("WebSocket %s desconectado (%d clientes)", canal, len(self.conexiones[canal]))

    def cantidad(self, canal: str) -> int:
        return len(self.conexiones[canal])

    async def enviar_a_todos(self, canal: str, mensaje: dict[str, Any]) -> None:
        clientes = list(self.conexiones[canal])
        if not clientes:
            return
        texto = json.dumps(mensaje, default=str)

        async def _enviar(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(texto), TIMEOUT_ENVIO_S)
            except Exception:  # noqa: BLE001 - cliente caído: se lo quita
                self.desconectar(canal, ws)

        await asyncio.gather(*(_enviar(ws) for ws in clientes))

    def emitir_desde_hilo(self, canal: str, mensaje: dict[str, Any]) -> bool:
        """Envía desde cualquier hilo sin bloquear. Devuelve False si el servidor no está listo."""
        loop = self.loop
        if loop is None or loop.is_closed() or not self.conexiones[canal]:
            return False
        asyncio.run_coroutine_threadsafe(self.enviar_a_todos(canal, mensaje), loop)
        return True
