"""Benchmark del preprocesamiento: impacto de vectorizar y de usar operaciones de bits.

Tarea medida = capa 1 del detector de fuego sobre un par de frames:
  "¿qué % de la zona tiene píxeles color fuego que además se movieron?"

Variantes:
  A. Bucle Python píxel a píxel (línea base, mismo algoritmo de bits que C y D)
  B. OpenCV clásico sin ROI: HSV + inRange + absdiff sobre el frame completo
  B2. OpenCV clásico con ROI: lo mismo que B pero solo en el recorte de la zona
  C. Bits vectorizados sin ROI: cuantización (AND 0xF0) + XOR + índice de color (>>, <<, |) + LUT
     (el índice es el de `detectores.fuego.modo_capa1`: 9 bits del informe por defecto, o RGB332)
  D. Bits vectorizados con ROI: recorte a la zona + C + AND con la máscara ROI (lo que usa HomeGuard)
  E. Como D, pero el XOR y los AND los hace C con SIMD (SSE2/AVX2, nativo/bitwise_simd.c).
     Solo aparece si la librería está compilada (Fase 7, opcional).

Uso:
    python -m homeguard.preproceso.benchmark [--repeticiones 30] [--frames-python 2]
Genera docs/benchmark.csv y docs/BENCHMARK.md con los tiempos medidos en ESTA máquina.
"""
from __future__ import annotations

import argparse
import csv
import platform
import statistics
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from homeguard.config import RAIZ, cargar_config
from homeguard.preproceso import bitwise as bw
from homeguard.preproceso import nativo

ZONA_NORM = [[0.20, 0.25], [0.80, 0.25], [0.80, 0.90], [0.20, 0.90]]  # zona "Cocina" del demo


def _frames_de_prueba(ancho: int) -> tuple[np.ndarray, np.ndarray]:
    """Dos frames consecutivos del video sintético de fuego (lo genera si falta)."""
    ruta = RAIZ / "data/videos_prueba/sinteticos/fuego.mp4"
    if not ruta.exists():
        from scripts.generar_video_sintetico import generar_todos

        generar_todos(ruta.parent)
    cap = cv2.VideoCapture(str(ruta))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 60)  # t = 4 s: hay llama
    _, a = cap.read()
    _, b = cap.read()
    cap.release()
    alto = round(a.shape[0] * ancho / a.shape[1])
    return cv2.resize(a, (ancho, alto)), cv2.resize(b, (ancho, alto))


class Preparado:
    """Lo que se calcula UNA vez al configurar la zona (no entra en la medición por frame)."""

    def __init__(self, alto: int, ancho: int, cfg) -> None:
        f = cfg.detectores.fuego
        self.bits_mov = cfg.preproceso.bits_movimiento
        # mismo índice de color que el detector: 9 bits (informe, tabla de 512) o RGB332 (tabla de 256)
        self.nueve_bits = f.modo_capa1 != "lut332"
        construir = bw.construir_lut_fuego_9bits if self.nueve_bits else bw.construir_lut_fuego
        self.lut = construir(f.hue_min, f.hue_max, f.sat_min, f.val_min)
        self.hsv_min = np.array([f.hue_min, f.sat_min, f.val_min], np.uint8)
        self.hsv_max = np.array([f.hue_max, 255, 255], np.uint8)
        pts = (np.array(ZONA_NORM) * [ancho, alto]).round().astype(np.int32)
        self.roi = bw.mascara_poligono(alto, ancho, pts)
        self.bbox = bw.bbox_poligono(pts, alto, ancho)
        x0, y0, x1, y1 = self.bbox
        # contiguo: el código C (variante E) recorre la memoria como bytes seguidos
        self.roi_recorte = np.ascontiguousarray(self.roi[y0:y1, x0:x1])
        self.total_roi = cv2.countNonZero(self.roi)
        self.roi_lista = self.roi.tolist()  # para el bucle Python


# ---------------------------------------------------------------------------
# Variantes (cada una devuelve el % de píxeles fuego+movimiento dentro de la zona)
# ---------------------------------------------------------------------------

