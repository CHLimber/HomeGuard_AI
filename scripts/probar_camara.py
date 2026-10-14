"""Abre una cámara (índice, URL o archivo) y muestra el video con sus FPS.

Uso:
    python scripts/probar_camara.py 0
    python scripts/probar_camara.py http://192.168.1.50:8080/video
    python scripts/probar_camara.py data/videos_prueba/sinteticos/puerta.mp4
    python scripts/probar_camara.py 0 --sin-ventana --segundos 5   (solo mide FPS)

Tecla q o ESC para salir.
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fuente", help="índice de webcam (0, 1...), URL o ruta de video")
    parser.add_argument("--sin-ventana", action="store_true", help="no abre ventana, solo imprime FPS")
    parser.add_argument("--segundos", type=float, default=0, help="duración de la prueba (0 = hasta apretar q)")
    args = parser.parse_args()

    fuente: int | str = int(args.fuente) if args.fuente.isdigit() else args.fuente
    print(f"Abriendo {fuente!r}...")
    cap = cv2.VideoCapture(fuente)
    if not cap.isOpened():
        print("No se pudo abrir la fuente. Revisá la URL, que el celular esté en la misma red Wi-Fi "
              "y que la app (IP Webcam / DroidCam) esté transmitiendo.")
        return 1

    inicio = time.time()
    t_ultimo = inicio
    frames = 0
    fps = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            print("La fuente dejó de entregar frames.")
            break
        frames += 1
        ahora = time.time()
        if ahora - t_ultimo >= 1.0:
            fps = frames / (ahora - t_ultimo)
            frames, t_ultimo = 0, ahora
            print(f"{fps:5.1f} FPS  resolución {frame.shape[1]}x{frame.shape[0]}")
        if not args.sin_ventana:
            cv2.putText(frame, f"{fps:.1f} FPS", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.imshow("HomeGuard - probar camara (q para salir)", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
        if args.segundos and ahora - inicio >= args.segundos:
            break
    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
