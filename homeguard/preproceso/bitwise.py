"""Preprocesamiento con operaciones de bits (AND, OR, XOR, desplazamientos).

Todas las funciones trabajan sobre matrices completas de NumPy/OpenCV: la
operación de bits se aplica a todos los píxeles a la vez (vectorizado, en C),
nunca con bucles de Python píxel a píxel. La explicación didáctica con
ejemplos numéricos está en docs/BITWISE.md.

Convención de máscaras: uint8 con 0 (apagado) o 255 (encendido = 0b11111111).
Usar 255 y no 1 permite combinarlas directamente con AND/OR bit a bit.
"""
from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

Mascara = np.ndarray  # uint8, valores 0 o 255


# ---------------------------------------------------------------------------
# Máscaras de región de interés (ROI): AND / OR
# ---------------------------------------------------------------------------

def mascara_poligono(alto: int, ancho: int, puntos_px: np.ndarray | Sequence) -> Mascara:
    """Máscara 0/255 con el polígono relleno."""
    mascara = np.zeros((alto, ancho), dtype=np.uint8)
    pts = np.asarray(puntos_px, dtype=np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(mascara, [pts], 255)
    return mascara


def mascara_roi(alto: int, ancho: int, poligonos: Sequence) -> Mascara:
    """Une varios polígonos en una sola máscara con OR."""
    mascara = np.zeros((alto, ancho), dtype=np.uint8)
    for pts in poligonos:
        mascara = cv2.bitwise_or(mascara, mascara_poligono(alto, ancho, pts))
    return mascara


def aplicar_mascara(img: np.ndarray, mascara: Mascara) -> np.ndarray:
    """AND bit a bit: los píxeles fuera de la máscara quedan en 0.

    x AND 255 = x   (dentro de la zona se conserva el valor)
    x AND 0   = 0   (fuera de la zona se borra)
    """
    return cv2.bitwise_and(img, img, mask=mascara)


def combinar_mascaras(*mascaras: Mascara, modo: str = "and") -> Mascara:
    """Combina máscaras: 'and' = intersección, 'or' = unión, 'xor' = diferencia simétrica."""
    # las versiones de cv2 hacen lo mismo que np.bitwise_* pero con instrucciones SIMD (~10x más rápido)
    operaciones = {"and": cv2.bitwise_and, "or": cv2.bitwise_or, "xor": cv2.bitwise_xor}
    if modo not in operaciones:
        raise ValueError(f"modo desconocido: {modo}")
    resultado = mascaras[0]
    for m in mascaras[1:]:
        resultado = operaciones[modo](resultado, m)
    return resultado


# ---------------------------------------------------------------------------
# Cuantización con desplazamientos (>>, <<)
# ---------------------------------------------------------------------------

def mascara_bits_altos(bits: int) -> int:
    """Byte con los `bits` más significativos encendidos. Ej. bits=4 -> (0xFF << 4) & 0xFF = 0b1111_0000."""
    return (0xFF << (8 - bits)) & 0xFF


def cuantizar(img: np.ndarray, bits: int) -> np.ndarray:
    """Conserva solo los `bits` más significativos de cada byte.

    Dos formas equivalentes:
      (x >> s) << s          con s = 8 - bits (desplazamientos)
      x AND mascara_bits_altos(bits)          (una sola AND, más rápida)
    Ej. bits=4: 0b1011_0110 (182) -> 0b1011_0000 (176).
    """
    # con un escalar se usa NumPy: cv2.bitwise_and(img, escalar) falla con imágenes muy chicas
    return np.bitwise_and(img, np.uint8(mascara_bits_altos(bits)))


def cuantizar_desplazando(img: np.ndarray, bits: int) -> np.ndarray:
    """Versión con desplazamientos (didáctica; da el mismo resultado que cuantizar)."""
    s = 8 - bits
    return np.left_shift(np.right_shift(img, s), s)


# ---------------------------------------------------------------------------
# Movimiento con XOR
# ---------------------------------------------------------------------------

def mascara_movimiento_xor(gris_anterior: np.ndarray, gris_actual: np.ndarray,
                           bits: int = 4, apertura_px: int = 3) -> Mascara:
    """Píxeles cuyo gris cuantizado cambió entre dos frames.

    a XOR b es 0 solo si a == b, así que XOR de los frames cuantizados marca
    los píxeles donde cambiaron los bits altos (cambio real, no ruido del
    sensor). Una apertura morfológica elimina puntos sueltos.
    """
    diferencia = cv2.bitwise_xor(cuantizar(gris_anterior, bits), cuantizar(gris_actual, bits))
    # cualquier bit encendido -> 255
    _, mascara = cv2.threshold(diferencia, 0, 255, cv2.THRESH_BINARY)
    if apertura_px > 0:
        kernel = np.ones((apertura_px, apertura_px), np.uint8)
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, kernel)
    return mascara


