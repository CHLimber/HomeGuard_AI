"""API JSON del dashboard."""
from __future__ import annotations

import csv
import io
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from homeguard.config import RUTA_CONFIG, TIPOS_ZONA, aplanar, leer_comentarios, ruta_abs
from homeguard import pruebas
from homeguard.db import modelos as m
from homeguard.reglas.estado import BIT_POR_TIPO
from homeguard.reglas.motor import probabilidad_falsa_alarma

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


class Armado(BaseModel):
    armado: bool


@router.get("/armado")
def obtener_armado(request: Request) -> dict:
    return {"armado": _sis(request).motor.armado}


@router.post("/armado")
def fijar_armado(datos: Armado, request: Request) -> dict:
    """Arma o desarma el sistema. Desarmado: se sigue analizando (video y calibración) pero no suena nada."""
    return {"armado": _sis(request).fijar_armado(datos.armado)}


@router.get("/falsa-alarma")
def falsa_alarma(request: Request, p: float = 0.05) -> dict:
    """P(falsa alarma) de la votación N de M de cada anomalía, si un frame da falso positivo con probabilidad p."""
    if not 0.0 <= p <= 1.0:
        raise HTTPException(400, "p tiene que estar entre 0 y 1")
    alarmas = _sis(request).config.alarmas
    anomalias = {}
    for tipo in BIT_POR_TIPO:
        regla = getattr(alarmas, tipo)
        anomalias[tipo] = {"n": regla.votos_n, "m": regla.votos_m,
                           "probabilidad": probabilidad_falsa_alarma(p, regla.votos_n, regla.votos_m)}
    return {"p": p, "anomalias": anomalias}


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
        for cid, c in sis.config.camaras.items() if not cid.startswith(pruebas.PREFIJO_PRUEBA)]}


@router.post("/camaras/{camara_id}")
def editar_camara(camara_id: str, datos: dict[str, Any], request: Request) -> dict:
    """Cambia la fuente (índice/URL/archivo) y/o si está activa. Se guarda como override y la cámara se reinicia."""
    sis = _sis(request)
    if camara_id.startswith(pruebas.PREFIJO_PRUEBA):
        raise HTTPException(400, "las cámaras de prueba se manejan desde «Prueba con video»")
    if camara_id not in sis.config.camaras:
        raise HTTPException(404, "cámara desconocida")
    cambios: dict[str, Any] = {}
    prefijo = f"{'demo.camaras' if sis.demo else 'camaras'}.{camara_id}"  # en demo las cámaras salen de demo.camaras
    if "fuente" in datos:
        fuente = str(datos["fuente"]).strip()
        if not fuente:
            raise HTTPException(400, "la fuente no puede estar vacía")
        cambios[f"{prefijo}.fuente"] = int(fuente) if fuente.isdigit() else fuente
    if "activa" in datos:
        cambios[f"{prefijo}.activa"] = bool(datos["activa"])
    try:
        sis.actualizar_overrides(cambios)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


# -- prueba con video (modo exposición) ---------------------------------------------------

@router.get("/pruebas")
def listar_pruebas(request: Request) -> dict:
    sis = _sis(request)
    medios = pruebas.listar_medios(sis.bd)
    for medio in medios:
        medio["activa"] = medio["camara_id"] == sis.prueba_activa
    return {"medios": medios, "activa": sis.prueba_activa, "armado": sis.motor.armado,
            "residentes": getattr(sis.pipeline.analizador.detectores.get("rostros"), "cantidad_residentes", 0),
            "max_mb": sis.config.general.max_mb_prueba}


@router.post("/pruebas")
async def crear_prueba(request: Request, nombre: str = Form(...), detectores: list[str] = Form([]),
                       segundos_por_imagen: float = Form(3.0), zonas_completas: bool = Form(True),
                       reproducir: bool = Form(True), archivos: list[UploadFile] = File(...)) -> dict:
    """Sube un video o imágenes; quedan como una cámara más que se puede reproducir en la exposición."""
    from starlette.concurrency import run_in_threadpool

    sis = _sis(request)
    contenidos = [(f.filename or "archivo", f.file) for f in archivos]
    try:
        medio = await run_in_threadpool(pruebas.crear_medio, sis.bd, sis.config, nombre, contenidos, detectores,
                                        segundos_por_imagen, zonas_completas)
    except pruebas.ErrorPrueba as e:
        raise HTTPException(400, str(e)) from e
    await run_in_threadpool(sis.reproducir_prueba, medio["camara_id"] if reproducir else sis.prueba_activa)
    return medio


@router.post("/pruebas/{medio_id}/reproducir")
def reproducir_prueba(medio_id: str, request: Request) -> dict:
    """Reproduce el medio desde el principio, con votos y cooldown de esa cámara en cero."""
    sis = _sis(request)
    camara_id = pruebas.PREFIJO_PRUEBA + medio_id
    if camara_id not in sis.config.camaras:
        raise HTTPException(404, "prueba inexistente")
    sis.reproducir_prueba(camara_id)
    return {"activa": camara_id}