def variante_a_bucle(prev: np.ndarray, act: np.ndarray, p: Preparado) -> float:
    """A. Píxel a píxel en Python: mismo algoritmo de bits que C/D, sin vectorizar."""
    mascara_q = bw.mascara_bits_altos(p.bits_mov)
    lut = p.lut.tolist()
    prev_l, act_l = prev.tolist(), act.tolist()
    alto, ancho = len(act_l), len(act_l[0])
    total = activos = 0
    for y in range(alto):
        fila_roi, fila_p, fila_a = p.roi_lista[y], prev_l[y], act_l[y]
        for x in range(ancho):
            if not fila_roi[x]:
                continue
            total += 1
            b, g, r = fila_a[x]
            bp, gp, rp = fila_p[x]
            # gris con la misma aritmética de punto fijo que OpenCV 5 (coeficientes << 15, redondeo, >> 15)
            gris = (9798 * r + 19235 * g + 3735 * b + 16384) >> 15
            gris_p = (9798 * rp + 19235 * gp + 3735 * bp + 16384) >> 15
            movio = (gris & mascara_q) ^ (gris_p & mascara_q)
            if p.nueve_bits:  # Informe, ecuación del índice de color: ((R>>5)<<6) | ((G>>5)<<3) | (B>>5)
                indice = ((r >> 5) << 6) | ((g >> 5) << 3) | (b >> 5)
            else:
                indice = (r & 0xE0) | ((g & 0xE0) >> 3) | (b >> 6)
            if movio and lut[indice]:
                activos += 1
    return 100.0 * activos / total if total else 0.0


def _clasica(prev: np.ndarray, act: np.ndarray, p: Preparado, roi: np.ndarray) -> float:
    color = cv2.inRange(cv2.cvtColor(act, cv2.COLOR_BGR2HSV), p.hsv_min, p.hsv_max)
    dif = cv2.absdiff(cv2.cvtColor(act, cv2.COLOR_BGR2GRAY), cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY))
    _, mov = cv2.threshold(dif, 1 << (8 - p.bits_mov), 255, cv2.THRESH_BINARY)
    return bw.porcentaje_activos(cv2.bitwise_and(color, mov), roi)


def variante_b_clasica(prev: np.ndarray, act: np.ndarray, p: Preparado) -> float:
    """B. OpenCV clásico, sin ROI ni bits: HSV + inRange + absdiff en todo el frame."""
    return _clasica(prev, act, p, p.roi)


def variante_b2_clasica_roi(prev: np.ndarray, act: np.ndarray, p: Preparado) -> float:
    """B2. OpenCV clásico solo dentro del recorte de la zona."""
    x0, y0, x1, y1 = p.bbox
    return _clasica(prev[y0:y1, x0:x1], act[y0:y1, x0:x1], p, p.roi_recorte)


def _mascara_color(bgr: np.ndarray, p: Preparado) -> np.ndarray:
    return bw.mascara_color_lut9(bgr, p.lut) if p.nueve_bits else bw.mascara_color_lut(bgr, p.lut)


def _bits(prev: np.ndarray, act: np.ndarray, p: Preparado, roi: np.ndarray) -> float:
    mov = bw.mascara_movimiento_xor(cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY), cv2.cvtColor(act, cv2.COLOR_BGR2GRAY),
                                    p.bits_mov, apertura_px=0)
    color = _mascara_color(act, p)
    return bw.porcentaje_activos(bw.combinar_mascaras(color, mov, roi, modo="and"), roi)


def variante_c_bits_sin_roi(prev: np.ndarray, act: np.ndarray, p: Preparado) -> float:
    """C. Bits vectorizados (AND, XOR, >>, |, LUT) sobre el frame completo."""
    return _bits(prev, act, p, p.roi)


def variante_d_bits_con_roi(prev: np.ndarray, act: np.ndarray, p: Preparado) -> float:
    """D. Recorte a la zona + AND con la ROI + XOR de cuantizados + LUT (lo que usa HomeGuard)."""
    x0, y0, x1, y1 = p.bbox
    return _bits(prev[y0:y1, x0:x1], act[y0:y1, x0:x1], p, p.roi_recorte)