def binarizar(gris: np.ndarray, umbral: int = 0) -> Mascara:
    """Binariza a 0/255. umbral=0 usa Otsu (umbral automático)."""
    if umbral <= 0:
        _, b = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, b = cv2.threshold(gris, umbral, 255, cv2.THRESH_BINARY)
    return b


def xor_binarizadas(a: Mascara, b: Mascara) -> Mascara:
    """XOR de dos imágenes binarizadas: 255 donde difieren, 0 donde son iguales."""
    return cv2.bitwise_xor(a, b)


# ---------------------------------------------------------------------------
# Color por tabla de búsqueda (LUT) indexada con bits empaquetados
# ---------------------------------------------------------------------------

def indice_rgb332(bgr: np.ndarray) -> np.ndarray:
    """Empaqueta cada píxel en UN byte con el formato RGB332 (3 bits R, 3 bits G, 2 bits B).

        índice = (R & 0xE0) | ((G & 0xE0) >> 3) | (B >> 6)
                  RRR0_0000    000G_GG00           0000_00BB
    Ej. naranja BGR (0, 140, 255):
        R & 0xE0 = 1110_0000 (224) ; (G & 0xE0) >> 3 = 1000_0000 >> 3 = 0001_0000 (16) ; B >> 6 = 0
        índice = 224 | 16 | 0 = 240 = 0b1111_0000
    Como el índice cabe en 8 bits, la clasificación se hace con cv2.LUT (tabla de 256 entradas).
    """
    b, g, r = cv2.split(bgr)
    alto3 = np.uint8(0xE0)
    return cv2.bitwise_or(cv2.bitwise_or(np.bitwise_and(r, alto3), np.right_shift(np.bitwise_and(g, alto3), 3)),
                          np.right_shift(b, 6))