@router.post("/pruebas/detener")
def detener_prueba(request: Request) -> dict:
    _sis(request).reproducir_prueba(None)
    return {"activa": None}


@router.delete("/pruebas/{medio_id}")
def borrar_prueba(medio_id: str, request: Request) -> dict:
    sis = _sis(request)
    camara_id = pruebas.PREFIJO_PRUEBA + medio_id
    if sis.prueba_activa == camara_id:
        sis.reproducir_prueba(None)
    if not pruebas.borrar_medio(sis.bd, sis.config, medio_id):
        raise HTTPException(404, "prueba inexistente")
    sis.invalidar_zonas(camara_id)
    sis.refrescar_camaras()  # quita la cámara borrada de la config
    return {"ok": True}


# -- configuración ---------------------------------------------------------------------

# secciones de config.yaml que se pueden editar desde el dashboard
SECCIONES_EDITABLES = ("alarmas", "motor", "detectores", "yolo_general", "preproceso", "procesamiento", "captura",
                       "telegram", "panel")


@router.get("/config")
def obtener_config(request: Request) -> dict:
    sis = _sis(request)
    datos = sis.config.model_dump()
    valores = aplanar({seccion: datos[seccion] for seccion in SECCIONES_EDITABLES})
    descripciones = {**leer_comentarios(RUTA_CONFIG), **leer_comentarios(sis.ruta_config)}
    return {"valores": valores, "overrides": sis.leer_overrides(), "descripciones": descripciones,
            "secciones": list(SECCIONES_EDITABLES)}


class CambiosConfig(BaseModel):
    cambios: dict[str, Any]


@router.post("/config")
def guardar_config(datos: CambiosConfig, request: Request) -> dict:
    sis = _sis(request)
    for clave in datos.cambios:
        if clave.split(".")[0] not in SECCIONES_EDITABLES:
            raise HTTPException(400, f"'{clave}' no se puede editar desde el dashboard")
    try:
        sis.actualizar_overrides(datos.cambios)
    except ValueError as e:
        raise HTTPException(400, f"Valor inválido: {e}") from e
    return {"ok": True, "overrides": sis.leer_overrides()}


@router.post("/config/restaurar")
def restaurar_config(request: Request) -> dict:
    _sis(request).restaurar_config()
    return {"ok": True}


@router.post("/telegram/probar")
def probar_telegram(request: Request) -> dict:
    ok, mensaje = _sis(request).telegram.probar()
    return {"ok": ok, "mensaje": mensaje}


# -- zonas -----------------------------------------------------------------------------

class NuevaZona(BaseModel):
    camara_id: str
    nombre: str
    tipo: str
    puntos: list[list[float]]


def _zona_dict(z: m.Zona) -> dict:
    return {"id": z.id, "camara_id": z.camara_id, "nombre": z.nombre, "tipo": z.tipo, "puntos": z.puntos,
            "referencia": f"/api/zonas/{z.id}/referencia.jpg" if z.referencia else None}


@router.get("/zonas")
def listar_zonas(request: Request, camara: str | None = None) -> dict:
    q = select(m.Zona).order_by(m.Zona.id)
    if camara:
        q = q.where(m.Zona.camara_id == camara)
    with _sis(request).bd.sesion() as s:
        return {"zonas": [_zona_dict(z) for z in s.scalars(q)], "tipos": list(TIPOS_ZONA)}


@router.post("/zonas")
def crear_zona(zona: NuevaZona, request: Request) -> dict:
    sis = _sis(request)
    if zona.camara_id not in sis.config.camaras:
        raise HTTPException(400, "cámara desconocida")
    if zona.tipo not in TIPOS_ZONA:
        raise HTTPException(400, f"tipo de zona inválido (usar: {', '.join(TIPOS_ZONA)})")
    if len(zona.puntos) < 3 or any(len(p) != 2 or not (0 <= p[0] <= 1 and 0 <= p[1] <= 1) for p in zona.puntos):
        raise HTTPException(400, "el polígono necesita al menos 3 puntos con coordenadas normalizadas entre 0 y 1")
    nombre = zona.nombre.strip() or zona.tipo
    with sis.bd.sesion() as s:
        nueva = m.Zona(camara_id=zona.camara_id, nombre=nombre, tipo=zona.tipo,
                       puntos=[[round(x, 4), round(y, 4)] for x, y in zona.puntos])
        s.add(nueva)
        s.flush()
        resultado = _zona_dict(nueva)
    sis.invalidar_zonas(zona.camara_id)
    return resultado


@router.delete("/zonas/{zona_id}")
def borrar_zona(zona_id: int, request: Request) -> dict:
    sis = _sis(request)
    with sis.bd.sesion() as s:
        z = s.get(m.Zona, zona_id)
        if z is None:
            raise HTTPException(404, "zona inexistente")
        camara = z.camara_id
        s.delete(z)
    sis.invalidar_zonas(camara)
    return {"ok": True}


