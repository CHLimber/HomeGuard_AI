"""Anomalía 3: fuego / humo, en dos capas.

Capa 1 (barata, bitwise, todos los frames):
    color_fuego AND movimiento (XOR de cuantizados) AND zona
    -> % de píxeles de la zona. Una llama real parpadea; un objeto naranja quieto no.
    color_fuego según `modo_capa1`: "lut332" (índice de 8 bits + cv2.LUT), "lut9" (índice
    de 9 bits del informe + tabla de 512) o "hsv" (cv2.inRange, sin bits, para comparar).
Capa 2 (cara, solo si la capa 1 supera `umbral_capa1_pct`):
    YOLOv8n fire-smoke (rabahdev/fire-smoke-yolov8n, 0=smoke, 1=fire).
La observación es positiva si capa 1 activa Y capa 2 con confianza > `confianza_capa2`.
El motor exige eso en 3 de 5 frames (alarmas.fuego en config.yaml).

Si la cámara no tiene zonas de tipo "fuego", se analiza la imagen completa.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from homeguard.config import ruta_abs
from homeguard.detectores.base import Anotacion, Contexto, Detector, PosibleEvento, zona_global
from homeguard.detectores.modelos import Modelos
from homeguard.preproceso import bitwise

NOMBRES_CAPA2 = {0: "humo", 1: "fuego"}

# detección de la capa 2: (clase, confianza, (x0, y0, x1, y1)) en coordenadas del frame de proceso
Deteccion = tuple[int, float, tuple[int, int, int, int]]


class DetectorFuego(Detector):
    nombre = "fuego"
    tipo = "fuego"

    def __init__(self, modelos: Modelos, inferir_capa2: Callable[[np.ndarray, Any], list[Deteccion]] | None = None):
        self.modelos = modelos
        self.inferir_capa2 = inferir_capa2 or self._yolo_fuego
        self._lut: np.ndarray | None = None
        self._clave_lut: tuple | None = None
        self.llamadas_capa2 = 0  # para el benchmark/tests: cuántas veces corrió el YOLO

    def _tabla(self, cfg) -> np.ndarray | None:
        """Tabla de la capa 1 según `modo_capa1` (None en modo "hsv"); se recalcula solo si cambia la config."""
        if cfg.modo_capa1 == "hsv":
            return None
        rangos = (cfg.hue_min, cfg.hue_max, cfg.sat_min, cfg.val_min)
        clave = (cfg.modo_capa1, cfg.lut_archivo, rangos)
        if clave != self._clave_lut:
            tamano = 512 if cfg.modo_capa1 == "lut9" else 256
            if cfg.lut_archivo:
                lut = np.load(ruta_abs(cfg.lut_archivo)).astype(np.uint8)
                if lut.shape != (tamano,):
                    raise ValueError(f"{cfg.lut_archivo} tiene {lut.size} entradas; modo {cfg.modo_capa1} "
                                     f"necesita {tamano} (regenerala con scripts/generar_lut_fuego.py)")
            elif cfg.modo_capa1 == "lut9":
                lut = bitwise.construir_lut_fuego_9bits(*rangos)
            else:
                lut = bitwise.construir_lut_fuego(*rangos)
            self._lut, self._clave_lut = lut, clave
        return self._lut

    @staticmethod
    def _mascara_color(bgr: np.ndarray, cfg, lut: np.ndarray | None) -> np.ndarray:
        if cfg.modo_capa1 == "lut9":
            return bitwise.mascara_color_lut9(bgr, lut)
        if cfg.modo_capa1 == "hsv":
            return bitwise.mascara_color_hsv(bgr, cfg.hue_min, cfg.hue_max, cfg.sat_min, cfg.val_min)
        return bitwise.mascara_color_lut(bgr, lut)

    def _yolo_fuego(self, frame: np.ndarray, cfg_global) -> list[Deteccion]:
        modelo = self.modelos.yolo(cfg_global.detectores.fuego.modelo)
        r = modelo.predict(frame, imgsz=cfg_global.procesamiento.imgsz_yolo, conf=0.1, verbose=False)[0]
        salida: list[Deteccion] = []
        for caja, clase, conf in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy()):
            salida.append((int(clase), float(conf), tuple(int(v) for v in caja)))
        return salida

    def procesar(self, frame: np.ndarray, ctx: Contexto) -> list[PosibleEvento]:
        cfg = ctx.cfg.detectores.fuego
        lut = self._tabla(cfg)
        zonas = ctx.zonas_de_tipo("fuego") or [zona_global(ctx.camara_id)]
        capa2: list[Deteccion] | None = None  # se calcula a lo sumo una vez por frame
        eventos: list[PosibleEvento] = []

        for zona in zonas:
            x0, y0, x1, y1 = bitwise.bbox_poligono(zona.puntos_px(ctx.ancho, ctx.alto), ctx.alto, ctx.ancho)
            roi = ctx.mascara_zona(zona)[y0:y1, x0:x1]
            color = self._mascara_color(frame[y0:y1, x0:x1], cfg, lut)
            if ctx.fuente_estatica:  # imagen fija: no hay movimiento que exigir, la capa 1 usa solo el color
                pct_color_mov = bitwise.porcentaje_activos(color, roi)
            elif ctx.mascara_movimiento is None:  # primer frame: todavía no hay movimiento
                pct_color_mov = 0.0
            else:
                mov = ctx.mascara_movimiento[y0:y1, x0:x1]
                fuego_y_mov = bitwise.combinar_mascaras(color, mov, roi, modo="and")
                pct_color_mov = bitwise.porcentaje_activos(fuego_y_mov, roi)
            pct_color = bitwise.porcentaje_activos(color, roi)
            # Informe, regla de fuego: (color AND movimiento AND roi) > umbral_capa1 y luego capa 2 YOLO en N de M
            capa1 = pct_color_mov >= cfg.umbral_capa1_pct

            conf2, mejor = 0.0, None
            if capa1:
                if capa2 is None:
                    capa2 = self.inferir_capa2(frame, ctx.cfg)
                    self.llamadas_capa2 += 1
                for clase, conf, caja in capa2:
                    cx, cy = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
                    if clase in cfg.clases_capa2 and x0 <= cx <= x1 and y0 <= cy <= y1 and conf > conf2:
                        conf2, mejor = conf, (clase, conf, caja)
            activo = capa1 and conf2 > cfg.confianza_capa2

            ctx.calibracion.setdefault("fuego", {})[zona.nombre] = {
                "capa1_pct_color": round(pct_color, 2),
                "capa1_pct_color_y_movimiento": round(pct_color_mov, 2),
                "umbral_capa1_pct": cfg.umbral_capa1_pct,
                "imagen_fija": ctx.fuente_estatica,
                "capa2_ejecutada": capa1,
                "capa2_confianza": round(conf2, 2),
                "umbral_capa2": cfg.confianza_capa2,
            }
            if zona.id != -1 or capa1:
                ctx.anotaciones.append(Anotacion((x0, y0, x1, y1),
                                                 f"{zona.nombre} c1 {pct_color_mov:.1f}% c2 {conf2:.2f}", activo))
            if mejor is not None:
                ctx.anotaciones.append(Anotacion(mejor[2], f"{NOMBRES_CAPA2.get(mejor[0], mejor[0])} {mejor[1]:.2f}",
                                                 activo))
            eventos.append(PosibleEvento(
                tipo=self.tipo, camara_id=ctx.camara_id, zona=zona.nombre, activo=activo, t=ctx.t,
                confianza=conf2,
                detalle={"capa1_pct": round(pct_color_mov, 2), "capa2_conf": round(conf2, 3),
                         "clase": NOMBRES_CAPA2.get(mejor[0]) if mejor else None},
                bbox=mejor[2] if mejor else (x0, y0, x1, y1),
            ))
        return eventos