def _lut_desde_hsv(r: np.ndarray, g: np.ndarray, b: np.ndarray,
                   hue_min: int, hue_max: int, sat_min: int, val_min: int) -> np.ndarray:
    """Evalúa la regla HSV sobre una lista de colores (uno por entrada de la tabla) -> 0/255."""
    colores = np.stack([b, g, r], axis=-1).astype(np.uint8).reshape(1, -1, 3)
    hsv = cv2.cvtColor(colores, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    h, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    if hue_min <= hue_max:
        tono_ok = (h >= hue_min) & (h <= hue_max)
    else:  # rango que da la vuelta (ej. 170..10)
        tono_ok = (h >= hue_min) | (h <= hue_max)
    es_fuego = tono_ok & (sat >= sat_min) & (val >= val_min)
    return np.where(es_fuego, 255, 0).astype(np.uint8)


def construir_lut_fuego(hue_min: int, hue_max: int, sat_min: int, val_min: int) -> np.ndarray:
    """Precalcula, para cada uno de los 256 colores RGB332, si es "color fuego" (255) o no (0).

    La regla HSV se evalúa una sola vez sobre el color central de cada celda;
    después clasificar un frame entero es solo cv2.LUT(indice, lut).
    """
    idx = np.arange(256, dtype=np.uint16)
    r = (idx & 0xE0) + 16                 # bits 7-5 -> centro de la celda de 32 valores
    g = ((idx & 0x1C) << 3) + 16          # bits 4-2
    b = ((idx & 0x03) << 6) + 32          # bits 1-0 -> celda de 64 valores
    return _lut_desde_hsv(r, g, b, hue_min, hue_max, sat_min, val_min)


def mascara_color_lut(bgr: np.ndarray, lut: np.ndarray) -> Mascara:
    """Clasifica cada píxel con la tabla: una sola búsqueda vectorizada."""
    return cv2.LUT(indice_rgb332(bgr), lut)


# --- Variante del informe: índice de 9 bits (3 bits por canal) + tabla de 512 entradas ---

def indice_rgb9(bgr: np.ndarray) -> np.ndarray:
    """Índice de color de 9 bits del informe (ecuación del índice de color, sección 5.3):

        idx = ((R >> 5) << 6) | ((G >> 5) << 3) | (B >> 5)          -> 0..511
               RRR_000_000       000_GGG_000       000_000_BBB

    OpenCV entrega los canales en orden B, G, R: por eso se separan como (b, g, r).
    El índice ocupa 9 bits y no cabe en un byte: se calcula en uint16, porque en uint8
    `(R >> 5) << 6` perdería el bit más alto (ej. 7 << 6 = 448 > 255).
    Ej. naranja BGR (0, 140, 255):
        R >> 5 = 7 -> 7 << 6 = 448 ; G >> 5 = 4 -> 4 << 3 = 32 ; B >> 5 = 0
        idx = 448 | 32 | 0 = 480 = 0b111_100_000
    """
    b, g, r = cv2.split(bgr)
    r16 = np.right_shift(r, 5).astype(np.uint16)
    g16 = np.right_shift(g, 5).astype(np.uint16)
    b16 = np.right_shift(b, 5).astype(np.uint16)
    return np.left_shift(r16, 6) | np.left_shift(g16, 3) | b16


def construir_lut_fuego_9bits(hue_min: int, hue_max: int, sat_min: int, val_min: int) -> np.ndarray:
    """Tabla de 512 entradas (una por índice de 9 bits): 255 = "color fuego", 0 = no.

    Es la tabla booleana del informe guardada como 0/255 para que el resultado de
    `lut[idx]` ya sea una máscara combinable con AND/OR. Se evalúa la regla HSV
    sobre el color central de cada celda de 32×32×32 valores.
    Ej. entrada 480 = 0b111_100_000 -> centro (R, G, B) = (240, 144, 16): naranja -> 255.
    """
    idx = np.arange(512, dtype=np.uint16)
    r = ((idx >> 6) & 0x7) * 32 + 16      # bits 8-6 -> centro de la celda de 32 valores
    g = ((idx >> 3) & 0x7) * 32 + 16      # bits 5-3
    b = (idx & 0x7) * 32 + 16             # bits 2-0
    return _lut_desde_hsv(r, g, b, hue_min, hue_max, sat_min, val_min)


def mascara_color_lut9(bgr: np.ndarray, lut512: np.ndarray) -> Mascara:
    """Máscara = lut[idx]: indexación vectorizada de NumPy (cv2.LUT solo acepta tablas de 256)."""
    return lut512[indice_rgb9(bgr)]


def mascara_color_hsv(bgr: np.ndarray, hue_min: int, hue_max: int, sat_min: int, val_min: int) -> Mascara:
    """Alternativa clásica sin bits: conversión a HSV + cv2.inRange (para comparar con la LUT)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    if hue_min <= hue_max:
        return cv2.inRange(hsv, (hue_min, sat_min, val_min), (hue_max, 255, 255))
    # rango de tono que da la vuelta (ej. 170..10): unión de los dos tramos
    return cv2.bitwise_or(cv2.inRange(hsv, (hue_min, sat_min, val_min), (180, 255, 255)),
                          cv2.inRange(hsv, (0, sat_min, val_min), (hue_max, 255, 255)))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def porcentaje_activos(mascara: Mascara, roi: Mascara | None = None) -> float:
    """% de píxeles encendidos de `mascara` dentro de `roi` (o de toda la imagen)."""
    if roi is None:
        total = mascara.size
        activos = cv2.countNonZero(mascara)
    else:
        total = cv2.countNonZero(roi)
        activos = cv2.countNonZero(cv2.bitwise_and(mascara, roi))
    # Informe, ecuación de proporción de píxeles: countNonZero(máscara AND roi) / countNonZero(roi)
    return 100.0 * activos / total if total else 0.0


def bbox_poligono(puntos_px: np.ndarray | Sequence, alto: int, ancho: int) -> tuple[int, int, int, int]:
    """Rectángulo (x0, y0, x1, y1) que contiene al polígono, recortado a la imagen."""
    pts = np.asarray(puntos_px, dtype=np.int32).reshape(-1, 2)
    x0, y0 = np.clip(pts.min(axis=0), 0, [ancho - 1, alto - 1])
    x1, y1 = np.clip(pts.max(axis=0) + 1, 1, [ancho, alto])
    return int(x0), int(y0), int(x1), int(y1)
