"""Genera videos sintéticos cortos para probar el pipeline sin cámaras.

Uso:
    python scripts/generar_video_sintetico.py [--carpeta data/videos_prueba/sinteticos]

Videos (640x480, 15 FPS, 12 s, fondo fijo con ruido leve de sensor):
  - puerta.mp4: puerta cerrada 0-4 s, abierta (cambio brusco) 4-9 s, cerrada 9-12 s.
  - fuego.mp4:  objeto naranja que parpadea dentro de la zona "Cocina" entre 3 y 10 s.
  - zona.mp4:   rectángulo que entra a la zona "Piscina" y se queda quieto.
Cada video se acompaña de un .json con la verdad de terreno (ground truth) por frame,
que usan los tests (por ej. las cajas del rectángulo para simular detecciones de YOLO).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ANCHO, ALTO, FPS, SEGUNDOS = 640, 480, 15, 12
RAIZ = Path(__file__).resolve().parent.parent


def _fondo(semilla: int) -> np.ndarray:
    """Pared con degradé y textura fija (siempre igual para la misma semilla)."""
    rng = np.random.default_rng(semilla)
    grad = np.linspace(150, 200, ANCHO, dtype=np.float32)[None, :].repeat(ALTO, axis=0)
    textura = rng.normal(0, 6, (ALTO, ANCHO)).astype(np.float32)
    gris = np.clip(grad + textura, 0, 255).astype(np.uint8)
    fondo = cv2.merge([gris, (gris * 0.95).astype(np.uint8), (gris * 0.85).astype(np.uint8)])
    cv2.rectangle(fondo, (0, 400), (ANCHO, ALTO), (90, 110, 130), -1)  # piso
    return fondo


def _ruido(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.clip(img.astype(np.int16) + rng.integers(-3, 4, img.shape, dtype=np.int16), 0, 255).astype(np.uint8)


def _escribir(ruta: Path, frames: list[np.ndarray], verdad: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    w = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (ANCHO, ALTO))
    for f in frames:
        w.write(f)
    w.release()
    ruta.with_suffix(".json").write_text(json.dumps(verdad, indent=1), encoding="utf-8")


def generar_puerta(ruta: Path) -> None:
    rng = np.random.default_rng(1)
    fondo = _fondo(10)
    x0, y0, x1, y1 = int(0.40 * ANCHO), int(0.20 * ALTO), int(0.60 * ANCHO), int(0.85 * ALTO)
    cerrada = fondo.copy()
    cv2.rectangle(cerrada, (x0, y0), (x1, y1), (40, 70, 120), -1)          # hoja de la puerta
    cv2.rectangle(cerrada, (x0, y0), (x1, y1), (20, 35, 60), 3)            # marco
    cv2.circle(cerrada, (x1 - 15, (y0 + y1) // 2), 6, (60, 200, 230), -1)   # picaporte
    abierta = cerrada.copy()
    cv2.rectangle(abierta, (x0 + 3, y0 + 3), (x1 - 3, y1 - 3), (25, 22, 20), -1)    # interior oscuro
    cv2.rectangle(abierta, (x0 + 3, y0 + 3), (x0 + 22, y1 - 3), (40, 70, 120), -1)  # hoja vista de canto
    frames, abiertos = [], []
    for i in range(FPS * SEGUNDOS):
        t = i / FPS
        esta_abierta = 4.0 <= t < 9.0
        frames.append(_ruido(abierta if esta_abierta else cerrada, rng))
        abiertos.append(esta_abierta)
    _escribir(ruta, frames, {"fps": FPS, "zona_puerta": [x0, y0, x1, y1], "abierta": abiertos,
                             "descripcion": "cerrada 0-4 s, abierta 4-9 s, cerrada 9-12 s"})


def generar_fuego(ruta: Path) -> None:
    rng = np.random.default_rng(2)
    fondo = _fondo(20)
    cv2.rectangle(fondo, (180, 300), (460, 400), (70, 70, 70), -1)  # "cocina"
    frames, activo = [], []
    for i in range(FPS * SEGUNDOS):
        t = i / FPS
        img = fondo.copy()
        hay = 3.0 <= t < 10.0
        if hay:  # llama: elipses naranja/amarillo que cambian de tamaño y brillo cada frame
            cx, cy = 320, 290
            for capa, color in ((1.0, (0, 90, 255)), (0.65, (0, 170, 255)), (0.35, (120, 230, 255))):
                ax = int(rng.integers(25, 45) * capa) + 4
                ay = int(rng.integers(45, 85) * capa) + 6
                cv2.ellipse(img, (cx + int(rng.integers(-6, 7)), cy - ay // 2), (ax, ay), 0, 0, 360, color, -1)
        frames.append(_ruido(img, rng))
        activo.append(hay)
    _escribir(ruta, frames, {"fps": FPS, "fuego": activo, "descripcion": "llama naranja 3-10 s"})


def generar_zona(ruta: Path) -> None:
    rng = np.random.default_rng(3)
    fondo = _fondo(30)
    cv2.rectangle(fondo, (int(0.5 * ANCHO), int(0.3 * ALTO)), (int(0.95 * ANCHO), int(0.9 * ALTO)), (170, 140, 40), -1)
    frames, cajas = [], []
    w, h = 50, 140
    for i in range(FPS * SEGUNDOS):
        t = i / FPS
        # entra caminando de izquierda a derecha durante 5 s y luego queda inmóvil dentro de la "piscina"
        x = int(20 + min(t, 5.0) / 5.0 * 420)
        y = 260
        img = fondo.copy()
        cv2.rectangle(img, (x, y), (x + w, y + h), (60, 60, 200), -1)
        cv2.circle(img, (x + w // 2, y - 18), 18, (150, 180, 220), -1)
        frames.append(_ruido(img, rng))
        cajas.append([x, y - 36, x + w, y + h])
    _escribir(ruta, frames, {"fps": FPS, "cajas_persona": cajas,
                             "descripcion": "entra a la zona en ~3.5 s y queda inmóvil desde 5 s"})


def generar_todos(carpeta: Path) -> list[Path]:
    rutas = [carpeta / "puerta.mp4", carpeta / "fuego.mp4", carpeta / "zona.mp4"]
    generar_puerta(rutas[0])
    generar_fuego(rutas[1])
    generar_zona(rutas[2])
    return rutas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--carpeta", default=str(RAIZ / "data/videos_prueba/sinteticos"))
    args = parser.parse_args()
    for flujo in (sys.stdout, sys.stderr):  # UTF-8 aunque la salida se redirija (Windows usa cp1252)
        flujo.reconfigure(encoding="utf-8", errors="replace")
    for r in generar_todos(Path(args.carpeta)):
        print(f"[ok] {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
