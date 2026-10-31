"""Fixtures comunes de los tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from homeguard.config import RUTA_CONFIG, cargar_config  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return cargar_config()


@pytest.fixture(scope="session")
def videos_sinteticos(tmp_path_factory) -> Path:
    """Genera los videos sintéticos una vez por sesión de tests."""
    from scripts.generar_video_sintetico import generar_todos

    carpeta = tmp_path_factory.mktemp("sinteticos")
    generar_todos(carpeta)
    return carpeta


def leer_video(ruta: Path):
    import cv2

    cap = cv2.VideoCapture(str(ruta))
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        yield frame
    cap.release()


def verdad(ruta_video: Path) -> dict:
    return json.loads(ruta_video.with_suffix(".json").read_text(encoding="utf-8"))


@pytest.fixture
def ruta_config_prueba(tmp_path) -> Path:
    """config.yaml con rutas temporales y sin cámaras (no toca data/ ni la webcam)."""
    datos = yaml.safe_load(RUTA_CONFIG.read_text(encoding="utf-8"))
    datos["general"].update({
        "base_datos": str(tmp_path / "prueba.db"),
        "carpeta_eventos": str(tmp_path / "eventos"),
        "carpeta_referencias": str(tmp_path / "referencias"),
        "carpeta_pruebas": str(tmp_path / "pruebas"),
        "archivo_log": str(tmp_path / "prueba.log"),
    })
    datos["camaras"] = {}
    datos["telegram"]["activo"] = False
    ruta = tmp_path / "config.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    return ruta


@pytest.fixture
def sistema(ruta_config_prueba):
    from homeguard.sistema import Sistema

    s = Sistema(sin_telegram=True, ruta_config=ruta_config_prueba)
    yield s
    s.telegram.detener()
    s.bd.cerrar()