def variante_e_simd_c(prev: np.ndarray, act: np.ndarray, p: Preparado) -> float:
    """E. Igual que D, pero (XOR de cuantizados) AND color AND zona se hace en C con SSE2/AVX2."""
    x0, y0, x1, y1 = p.bbox
    gris_prev = cv2.cvtColor(prev[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    gris_act = cv2.cvtColor(act[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    color = _mascara_color(act[y0:y1, x0:x1], p)
    # (a XOR b) AND color: distinto de 0 solo donde cambiaron los bits altos y el color es fuego
    m = nativo.xor_and(bw.cuantizar(gris_prev, p.bits_mov), bw.cuantizar(gris_act, p.bits_mov), color)
    m = nativo.and_(m, p.roi_recorte, salida=m)  # AND zona
    return 100.0 * cv2.countNonZero(m) / p.total_roi if p.total_roi else 0.0


VARIANTES: list[tuple[str, str, Callable]] = [
    ("A", "Bucle Python píxel a píxel (línea base)", variante_a_bucle),
    ("B", "OpenCV clásico sin ROI (HSV + absdiff)", variante_b_clasica),
    ("B2", "OpenCV clásico con ROI (HSV + absdiff)", variante_b2_clasica_roi),
    ("C", "Bits sin ROI (AND, XOR, >>, |, LUT)", variante_c_bits_sin_roi),
    ("D", "Bits con ROI (recorte + AND + XOR + LUT) — HomeGuard", variante_d_bits_con_roi),
]


def variantes_disponibles() -> list[tuple[str, str, Callable]]:
    """VARIANTES + la E si la librería SIMD está compilada (si no, se omite con un aviso)."""
    if not nativo.disponible():
        print("  (variante E omitida: falta compilar nativo/bitwise_simd.c, ver docs/BITWISE.md)")
        return VARIANTES
    return VARIANTES + [("E", f"C con SIMD {nativo.nivel()} (XOR + AND nativos) + ROI", variante_e_simd_c)]


def medir(funcion: Callable, prev, act, p, repeticiones: int) -> tuple[list[float], float]:
    funcion(prev, act, p)  # calentamiento
    tiempos = []
    resultado = 0.0
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        resultado = funcion(prev, act, p)
        tiempos.append((time.perf_counter() - t0) * 1000)
    return tiempos, resultado


def ejecutar(repeticiones: int = 30, frames_python: int = 2, ancho: int | None = None,
             carpeta_salida: Path | None = None) -> list[dict]:
    cfg = cargar_config()
    ancho = ancho or cfg.procesamiento.ancho_proceso
    prev, act = _frames_de_prueba(ancho)
    p = Preparado(act.shape[0], act.shape[1], cfg)
    filas = []
    for clave, nombre, funcion in variantes_disponibles():
        n = frames_python if clave == "A" else repeticiones
        tiempos, pct = medir(funcion, prev, act, p, n)
        filas.append({"variante": clave, "descripcion": nombre, "repeticiones": n,
                      "ms_media": statistics.mean(tiempos), "ms_mediana": statistics.median(tiempos),
                      "ms_min": min(tiempos), "fps_equivalente": 1000 / statistics.median(tiempos),
                      "porcentaje_resultado": pct})
        print(f"  {clave:>2}. {nombre:<52} {statistics.median(tiempos):10.3f} ms  (resultado {pct:.3f} %)")
    base = filas[0]["ms_mediana"]
    for f in filas:
        f["aceleracion_vs_A"] = base / f["ms_mediana"]

    salida = carpeta_salida or RAIZ / "docs"
    salida.mkdir(parents=True, exist_ok=True)
    with open(salida / "benchmark.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        for f in filas:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()})
    _escribir_markdown(salida / "BENCHMARK.md", filas, act.shape, p)
    return filas


def _escribir_markdown(ruta: Path, filas: list[dict], forma: tuple, p: Preparado) -> None:
    x0, y0, x1, y1 = p.bbox
    # Informe, ecuación del tamaño de fotograma: ancho × alto × 3 bytes (640×480 BGR = 921 600 bytes)
    zona_pct = 100 * cv2.countNonZero(p.roi) / (forma[0] * forma[1])
    lineas = [
        "# Benchmark del preprocesamiento bitwise",
        "",
        f"Generado automáticamente por `python -m homeguard.preproceso.benchmark` el {datetime.now():%d/%m/%Y %H:%M}.",
        f"Máquina: {platform.processor() or platform.machine()} · Python {platform.python_version()} · "
        f"NumPy {np.__version__} · OpenCV {cv2.__version__}.",
        "",
        f"Tarea: capa 1 del detector de fuego (color fuego AND movimiento dentro de la zona) sobre frames de "
        f"{forma[1]}x{forma[0]} del video sintético `fuego.mp4`. La zona ocupa el {zona_pct:.0f} % del frame "
        f"(recorte {x1 - x0}x{y1 - y0}). Índice de color de A, C y D: "
        + ("9 bits del informe (tabla de 512)." if p.nueve_bits else "RGB332 de 8 bits (tabla de 256)."),
        "",
        "| Variante | Descripción | ms/frame (mediana) | FPS equivalentes | Aceleración vs A | Resultado (% zona) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for f in filas:
        descripcion = f["descripcion"].replace("|", r"\|")  # el | literal rompería la tabla Markdown
        lineas.append(f"| {f['variante']} | {descripcion} | {f['ms_mediana']:.3f} | {f['fps_equivalente']:.1f} | "
                      f"{f['aceleracion_vs_A']:.0f}x | {f['porcentaje_resultado']:.3f} |")
    lineas += [
        "",
        "Lectura (con los números de esta tabla):",
        "- **A vs D** — vectorizar: el mismo algoritmo de bits, píxel a píxel en Python o sobre la matriz completa. "
        "Es la diferencia más grande y la razón por la que el sistema puede analizar video en tiempo real.",
        "- **C vs D** y **B vs B2** — ROI: procesar solo el recorte de la zona (y anular el resto con AND) ahorra "
        "aproximadamente en proporción al área que se descarta.",
        "- **B2 vs D** — bits vs HSV a igual área: compara la cuantización con AND + índice de color + LUT contra la "
        "conversión HSV optimizada de OpenCV. Ver el resultado en la tabla: si la diferencia es chica, la ventaja de la LUT "
        "no es la velocidad sino que cualquier regla de color (por compleja que sea) cuesta lo mismo: una búsqueda por píxel.",
        "- A, C y D usan exactamente las mismas operaciones de bits, por eso dan el mismo resultado; "
        "B y B2 difieren un poco porque usan HSV exacto y umbral de diferencia en lugar de XOR de cuantizados.",
        "",
        "Los números cambian según la computadora: volvé a ejecutar el benchmark en la laptop de la feria.",
    ]
    if any(f["variante"] == "E" for f in filas):  # antes de la línea en blanco y la nota final
        lineas.insert(len(lineas) - 2, "- **D vs E** — SIMD escrito a mano en C (Fase 7): mismo resultado que D; el "
                      "XOR y los AND los ejecutan pxor/pand (SSE2) o vpxor/vpand (AVX2) sobre 16 o 32 píxeles a la vez.")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeticiones", type=int, default=30, help="repeticiones de las variantes vectorizadas")
    parser.add_argument("--frames-python", type=int, default=2, help="repeticiones del bucle Python (es lento)")
    parser.add_argument("--ancho", type=int, default=None, help="ancho del frame (por defecto ancho_proceso)")
    args = parser.parse_args()
    from homeguard.logs import consola_utf8

    consola_utf8()
    print("Benchmark de preprocesamiento (ms por frame):")
    ejecutar(args.repeticiones, args.frames_python, args.ancho)
    print("Resultados en docs/benchmark.csv y docs/BENCHMARK.md")


if __name__ == "__main__":
    main()
