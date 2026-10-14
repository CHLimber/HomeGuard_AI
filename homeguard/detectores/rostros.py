"""Anomalía 1: intrusión (rostro desconocido en la zona "acceso").

- Para no gastar CPU, primero se mira si el YOLO general ve una persona dentro
  de la zona "acceso" (exigir_persona_yolo). Solo entonces corre YuNet.
- YuNet (cv2.FaceDetectorYN) encuentra los rostros; SFace (cv2.FaceRecognizerSF)
  alinea cada rostro y calcula un embedding de 128 valores.
- Se compara con los embeddings de los residentes por similitud coseno. Si la
  mejor similitud es < `umbral_similitud` (0,363, valor de referencia de
  OpenCV Zoo), el rostro es desconocido.
- La observación es positiva si hay algún rostro desconocido dentro de la zona.
  El motor exige K frames consecutivos (alarmas.intrusion: votos_n = votos_m = K).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from homeguard.detectores.base import Anotacion, Contexto, Detector, PosibleEvento
from homeguard.detectores.modelos import Modelos
from homeguard.preproceso import bitwise


@dataclass
class Rostro:
    caja: tuple[int, int, int, int]  # x, y, ancho, alto (en la imagen donde se detectó)
    embedding: np.ndarray            # 128 floats, normalizado (norma 1)
    puntaje: float = 1.0


def normalizar(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def comparar(embedding: np.ndarray, residentes: np.ndarray, nombres: list[str]) -> tuple[float, str | None]:
    """Mejor similitud coseno contra los residentes (vectores normalizados: coseno = producto punto)."""
    if residentes.size == 0:
        return -1.0, None
    similitudes = residentes @ normalizar(embedding)
    i = int(np.argmax(similitudes))
    return float(similitudes[i]), nombres[i]


def extraer_rostros(imagen: np.ndarray, modelos: Modelos, cfg_rostros, tamano_min: int = 0,
                    instancia: str | None = None) -> list[Rostro]:
    """Detecta rostros con YuNet y calcula su embedding con SFace."""
    alto, ancho = imagen.shape[:2]
    if alto < 10 or ancho < 10:
        return []
    detector = modelos.yunet(cfg_rostros.modelo_detector, cfg_rostros.confianza_rostro, cfg_rostros.nms, instancia)
    reconocedor = modelos.sface(cfg_rostros.modelo_reconocedor, instancia)
    detector.setInputSize((ancho, alto))
    _, caras = detector.detect(imagen)
    rostros: list[Rostro] = []
    if caras is None:
        return rostros
    for cara in caras:
        x, y, w, h = (int(round(v)) for v in cara[:4])
        if min(w, h) < tamano_min:
            continue
        alineado = reconocedor.alignCrop(imagen, cara)
        emb = normalizar(reconocedor.feature(alineado))
        rostros.append(Rostro((x, y, w, h), emb, float(cara[-1])))
    return rostros


class DetectorRostros(Detector):
    nombre = "rostros"
    tipo = "intrusion"

    def __init__(self, modelos: Modelos,
                 detectar: Callable[[np.ndarray, Any], list[Rostro]] | None = None) -> None:
        self.modelos = modelos
        self.detectar = detectar or self._detectar_real
        self._lock = threading.Lock()
        self._residentes = np.zeros((0, 128), np.float32)
        self._nombres: list[str] = []

    def fijar_residentes(self, embeddings: np.ndarray, nombres: list[str]) -> None:
        """Lista de embeddings de residentes (uno por fila) y el nombre del residente de cada fila."""
        matriz = np.asarray(embeddings, dtype=np.float32).reshape(-1, 128) if len(nombres) else np.zeros((0, 128),
                                                                                                         np.float32)
        if len(matriz):
            matriz = matriz / np.maximum(np.linalg.norm(matriz, axis=1, keepdims=True), 1e-9)
        with self._lock:
            self._residentes, self._nombres = matriz, list(nombres)

    @property
    def cantidad_residentes(self) -> int:
        return len(set(self._nombres))

    def _detectar_real(self, imagen: np.ndarray, cfg_global) -> list[Rostro]:
        cfg = cfg_global.detectores.rostros
        return extraer_rostros(imagen, self.modelos, cfg, cfg.tamano_min_rostro_px)

    def procesar(self, frame: np.ndarray, ctx: Contexto) -> list[PosibleEvento]:
        zonas = ctx.zonas_de_tipo("acceso")
        if not zonas:
            return []
        cfg = ctx.cfg.detectores.rostros
        with self._lock:
            residentes, nombres = self._residentes, self._nombres

        imagen = ctx.frame_original if cfg.usar_resolucion_original else frame
        escala = imagen.shape[1] / ctx.ancho  # px de la imagen de rostros por px del frame de proceso
        eventos: list[PosibleEvento] = []
        for zona in zonas:
            personas = 0
            if cfg.exigir_persona_yolo:
                det = ctx.detecciones_generales()
                if len(det):
                    personas = int(np.sum(ctx.dentro_de_zona(zona, det) & (det.class_id == 0)))
                if personas == 0:
                    ctx.calibracion.setdefault("rostros", {})[zona.nombre] = {
                        "personas_en_zona": 0, "rostros": [], "umbral_similitud": cfg.umbral_similitud}
                    eventos.append(PosibleEvento(self.tipo, ctx.camara_id, zona.nombre, False, ctx.t,
                                                 detalle={"personas": 0}))
                    continue

            pts = zona.puntos_px(ctx.ancho, ctx.alto)
            x0, y0, x1, y1 = bitwise.bbox_poligono(pts, ctx.alto, ctx.ancho)
            X0, Y0, X1, Y1 = (int(round(v * escala)) for v in (x0, y0, x1, y1))
            recorte = imagen[Y0:Y1, X0:X1]
            poligono = (pts * escala).astype(np.float32)

            resultados = []
            for r in self.detectar(recorte, ctx.cfg):
                x, y, w, h = r.caja
                centro = (X0 + x + w / 2, Y0 + y + h / 2)
                if cv2.pointPolygonTest(poligono, centro, False) < 0:
                    continue  # el rostro está en el recorte pero fuera del polígono
                similitud, nombre = comparar(r.embedding, residentes, nombres)
                conocido = similitud >= cfg.umbral_similitud
                resultados.append({"similitud": round(similitud, 3), "residente": nombre if conocido else None,
                                   "conocido": conocido})
                caja_proc = (int((X0 + x) / escala), int((Y0 + y) / escala),
                             int((X0 + x + w) / escala), int((Y0 + y + h) / escala))
                texto = f"{nombre} {similitud:.2f}" if conocido else f"desconocido {similitud:.2f}"
                ctx.anotaciones.append(Anotacion(caja_proc, texto, not conocido))

            desconocidos = [r for r in resultados if not r["conocido"]]
            activo = bool(desconocidos)
            ctx.calibracion.setdefault("rostros", {})[zona.nombre] = {
                "personas_en_zona": personas, "rostros": resultados, "umbral_similitud": cfg.umbral_similitud,
                "residentes_registrados": self.cantidad_residentes,
            }
            eventos.append(PosibleEvento(
                tipo=self.tipo, camara_id=ctx.camara_id, zona=zona.nombre, activo=activo, t=ctx.t,
                # cuanto menor la similitud con cualquier residente, más seguro es que sea un desconocido
                confianza=float(np.clip(1.0 - min(r["similitud"] for r in desconocidos), 0, 1)) if activo else 0.0,
                detalle={"rostros": len(resultados), "desconocidos": len(desconocidos),
                         "mejor_similitud": max((r["similitud"] for r in resultados), default=None)},
            ))
        return eventos
