"""Medios de "Prueba con video" (modo exposición).

En la feria no se puede provocar un incendio ni una caída real. Desde el dashboard
se sube un video o una serie de imágenes, y el sistema los analiza como una
cámara más: mismos detectores, mismo motor de reglas, mismo panel, Telegram e
historial. Cada medio se guarda en `general.carpeta_pruebas/<id>/` y se registra
en la tabla `medio_prueba`; el Sistema lo agrega a la config como la cámara
`prueba_<id>`.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

import cv2
from sqlalchemy import delete, select

from homeguard.captura.camaras import EXTENSIONES_IMAGEN, listar_imagenes
from homeguard.config import Config, ruta_abs
from homeguard.db import modelos as m
from homeguard.db.sesion import BaseDatos

log = logging.getLogger(__name__)

PREFIJO_PRUEBA = "prueba_"  # id de cámara de cada medio: prueba_<id>
EXTENSIONES_VIDEO = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v")
DETECTORES = ("rostros", "piscina", "fuego", "caidas", "puerta")
# zona de cuadro completo que necesita cada detector (caídas analiza todo el frame sin zona)
ZONA_POR_DETECTOR = {"rostros": "acceso", "piscina": "piscina", "fuego": "fuego", "puerta": "puerta"}
CUADRO_COMPLETO = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
TAMANO_BLOQUE = 1024 * 1024


class ErrorPrueba(ValueError):
    """Archivo subido inválido (se muestra tal cual en el dashboard)."""


def _copiar_limitado(origen: BinaryIO, destino: Path, restante: int) -> int:
    """Copia por bloques sin cargar todo en memoria. Devuelve los bytes escritos o lanza si se pasa del límite."""
    escritos = 0
    with destino.open("wb") as f:
        while bloque := origen.read(TAMANO_BLOQUE):
            escritos += len(bloque)
            if escritos > restante:
                raise ErrorPrueba("el archivo supera el tamaño máximo (general.max_mb_prueba)")
            f.write(bloque)
    return escritos


def info_video(ruta: Path) -> dict[str, Any]:
    """Abre el video y lee el primer frame: si OpenCV no lo puede decodificar, no sirve como cámara."""
    cap = cv2.VideoCapture(str(ruta))
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ErrorPrueba("OpenCV no puede leer el video (probá exportarlo como MP4 H.264)")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return {"resolucion": f"{frame.shape[1]}x{frame.shape[0]}", "fps": round(fps, 1),
                "duracion_s": round(frames / fps, 1) if fps else None}
    finally:
        cap.release()


def crear_medio(bd: BaseDatos, cfg: Config, nombre: str, archivos: list[tuple[str, BinaryIO]],
                detectores: list[str], segundos_por_imagen: float = 3.0,
                zonas_completas: bool = True) -> dict[str, Any]:
    """Guarda un video (1 archivo) o una serie de imágenes (1 o más) y lo registra como medio de prueba."""
    nombre = nombre.strip()
    if not nombre:
        raise ErrorPrueba("falta el nombre")
    detectores = [d for d in DETECTORES if d in detectores]  # orden fijo y sin repetidos
    if not detectores:
        raise ErrorPrueba("elegí al menos una anomalía para analizar")
    if not archivos:
        raise ErrorPrueba("no se subió ningún archivo")
    if segundos_por_imagen <= 0:
        raise ErrorPrueba("los segundos por imagen tienen que ser mayores que 0")
    extensiones = [Path(n).suffix.lower() for n, _ in archivos]
    if all(e in EXTENSIONES_VIDEO for e in extensiones):
        if len(archivos) != 1:
            raise ErrorPrueba("subí un solo video por prueba")
        tipo = "video"
    elif all(e in EXTENSIONES_IMAGEN for e in extensiones):
        tipo = "imagenes"
    else:
        raise ErrorPrueba("subí un video (" + ", ".join(EXTENSIONES_VIDEO) + ") o imágenes ("
                          + ", ".join(EXTENSIONES_IMAGEN) + "), sin mezclar")

    medio_id, carpeta = _nueva_carpeta(cfg)
    restante = int(cfg.general.max_mb_prueba * 1024 * 1024)
    try:
        if tipo == "video":
            ruta = carpeta / f"video{extensiones[0]}"
            _copiar_limitado(archivos[0][1], ruta, restante)
            info = info_video(ruta)
        else:
            ruta = carpeta
            # la presentación sigue el orden alfabético de los nombres originales (1.jpg, 2.jpg, ...)
            ordenados = sorted(zip(archivos, extensiones), key=lambda a: a[0][0].lower())
            for i, ((_, contenido), ext) in enumerate(ordenados, start=1):
                restante -= _copiar_limitado(contenido, carpeta / f"{i:03d}{ext}", restante)
            legibles = [p for p in listar_imagenes(carpeta) if cv2.imread(str(p)) is not None]
            if len(legibles) != len(archivos):
                raise ErrorPrueba(f"{len(archivos) - len(legibles)} imagen(es) no se pudieron leer")
            primera = cv2.imread(str(legibles[0]))
            info = {"resolucion": f"{primera.shape[1]}x{primera.shape[0]}", "imagenes": len(legibles),
                    "duracion_s": round(len(legibles) * segundos_por_imagen, 1)}
    except Exception:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise
    return _registrar_medio(bd, medio_id, nombre, tipo, ruta, detectores, segundos_por_imagen, zonas_completas, info)


def _nueva_carpeta(cfg: Config) -> tuple[str, Path]:
    medio_id = uuid.uuid4().hex[:10]
    carpeta = ruta_abs(cfg.general.carpeta_pruebas) / medio_id
    carpeta.mkdir(parents=True, exist_ok=True)
    return medio_id, carpeta


def _registrar_medio(bd: BaseDatos, medio_id: str, nombre: str, tipo: str, ruta: Path, detectores: list[str],
                     segundos_por_imagen: float, zonas_completas: bool, info: dict[str, Any]) -> dict[str, Any]:
    camara_id = PREFIJO_PRUEBA + medio_id
    with bd.sesion() as s:
        s.add(m.MedioPrueba(id=medio_id, nombre=nombre, tipo=tipo, ruta=str(ruta), detectores=detectores,
                            segundos_por_imagen=segundos_por_imagen))
        s.merge(m.Camara(id=camara_id, nombre=f"Prueba: {nombre}", fuente=str(ruta)))
        if zonas_completas:
            for d in detectores:
                if d in ZONA_POR_DETECTOR:
                    tipo_zona = ZONA_POR_DETECTOR[d]
                    s.add(m.Zona(camara_id=camara_id, nombre=f"{tipo_zona} (cuadro completo)", tipo=tipo_zona,
                                 puntos=CUADRO_COMPLETO))
    log.info("Prueba con video: nuevo medio %s (%s, %s)", camara_id, tipo, ", ".join(detectores))
    return {"id": medio_id, "camara_id": camara_id, "nombre": nombre, "tipo": tipo, "detectores": detectores,
            **info}


# -- video desde un enlace ---------------------------------------------------------------

HOSTS_YOUTUBE = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")
TIMEOUT_ENLACE_S = 15
TIPOS_MIME_VIDEO = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
                    "video/x-matroska": ".mkv", "video/x-msvideo": ".avi"}


def _descargar_directo(url: str, carpeta: Path, restante: int) -> Path:
    """Descarga un archivo de video por HTTP(S), por bloques y con el mismo límite de tamaño que la subida."""
    import requests

    try:
        with requests.get(url, stream=True, timeout=TIMEOUT_ENLACE_S, headers={"User-Agent": "HomeGuardAI"}) as r:
            r.raise_for_status()
            mime = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if mime.startswith("text/"):
                raise ErrorPrueba("el enlace es una página web, no un video (si es de YouTube pegá el link del video)")
            ext = Path(url.split("?", 1)[0]).suffix.lower()
            if ext not in EXTENSIONES_VIDEO:
                ext = TIPOS_MIME_VIDEO.get(mime, ".mp4")
            ruta = carpeta / f"video{ext}"
            escritos = 0
            with ruta.open("wb") as f:
                for bloque in r.iter_content(TAMANO_BLOQUE):
                    escritos += len(bloque)
                    if escritos > restante:
                        raise ErrorPrueba("el video supera el tamaño máximo (general.max_mb_prueba)")
                    f.write(bloque)
            return ruta
    except requests.RequestException as e:
        raise ErrorPrueba(f"no se pudo descargar el enlace: {e}") from e


def _descargar_youtube(url: str, carpeta: Path, restante: int) -> Path:
    """Descarga un video de YouTube con yt-dlp (opcional): solo la imagen (sin audio, no hace falta ni ffmpeg), de 720p o menos."""
    try:
        import yt_dlp
    except ImportError as e:
        raise ErrorPrueba("para enlaces de YouTube falta instalar yt-dlp (pip install yt-dlp)") from e
    # YouTube casi nunca ofrece un archivo con imagen y audio juntos: se pide solo el video, de preferencia H.264 (OpenCV
    # lo lee siempre; VP9/AV1 no) y por https directo. Los últimos formatos son el respaldo si no hay H.264.
    opciones = {"format": "bv[height<=720][vcodec^=avc1][protocol^=https]/bv[height<=720][vcodec^=avc1]"
                          "/bv[height<=720][ext=mp4]/b[height<=720]/bv[height<=720]/b",
                "noplaylist": True, "quiet": True, "noprogress": True,
                "no_warnings": True, "outtmpl": str(carpeta / "video.%(ext)s"), "max_filesize": restante,
                "socket_timeout": TIMEOUT_ENLACE_S}
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        raise ErrorPrueba(f"no se pudo descargar el video de YouTube: {str(e).splitlines()[-1]}") from e
    descargados = [p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES_VIDEO]
    if not descargados:
        raise ErrorPrueba("no se descargó ningún video (¿supera general.max_mb_prueba?)")
    return descargados[0]


def crear_medio_enlace(bd: BaseDatos, cfg: Config, nombre: str, enlace: str, detectores: list[str],
                       zonas_completas: bool = True) -> dict[str, Any]:
    """Descarga el video de un enlace (directo o de YouTube) y lo registra como medio de prueba.

    Queda guardado en disco igual que uno subido: después se reproduce sin internet.
    """
    nombre, enlace = nombre.strip(), enlace.strip()
    if not nombre:
        raise ErrorPrueba("falta el nombre")
    detectores = [d for d in DETECTORES if d in detectores]
    if not detectores:
        raise ErrorPrueba("elegí al menos una anomalía para analizar")
    partes = urlsplit(enlace)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ErrorPrueba("el enlace tiene que empezar con http:// o https://")

    medio_id, carpeta = _nueva_carpeta(cfg)
    restante = int(cfg.general.max_mb_prueba * 1024 * 1024)
    try:
        descargar = _descargar_youtube if partes.hostname.lower() in HOSTS_YOUTUBE else _descargar_directo
        ruta = descargar(enlace, carpeta, restante)
        info = info_video(ruta)
    except Exception:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise
    return _registrar_medio(bd, medio_id, nombre, "video", ruta, detectores, 3.0, zonas_completas, info)


def listar_medios(bd: BaseDatos) -> list[dict[str, Any]]:
    with bd.sesion() as s:
        medios = s.scalars(select(m.MedioPrueba).order_by(m.MedioPrueba.creado_en.desc())).all()
        zonas = {}
        for z in s.scalars(select(m.Zona).where(m.Zona.camara_id.startswith(PREFIJO_PRUEBA))):
            zonas.setdefault(z.camara_id, []).append(z.tipo)
    salida = []
    for medio in medios:
        ruta = Path(medio.ruta)
        cid = PREFIJO_PRUEBA + medio.id
        salida.append({
            "id": medio.id, "camara_id": cid, "nombre": medio.nombre, "tipo": medio.tipo,
            "detectores": medio.detectores, "segundos_por_imagen": medio.segundos_por_imagen,
            "imagenes": len(listar_imagenes(ruta)) if medio.tipo == "imagenes" and ruta.is_dir() else None,
            "existe": ruta.exists(), "zonas": sorted(zonas.get(cid, [])),
            "creado_en": medio.creado_en.isoformat(timespec="minutes"),
        })
    return salida


def borrar_medio(bd: BaseDatos, cfg: Config, medio_id: str) -> bool:
    """Borra el medio, su carpeta y sus zonas. Los eventos que generó quedan en el historial."""
    camara_id = PREFIJO_PRUEBA + medio_id
    with bd.sesion() as s:
        medio = s.get(m.MedioPrueba, medio_id)
        if medio is None:
            return False
        s.delete(medio)
        s.execute(delete(m.Zona).where(m.Zona.camara_id == camara_id))
    carpeta = ruta_abs(cfg.general.carpeta_pruebas) / medio_id
    shutil.rmtree(carpeta, ignore_errors=True)
    return True