@router.post("/zonas/{zona_id}/referencia")
def capturar_referencia(zona_id: int, request: Request) -> dict:
    """Guarda el frame actual (en gris, al ancho de proceso) como referencia de la puerta cerrada."""
    from homeguard.analizador import redimensionar

    sis = _sis(request)
    with sis.bd.sesion() as s:
        z = s.get(m.Zona, zona_id)
        if z is None or z.tipo != "puerta":
            raise HTTPException(400, "la referencia solo se captura en zonas de tipo puerta")
        cam = sis.camaras.obtener(z.camara_id)
        capturado = cam.leer() if cam else None
        if capturado is None:
            raise HTTPException(409, "la cámara no está entregando imágenes")
        gris = cv2.cvtColor(redimensionar(capturado.imagen, sis.config.procesamiento.ancho_proceso),
                            cv2.COLOR_BGR2GRAY)
        carpeta = ruta_abs(sis.config.general.carpeta_referencias)
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"{z.camara_id}_zona{z.id}.png"
        cv2.imwrite(str(ruta), gris)
        z.referencia = str(ruta)
    sis.invalidar_zonas()
    return {"ok": True, "referencia": f"/api/zonas/{zona_id}/referencia.jpg"}


@router.get("/zonas/{zona_id}/referencia.jpg")
def ver_referencia(zona_id: int, request: Request) -> Response:
    with _sis(request).bd.sesion() as s:
        z = s.get(m.Zona, zona_id)
        ruta = ruta_abs(z.referencia) if z and z.referencia else None
    if ruta is None or not ruta.exists():
        raise HTTPException(404, "sin referencia")
    img = cv2.imread(str(ruta))
    return Response(cv2.imencode(".jpg", img)[1].tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


# -- residentes --------------------------------------------------------------------------

_lock_registro = threading.Lock()  # YuNet/SFace no son thread-safe: una sola instancia para el registro
ANCHO_MAX_FOTO = 1280


@router.get("/residentes")
def listar_residentes(request: Request) -> dict:
    with _sis(request).bd.sesion() as s:
        filas = s.scalars(select(m.Residente).order_by(m.Residente.nombre)).all()
        return {"residentes": [{"id": r.id, "nombre": r.nombre, "vectores": len(r.embeddings),
                                "creado_en": r.creado_en.isoformat(timespec="minutes")} for r in filas]}


def _embeddings_de_fotos(sis: Sistema, contenidos: list[tuple[str, bytes]]) -> tuple[list[np.ndarray], list[dict]]:
    from homeguard.detectores.rostros import extraer_rostros

    vectores, rechazadas = [], []
    cfg = sis.config.detectores.rostros
    with _lock_registro:
        for archivo, datos in contenidos:
            img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                rechazadas.append({"archivo": archivo, "motivo": "no es una imagen válida"})
                continue
            if img.shape[1] > ANCHO_MAX_FOTO:
                img = cv2.resize(img, (ANCHO_MAX_FOTO, round(img.shape[0] * ANCHO_MAX_FOTO / img.shape[1])))
            rostros = extraer_rostros(img, sis.modelos, cfg, instancia="registro")
            if not rostros:
                rechazadas.append({"archivo": archivo, "motivo": "no se encontró un rostro"})
                continue
            mayor = max(rostros, key=lambda r: r.caja[2] * r.caja[3])  # el rostro más grande de la foto
            vectores.append(mayor.embedding)
    return vectores, rechazadas


@router.post("/residentes")
async def crear_residente(request: Request, nombre: str = Form(...),
                          fotos: list[UploadFile] = File(...)) -> dict:
    """Alta de residente: detecta el rostro más grande de cada foto y guarda SOLO su embedding (no la foto)."""
    from starlette.concurrency import run_in_threadpool

    sis = _sis(request)
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(400, "falta el nombre")
    if not 1 <= len(fotos) <= 10:
        raise HTTPException(400, "subí entre 1 y 10 fotos (se recomiendan 3 a 5)")
    contenidos = [(f.filename or "foto", await f.read()) for f in fotos]
    vectores, rechazadas = await run_in_threadpool(_embeddings_de_fotos, sis, contenidos)
    if not vectores:
        raise HTTPException(400, {"mensaje": "ninguna foto tenía un rostro detectable", "rechazadas": rechazadas})
    with sis.bd.sesion() as s:
        r = m.Residente(nombre=nombre)
        r.embeddings = [m.EmbeddingRostro(vector=m.EmbeddingRostro.a_bytes(v)) for v in vectores]
        s.add(r)
        s.flush()
        rid = r.id
    sis.recargar_residentes()
    return {"id": rid, "nombre": nombre, "aceptadas": len(vectores), "rechazadas": rechazadas}


@router.delete("/residentes/{residente_id}")
def borrar_residente(residente_id: int, request: Request) -> dict:
    sis = _sis(request)
    with sis.bd.sesion() as s:
        r = s.get(m.Residente, residente_id)
        if r is None:
            raise HTTPException(404, "residente inexistente")
        s.delete(r)
    sis.recargar_residentes()
    return {"ok": True}
