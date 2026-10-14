"""Envío de fotos de eventos por Telegram, en un hilo aparte con cola.

El hilo de procesamiento solo encola (no bloquea nunca). Si no hay internet,
la tarea se reintenta con espera exponencial hasta `reintento_max_s`, y se
descarta si tiene más de `descartar_tras_min` minutos. Los eventos que
quedaron "pendientes" al cerrar el programa se vuelven a encolar al arrancar.
Sin token configurado, solo se registra en el log.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from homeguard.config import CfgTelegram

log = logging.getLogger(__name__)

URL_API = "https://api.telegram.org/bot{token}/{metodo}"


@dataclass
class TareaTelegram:
    evento_id: str
    texto: str
    foto_jpeg: bytes | None
    t_deteccion: float
    intentos: int = 0


class ErrorPermanente(Exception):
    """Error que no se arregla reintentando (token o chat_id inválidos)."""


# callback(evento_id, latencia_ms | None, estado)
AlTerminar = Callable[[str, float | None, str], None]


class EnviadorTelegram:
    def __init__(self, token: str, chat_id: str, cfg: CfgTelegram, al_terminar: AlTerminar | None = None,
                 habilitado: bool = True) -> None:
        self.token = token
        self.chat_id = chat_id
        self.cfg = cfg
        self.al_terminar = al_terminar
        self.habilitado = habilitado and cfg.activo and bool(token and chat_id)
        self.cola: queue.Queue[TareaTelegram | None] = queue.Queue()
        self._detener = threading.Event()
        self._hilo: threading.Thread | None = None
        self.ultimo_error: str | None = None
        self.sin_conexion = False

    # -- ciclo de vida ----------------------------------------------------------

    def iniciar(self) -> None:
        if self._hilo is None:
            self._hilo = threading.Thread(target=self._bucle, name="telegram", daemon=True)
            self._hilo.start()
            if not self.habilitado:
                log.warning("Telegram desactivado (sin token/chat_id o --sin-telegram): las alertas solo van al log")

    def detener(self) -> None:
        self._detener.set()
        self.cola.put(None)
        if self._hilo:
            self._hilo.join(timeout=3)

    @property
    def pendientes(self) -> int:
        return self.cola.qsize()

    # -- API pública ------------------------------------------------------------

    def encolar(self, tarea: TareaTelegram) -> None:
        if not self.habilitado:
            log.info("[Telegram desactivado] %s", tarea.texto.replace("\n", " | "))
            self._notificar(tarea.evento_id, None, "desactivado")
            return
        self.cola.put(tarea)

    def probar(self) -> tuple[bool, str]:
        """Envía un mensaje de prueba de forma síncrona (botón "probar Telegram")."""
        if not (self.token and self.chat_id):
            return False, "Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en .env"
        try:
            self._llamar("sendMessage", data={"chat_id": self.chat_id,
                                               "text": "✅ HomeGuard AI: prueba de Telegram correcta"})
            return True, "Mensaje de prueba enviado"
        except Exception as e:  # noqa: BLE001
            return False, f"Error: {e}"

    # -- internos ---------------------------------------------------------------

    def _notificar(self, evento_id: str, latencia_ms: float | None, estado: str) -> None:
        if self.al_terminar:
            try:
                self.al_terminar(evento_id, latencia_ms, estado)
            except Exception:  # noqa: BLE001
                log.exception("Error registrando el resultado de Telegram")

    def _llamar(self, metodo: str, data: dict, files: dict | None = None) -> dict:
        r = requests.post(URL_API.format(token=self.token, metodo=metodo), data=data, files=files,
                          timeout=self.cfg.timeout_s)
        if r.status_code in (400, 401, 403, 404):
            raise ErrorPermanente(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code == 429:  # demasiados mensajes: Telegram dice cuánto esperar
            espera = r.json().get("parameters", {}).get("retry_after", 5)
            raise requests.RequestException(f"límite de Telegram, reintentar en {espera}s")
        r.raise_for_status()
        return r.json()

    def enviar_ahora(self, tarea: TareaTelegram) -> None:
        if tarea.foto_jpeg:
            self._llamar("sendPhoto", data={"chat_id": self.chat_id, "caption": tarea.texto[:1024]},
                         files={"photo": ("evento.jpg", tarea.foto_jpeg, "image/jpeg")})
        else:
            self._llamar("sendMessage", data={"chat_id": self.chat_id, "text": tarea.texto})

    def _bucle(self) -> None:
        while not self._detener.is_set():
            tarea = self.cola.get()
            if tarea is None:
                break
            espera = min(1.0, self.cfg.reintento_max_s)
            while not self._detener.is_set():
                edad_min = (time.time() - tarea.t_deteccion) / 60
                if edad_min > self.cfg.descartar_tras_min:
                    log.warning("Telegram: evento %s descartado (%.0f min sin poder enviarse)", tarea.evento_id, edad_min)
                    self._notificar(tarea.evento_id, None, "error")
                    break
                try:
                    tarea.intentos += 1
                    self.enviar_ahora(tarea)
                    latencia = (time.time() - tarea.t_deteccion) * 1000
                    self.sin_conexion = False
                    self.ultimo_error = None
                    log.info("Telegram: evento %s enviado en %.0f ms (intento %d)", tarea.evento_id, latencia, tarea.intentos)
                    self._notificar(tarea.evento_id, latencia, "enviado")
                    break
                except ErrorPermanente as e:
                    self.ultimo_error = str(e)
                    log.error("Telegram: error permanente (revisá token/chat_id): %s", e)
                    self._notificar(tarea.evento_id, None, "error")
                    break
                except Exception as e:  # noqa: BLE001 - sin internet, timeout, etc.
                    self.sin_conexion = True
                    self.ultimo_error = str(e)
                    log.warning("Telegram: fallo al enviar %s (%s). Reintento en %.0f s", tarea.evento_id, e, espera)
                    self._detener.wait(espera)
                    espera = min(espera * 2, self.cfg.reintento_max_s)
