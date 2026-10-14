"""Descarga todos los pesos preentrenados a la carpeta models/.

Uso:
    python scripts/descargar_modelos.py [--forzar]

Modelos:
  - yolov8n.pt            (Ultralytics, COCO: personas, perros, gatos)
  - yolov8n-pose.pt       (Ultralytics, 17 keypoints COCO)
  - fire_smoke_yolov8n.pt (Hugging Face rabahdev/fire-smoke-yolov8n, archivo best.pt; 0=smoke, 1=fire)
  - face_detection_yunet_2023mar.onnx   (Hugging Face opencv/face_detection_yunet)
  - face_recognition_sface_2021dec.onnx (Hugging Face opencv/face_recognition_sface)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "models"

# (repo de Hugging Face, archivo en el repo, nombre local)
MODELOS_HF = [
    ("rabahdev/fire-smoke-yolov8n", "best.pt", "fire_smoke_yolov8n.pt"),
    ("opencv/face_detection_yunet", "face_detection_yunet_2023mar.onnx", "face_detection_yunet_2023mar.onnx"),
    ("opencv/face_recognition_sface", "face_recognition_sface_2021dec.onnx", "face_recognition_sface_2021dec.onnx"),
]
MODELOS_ULTRALYTICS = ["yolov8n.pt", "yolov8n-pose.pt"]


def descargar_ultralytics(nombre: str, forzar: bool) -> None:
    destino = CARPETA / nombre
    if destino.exists() and not forzar:
        print(f"[ok] {nombre} ya existe")
        return
    from ultralytics.utils.downloads import attempt_download_asset

    # attempt_download_asset descarga desde los releases de Ultralytics a la ruta indicada
    ruta = Path(attempt_download_asset(str(destino)))
    if ruta.resolve() != destino.resolve():
        shutil.move(str(ruta), destino)
    print(f"[ok] {nombre} descargado")


def descargar_hf(repo: str, archivo: str, local: str, forzar: bool) -> None:
    destino = CARPETA / local
    if destino.exists() and not forzar:
        print(f"[ok] {local} ya existe")
        return
    from huggingface_hub import hf_hub_download

    ruta = hf_hub_download(repo_id=repo, filename=archivo)
    shutil.copy(ruta, destino)
    print(f"[ok] {local} descargado desde {repo}/{archivo}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forzar", action="store_true", help="vuelve a descargar aunque ya existan")
    args = parser.parse_args()
    CARPETA.mkdir(exist_ok=True)
    errores = 0
    for nombre in MODELOS_ULTRALYTICS:
        try:
            descargar_ultralytics(nombre, args.forzar)
        except Exception as e:  # noqa: BLE001 - se informa y se sigue con el resto
            errores += 1
            print(f"[ERROR] {nombre}: {e}")
    for repo, archivo, local in MODELOS_HF:
        try:
            descargar_hf(repo, archivo, local, args.forzar)
        except Exception as e:  # noqa: BLE001
            errores += 1
            print(f"[ERROR] {repo}/{archivo}: {e}")
    print("Listo." if errores == 0 else f"Terminado con {errores} error(es).")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
