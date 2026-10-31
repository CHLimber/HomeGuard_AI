"""Genera la tabla de "color fuego" de la capa 1 y la guarda como .npy.

La tabla se arma con los rangos HSV de config.yaml (detectores.fuego: hue_min, hue_max,
sat_min, val_min) y, opcionalmente, se le suman los colores que aparecen en recortes reales
de fuego (carpeta de imágenes .jpg/.png con solo la llama).

Uso:
    python scripts/generar_lut_fuego.py                       # tabla de 512 (índice de 9 bits del informe)
    python scripts/generar_lut_fuego.py --bits 8              # tabla de 256 (índice RGB332)
    python scripts/generar_lut_fuego.py --muestras data/muestras_fuego --min-pct 0.5
    python scripts/generar_lut_fuego.py --solo-muestras --muestras data/muestras_fuego

Después, en config.yaml (o en el dashboard):
    detectores.fuego.modo_capa1: lut9      (o lut332 si se generó con --bits 8)
    detectores.fuego.lut_archivo: data/lut_fuego_512.npy
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from homeguard.config import RUTA_CONFIG, cargar_config, ruta_abs  # noqa: E402
from homeguard.logs import consola_utf8  # noqa: E402
from homeguard.preproceso import bitwise  # noqa: E402

EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp"}


def lut_desde_muestras(imagenes: list[np.ndarray], bits: int, min_pct: float) -> np.ndarray:
    """Marca (255) los índices de color que ocupan al menos `min_pct` % de los píxeles de las muestras."""
    tamano = 512 if bits == 9 else 256
    conteo = np.zeros(tamano, dtype=np.int64)
    for img in imagenes:
        idx = bitwise.indice_rgb9(img) if bits == 9 else bitwise.indice_rgb332(img)
        conteo += np.bincount(idx.ravel(), minlength=tamano)  # histograma vectorizado de índices
    total = int(conteo.sum())
    if total == 0:
        return np.zeros(tamano, dtype=np.uint8)
    return np.where(100.0 * conteo / total >= min_pct, 255, 0).astype(np.uint8)


def leer_muestras(carpeta: Path) -> list[np.ndarray]:
    imagenes = []
    for ruta in sorted(carpeta.iterdir()):
        if ruta.suffix.lower() in EXTENSIONES:
            img = cv2.imread(str(ruta))  # BGR, el mismo orden que entregan las cámaras
            if img is None:
                print(f"  (no se pudo leer {ruta.name}, se omite)")
            else:
                imagenes.append(img)
    return imagenes


def main() -> None:
    consola_utf8()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bits", type=int, choices=[8, 9], default=9,
                        help="9 = índice del informe (tabla de 512, modo lut9); 8 = RGB332 (tabla de 256, modo lut332)")
    parser.add_argument("--config", default=str(RUTA_CONFIG), help="config.yaml de donde leer los rangos HSV")
    parser.add_argument("--muestras", default=None, help="carpeta con recortes de fuego (.jpg/.png)")
    parser.add_argument("--min-pct", type=float, default=0.5,
                        help="%% mínimo de píxeles de las muestras para marcar un color como fuego")
    parser.add_argument("--solo-muestras", action="store_true", help="no usar los rangos HSV, solo las muestras")
    parser.add_argument("--salida", default=None, help="archivo .npy (por defecto data/lut_fuego_<N>.npy)")
    args = parser.parse_args()

    tamano = 512 if args.bits == 9 else 256
    cfg = cargar_config(args.config).detectores.fuego
    rangos = (cfg.hue_min, cfg.hue_max, cfg.sat_min, cfg.val_min)

    if args.solo_muestras:
        if not args.muestras:
            parser.error("--solo-muestras necesita --muestras")
        lut = np.zeros(tamano, dtype=np.uint8)
    else:
        lut = bitwise.construir_lut_fuego_9bits(*rangos) if args.bits == 9 else bitwise.construir_lut_fuego(*rangos)
        print(f"Rangos HSV de config.yaml: tono {cfg.hue_min}-{cfg.hue_max}, saturación ≥ {cfg.sat_min}, "
              f"brillo ≥ {cfg.val_min} → {np.count_nonzero(lut)} colores")

    if args.muestras:
        carpeta = ruta_abs(args.muestras)
        if not carpeta.is_dir():
            parser.error(f"no existe la carpeta {carpeta}")
        imagenes = leer_muestras(carpeta)
        de_muestras = lut_desde_muestras(imagenes, args.bits, args.min_pct)
        print(f"Muestras: {len(imagenes)} imágenes → {np.count_nonzero(de_muestras)} colores con ≥ {args.min_pct} %")
        lut = np.bitwise_or(lut, de_muestras)  # unión de las dos tablas (OR)

    salida = ruta_abs(args.salida or f"data/lut_fuego_{tamano}.npy")
    salida.parent.mkdir(parents=True, exist_ok=True)
    np.save(salida, lut)
    modo = "lut9" if args.bits == 9 else "lut332"
    print(f"Tabla de {tamano} entradas: {np.count_nonzero(lut)} colores marcados como fuego → {salida}")
    print(f"Para usarla: detectores.fuego.modo_capa1: {modo} y detectores.fuego.lut_archivo: "
          f"{salida.relative_to(RAIZ) if salida.is_relative_to(RAIZ) else salida}")


if __name__ == "__main__":
    main()
