"""API JSON del dashboard."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from homeguard.db import modelos as m

if TYPE_CHECKING:
    from homeguard.sistema import Sistema

router = APIRouter(prefix="/api")


def _sis(request: Request) -> Sistema:
    return request.app.state.sistema


# -- estado y alarma ---------------------------------------------------------------

@router.get("/estado")
def estado(request: Request) -> dict:
    return _sis(request).estado_actual()


@router.post("/silenciar")
def silenciar(request: Request) -> dict:
    return {"estado": _sis(request).silenciar()}


@router.get("/telemetria")
def telemetria(request: Request) -> dict:
    return _sis(request).pipeline.telemetria()


# -- historial -----------------------------------------------------------------------

def _consultar_eventos(sis: Sistema, tipo: str | None, camara: str | None, desde: str | None,
                       hasta: str | None, limite: int) -> list[dict]:
    q = select(m.Evento).order_by(m.Evento.creado_en.desc())
    if tipo:
        q = q.where(m.Evento.tipo == tipo)
    if camara:
        q = q.where(m.Evento.camara_id == camara)
    if desde:
        q = q.where(m.Evento.creado_en >= datetime.fromisoformat(desde))
    if hasta:
        q = q.where(m.Evento.creado_en <= datetime.fromisoformat(hasta))
    with sis.bd.sesion() as s:
        return [e.a_dict() for e in s.scalars(q.limit(limite))]


@router.get("/eventos")
def eventos(request: Request, tipo: str | None = None, camara: str | None = None, desde: str | None = None,
            hasta: str | None = None, limite: int = 200) -> dict:
    sis = _sis(request)
    filas = _consultar_eventos(sis, tipo, camara, desde, hasta, min(limite, 5000))
    return {"eventos": filas, "latencia_objetivo_ms": sis.config.panel.latencia_objetivo_ms}


@router.get("/eventos.csv")
def eventos_csv(request: Request, tipo: str | None = None, camara: str | None = None, desde: str | None = None,
                hasta: str | None = None) -> StreamingResponse:
    filas = _consultar_eventos(_sis(request), tipo, camara, desde, hasta, 100000)
    buf = io.StringIO()
    columnas = ["id", "creado_en", "tipo", "camara_id", "zona", "confianza", "latencia_panel_ms",
                "latencia_telegram_ms", "telegram_estado", "silenciado", "foto"]
    w = csv.DictWriter(buf, fieldnames=columnas, extrasaction="ignore")
    w.writeheader()
    w.writerows(filas)
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=eventos_homeguard.csv"})


# -- cámaras --------------------------------------------------------------------------

@router.get("/camaras")
def camaras(request: Request) -> dict:
    sis = _sis(request)
    activas = {c["id"]: c for c in sis.camaras.resumen()}
    return {"camaras": [
        {"id": cid, "nombre": c.nombre, "fuente": str(c.fuente), "activa": c.activa, "detectores": c.detectores,
         **{k: v for k, v in activas.get(cid, {}).items() if k not in ("id", "nombre", "fuente")}}
        for cid, c in sis.config.camaras.items()]}
