"""Orquestador: crea y conecta todos los componentes de HomeGuard AI.

    cámaras (hilos) -> pipeline (hilo) -> motor de reglas -> despachar():
        1. WebSocket al panel y al dashboard   (no bloquea: run_coroutine_threadsafe)
        2. cola de Telegram                    (no bloquea: hilo aparte)
        3. registro en SQLite + foto           (rápido, en el hilo de procesamiento)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from homeguard.captura.camaras import GestorCamaras
from homeguard.config import RUTA_CONFIG, Config, cargar_config, cargar_secretos, ruta_abs
from homeguard.db import modelos as m
from homeguard.db.sesion import BaseDatos
from homeguard.detectores.base import Zona
from homeguard.detectores.modelos import Modelos
from homeguard.pipeline import Pipeline
from homeguard.reglas.motor import Disparo, MotorReglas
from homeguard.salidas.registro import Registro, codificar_jpeg
from homeguard.salidas.telegram import EnviadorTelegram, TareaTelegram
from homeguard.salidas.websocket import GestorWebSocket

log = logging.getLogger(__name__)

ETIQUETAS = {
    "intrusion": "INTRUSIÓN - rostro desconocido",
    "piscina": "PISCINA - riesgo en el agua",
    "fuego": "FUEGO / HUMO",
    "caida": "CAÍDA de una persona",
    "puerta": "PUERTA abierta fuera de horario",
}


class Sistema:
    def __init__(self, demo: bool = False, sin_telegram: bool = False, ruta_config: Path = RUTA_CONFIG,
                 ruta_bd: str | Path | None = None, modelos: Modelos | None = None) -> None:
        self.demo = demo
        self.ruta_config = Path(ruta_config)
        base = cargar_config(self.ruta_config, demo=demo)
        self.bd = BaseDatos(ruta_bd or ruta_abs(base.general.base_datos))
        self.config: Config = self._config_con_overrides()
        self.secretos = cargar_secretos()
        cfg = self.config

        self.registro = Registro(self.bd, ruta_abs(cfg.general.carpeta_eventos))
        self.ws = GestorWebSocket()
        self.motor = MotorReglas(cfg.alarmas, cfg.motor)
        self.telegram = EnviadorTelegram(self.secretos.telegram_token, self.secretos.telegram_chat_id,
                                         cfg.telegram, al_terminar=self._telegram_terminado,
                                         habilitado=not sin_telegram)
        self.camaras = GestorCamaras(cfg.captura)
        self.modelos = modelos or Modelos(cfg.procesamiento.hilos_torch)
        self.pipeline = Pipeline(self)

        self.ultimo_evento: dict[str, Any] | None = None
        self._zonas_cache: dict[str, list[Zona]] = {}
        self._lock_acks = threading.Lock()
        self._acks_anticipados: dict[str, float] = {}  # ack que llegó antes de guardar el evento
        self._eventos_guardados: set[str] = set()

        self._sincronizar_camaras_bd()
        if demo:
            self._sembrar_zonas_demo()

    # -- configuración ------------------------------------------------------------

    def leer_overrides(self) -> dict[str, Any]:
        with self.bd.sesion() as s:
            return {o.clave: o.valor for o in s.scalars(select(m.ConfigOverride))}

    def _config_con_overrides(self) -> Config:
        overrides = self.leer_overrides()
        try:
            return cargar_config(self.ruta_config, overrides, demo=self.demo)
        except Exception as e:  # noqa: BLE001 - overrides inválidos: se ignoran, config.yaml manda
            log.error("Los cambios guardados desde el dashboard son inválidos (%s); se usa config.yaml", e)
            return cargar_config(self.ruta_config, demo=self.demo)

    def actualizar_overrides(self, cambios: dict[str, Any]) -> Config:
        """Valida y guarda cambios del dashboard. Lanza ValueError si la config resultante es inválida."""
        nuevos = {**self.leer_overrides(), **cambios}
        try:
            cfg = cargar_config(self.ruta_config, nuevos, demo=self.demo)
        except Exception as e:
            raise ValueError(str(e)) from e
        with self.bd.sesion() as s:
            for clave, valor in cambios.items():
                s.merge(m.ConfigOverride(clave=clave, valor=valor))
        self._aplicar_config(cfg)
        return cfg

    def restaurar_config(self) -> Config:
        with self.bd.sesion() as s:
            s.execute(delete(m.ConfigOverride))
        cfg = cargar_config(self.ruta_config, demo=self.demo)
        self._aplicar_config(cfg)
        return cfg

    def _aplicar_config(self, cfg: Config) -> None:
        self.config = cfg
        self.motor.actualizar_config(cfg.alarmas, cfg.motor)
        self.telegram.cfg = cfg.telegram
        self.camaras.cfg_captura = cfg.captura
        self._sincronizar_camaras_bd()
        self.camaras.sincronizar(cfg.camaras)
        log.info("Configuración actualizada")

    # -- cámaras y zonas -----------------------------------------------------------

    def _sincronizar_camaras_bd(self) -> None:
        with self.bd.sesion() as s:
            for cid, cam in self.config.camaras.items():
                s.merge(m.Camara(id=cid, nombre=cam.nombre, fuente=str(cam.fuente)))

    def _sembrar_zonas_demo(self) -> None:
        with self.bd.sesion() as s:
            con_zonas = {z.camara_id for z in s.scalars(select(m.Zona))}
            for z in self.config.demo.zonas:
                if z.camara not in con_zonas:
                    s.add(m.Zona(camara_id=z.camara, nombre=z.nombre, tipo=z.tipo, puntos=z.puntos))

    def zonas(self, camara_id: str) -> list[Zona]:
        if camara_id not in self._zonas_cache:
            with self.bd.sesion() as s:
                filas = s.scalars(select(m.Zona).where(m.Zona.camara_id == camara_id).order_by(m.Zona.id))
                self._zonas_cache[camara_id] = [
                    Zona(id=z.id, camara_id=z.camara_id, nombre=z.nombre, tipo=z.tipo, puntos=z.puntos,
                         referencia=z.referencia) for z in filas]
        return self._zonas_cache[camara_id]

    def invalidar_zonas(self, camara_id: str | None = None) -> None:
        if camara_id is None:
            self._zonas_cache.clear()
        else:
            self._zonas_cache.pop(camara_id, None)

    # -- ciclo de vida -----------------------------------------------------------

    def iniciar(self) -> None:
        self.telegram.iniciar()
        if self.telegram.habilitado:
            pendientes = self.registro.pendientes_telegram(self.config.telegram.descartar_tras_min)
            for ev in pendientes:
                foto = self.registro.ruta_foto(ev.foto)
                self.telegram.encolar(TareaTelegram(
                    ev.id, self._texto_telegram(ev.tipo, ev.camara_id, ev.zona, ev.confianza,
                                                datetime.fromtimestamp(ev.t_deteccion)) + "\n(envío diferido)",
                    foto.read_bytes() if foto and foto.exists() else None, ev.t_deteccion))
            if pendientes:
                log.info("Telegram: %d eventos pendientes re-encolados", len(pendientes))
        self.camaras.sincronizar(self.config.camaras)
        self.pipeline.iniciar()

    def detener(self) -> None:
        self.pipeline.detener()
        self.camaras.detener_todas()
        self.telegram.detener()
        self.bd.cerrar()

    # -- alarmas --------------------------------------------------------------------

    def _texto_telegram(self, tipo: str, camara_id: str, zona: str, confianza: float, hora: datetime) -> str:
        cam = self.config.camaras.get(camara_id)
        return (f"🚨 {ETIQUETAS.get(tipo, tipo)}\n"
                f"Cámara: {cam.nombre if cam else camara_id}\n"
                f"Zona: {zona}\n"
                f"Hora: {hora:%d/%m/%Y %H:%M:%S}\n"
                f"Confianza: {confianza:.0%}")

    def despachar(self, d: Disparo, frame_anotado) -> dict[str, Any]:
        """Ejecuta las tres salidas de una alarma confirmada. Nunca bloquea por red."""
        t_det = time.time()
        cfg = self.config
        evento_id = uuid.uuid4().hex
        jpeg = codificar_jpeg(frame_anotado, cfg.telegram.ancho_foto, cfg.telegram.calidad_jpeg)
        detalle = {**d.detalle, "votos": d.votos,
                   "ms_frame_a_deteccion": round((t_det - d.t) * 1000, 1)}
        hora = datetime.fromtimestamp(t_det)
        evento = {
            "id": evento_id, "tipo": d.tipo, "etiqueta": ETIQUETAS.get(d.tipo, d.tipo), "camara_id": d.camara_id,
            "camara": cfg.camaras[d.camara_id].nombre if d.camara_id in cfg.camaras else d.camara_id,
            "zona": d.zona, "confianza": round(d.confianza, 3), "foto": f"/fotos/{evento_id}.jpg",
            "t_deteccion": t_det, "hora": hora.strftime("%H:%M:%S"), "creado_en": hora.isoformat(timespec="seconds"),
            "detalle": detalle,
        }
        # 1) foto en disco (la necesita el panel para mostrarla) y WebSocket
        nombre_foto = self.registro.guardar_foto(evento_id, jpeg)
        self.ultimo_evento = evento
        mensaje = {"tipo": "alerta", "estado": d.estado, "evento": evento}
        self.ws.emitir_desde_hilo("alarma", mensaje)
        self.ws.emitir_desde_hilo("estado", mensaje)
        # 2) Telegram (cola)
        self.telegram.encolar(TareaTelegram(evento_id, self._texto_telegram(d.tipo, d.camara_id, d.zona,
                                                                           d.confianza, hora), jpeg, t_det))
        # 3) base de datos
        self.registro.guardar_evento(evento_id=evento_id, tipo=d.tipo, camara_id=d.camara_id, zona=d.zona,
                                     confianza=d.confianza, detalle=detalle, foto=nombre_foto, t_deteccion=t_det,
                                     telegram_estado="pendiente" if self.telegram.habilitado else "desactivado")
        self._marcar_guardado(evento_id)
        log.warning("ALARMA %s en %s / %s (confianza %.2f, %d votos)", d.tipo.upper(), d.camara_id, d.zona,
                    d.confianza, d.votos)
        return evento

    def _marcar_guardado(self, evento_id: str) -> None:
        with self._lock_acks:
            self._eventos_guardados.add(evento_id)
            t_ack = self._acks_anticipados.pop(evento_id, None)
        if t_ack is not None:
            self._guardar_ack(evento_id, t_ack)

    def recibir_ack(self, evento_id: str, t_ack: float | None = None) -> None:
        """El panel confirmó que recibió la alerta: se registra la latencia detección -> panel."""
        t_ack = time.time() if t_ack is None else t_ack
        with self._lock_acks:
            if evento_id not in self._eventos_guardados:
                self._acks_anticipados.setdefault(evento_id, t_ack)
                return
        self._guardar_ack(evento_id, t_ack)

    def _guardar_ack(self, evento_id: str, t_ack: float) -> None:
        ms = self.registro.registrar_latencia_panel(evento_id, t_ack)
        if ms is not None:
            objetivo = self.config.panel.latencia_objetivo_ms
            nivel = logging.INFO if ms <= objetivo else logging.WARNING
            log.log(nivel, "Panel recibió el evento %s en %.0f ms (objetivo < %.0f ms)", evento_id, ms, objetivo)
            if self.ultimo_evento and self.ultimo_evento["id"] == evento_id:
                self.ultimo_evento["latencia_panel_ms"] = round(ms, 1)

    def _telegram_terminado(self, evento_id: str, latencia_ms: float | None, estado: str) -> None:
        self.registro.registrar_telegram(evento_id, latencia_ms, estado)
        if self.ultimo_evento and self.ultimo_evento["id"] == evento_id and latencia_ms is not None:
            self.ultimo_evento["latencia_telegram_ms"] = round(latencia_ms, 1)

    def silenciar(self) -> int:
        estado = self.motor.silenciar()
        self.registro.marcar_silenciados()
        log.info("Alarma silenciada")
        self.ws.emitir_desde_hilo("alarma", {"tipo": "estado", "estado": estado, "silenciada": True})
        self.ws.emitir_desde_hilo("estado", {"tipo": "estado", "estado": estado, "silenciada": True})
        return estado

    def estado_actual(self) -> dict[str, Any]:
        return {"tipo": "estado", "estado": self.motor.estado, "activos": self.motor.activos,
                "ultimo_evento": self.ultimo_evento, "demo": self.demo}
