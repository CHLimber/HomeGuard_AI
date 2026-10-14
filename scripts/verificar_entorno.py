"""Chequea que todo esté listo para correr HomeGuard AI.

Uso:
    python scripts/verificar_entorno.py [--sin-camaras] [--cargar-modelos]

Revisa: versión de Python, paquetes, config.yaml, modelos, carpetas, cámaras
activas, Telegram (.env) y que el puerto del servidor esté libre.
[OK] = bien, [AVISO] = depende del grupo / no bloquea, [ERROR] = hay que arreglarlo.
"""
from __future__ import annotations

import argparse
import importlib
import os
import socket
import sys
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

if os.name == "nt":
    os.system("")  # habilita colores ANSI en la consola de Windows

VERDE, AMARILLO, ROJO, FIN = "\033[92m", "\033[93m", "\033[91m", "\033[0m"
contadores = {"ok": 0, "aviso": 0, "error": 0}


def ok(msg: str) -> None:
    contadores["ok"] += 1
    print(f"{VERDE}[OK]{FIN}    {msg}")


def aviso(msg: str) -> None:
    contadores["aviso"] += 1
    print(f"{AMARILLO}[AVISO]{FIN} {msg}")


def error(msg: str) -> None:
    contadores["error"] += 1
    print(f"{ROJO}[ERROR]{FIN} {msg}")


def chequear_python() -> None:
    v = sys.version_info
    texto = f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if (v.major, v.minor) in ((3, 11), (3, 12)):
        ok(texto)
    elif (v.major, v.minor) >= (3, 10):
        aviso(texto + " - se recomienda 3.11 o 3.12")
    else:
        error(texto + " - se necesita Python 3.10 o superior (recomendado 3.11/3.12)")
    if sys.prefix == sys.base_prefix:
        aviso("No estás dentro de un entorno virtual (.venv). Activalo antes de correr el sistema.")


def chequear_paquetes() -> None:
    paquetes = {
        "cv2": "opencv-python", "numpy": "numpy", "ultralytics": "ultralytics", "torch": "torch",
        "supervision": "supervision", "fastapi": "fastapi", "uvicorn": "uvicorn", "jinja2": "jinja2",
        "multipart": "python-multipart", "sqlalchemy": "sqlalchemy", "pydantic": "pydantic",
        "yaml": "pyyaml", "dotenv": "python-dotenv", "requests": "requests",
        "huggingface_hub": "huggingface_hub", "psutil": "psutil", "pytest": "pytest", "httpx": "httpx",
    }
    for modulo, nombre in paquetes.items():
        try:
            m = importlib.import_module(modulo)
            ok(f"{nombre} {getattr(m, '__version__', '')}")
        except Exception as e:  # noqa: BLE001
            error(f"{nombre} no se puede importar ({e}). Ejecutá: pip install -r requirements.txt")
    try:
        import cv2

        if not (hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")):
            error("OpenCV sin FaceDetectorYN/FaceRecognizerSF: se necesita opencv-python>=4.10")
        import torch

        ok(f"torch usa {'CUDA' if torch.cuda.is_available() else 'CPU'}")
    except Exception:  # noqa: BLE001
        pass


def chequear_config():
    try:
        from homeguard.config import cargar_config

        cfg = cargar_config()
        ok(f"config.yaml válido ({len(cfg.camaras)} cámaras, {sum(c.activa for c in cfg.camaras.values())} activas)")
        return cfg
    except Exception as e:  # noqa: BLE001
        error(f"config.yaml inválido: {e}")
        return None


def chequear_modelos(cfg, cargar: bool) -> None:
    from homeguard.config import ruta_abs

    rutas = [
        cfg.yolo_general.modelo, cfg.detectores.caidas.modelo, cfg.detectores.fuego.modelo,
        cfg.detectores.rostros.modelo_detector, cfg.detectores.rostros.modelo_reconocedor,
    ]
    faltan = False
    for r in rutas:
        p = ruta_abs(r)
        if p.exists() and p.stat().st_size > 1000:
            ok(f"modelo {r} ({p.stat().st_size / 1e6:.1f} MB)")
        else:
            faltan = True
            error(f"falta el modelo {r}")
    if faltan:
        print("        -> ejecutá: python scripts/descargar_modelos.py")
        return
    if cargar:
        try:
            import cv2
            from ultralytics import YOLO

            for r in rutas[:3]:
                YOLO(str(ruta_abs(r)))
            cv2.FaceDetectorYN.create(str(ruta_abs(rutas[3])), "", (320, 320))
            cv2.FaceRecognizerSF.create(str(ruta_abs(rutas[4])), "")
            ok("todos los modelos cargan correctamente")
        except Exception as e:  # noqa: BLE001
            error(f"un modelo no carga: {e}")


def chequear_carpetas(cfg) -> None:
    from homeguard.config import ruta_abs

    for r in (cfg.general.carpeta_eventos, cfg.general.carpeta_referencias, Path(cfg.general.base_datos).parent):
        p = ruta_abs(r)
        try:
            p.mkdir(parents=True, exist_ok=True)
            prueba = p / ".escritura_prueba"
            prueba.write_text("x")
            prueba.unlink()
            ok(f"carpeta {r} con permiso de escritura")
        except Exception as e:  # noqa: BLE001
            error(f"no se puede escribir en {r}: {e}")


def abrir_con_timeout(fuente, timeout: float = 8.0):
    """Abre una fuente de video en otro hilo (cv2 puede colgarse con URLs que no responden)."""
    import cv2

    resultado: dict = {}

    def _abrir() -> None:
        cap = cv2.VideoCapture(fuente)
        ok_, frame = cap.read() if cap.isOpened() else (False, None)
        resultado["ok"] = ok_
        resultado["forma"] = None if frame is None else frame.shape
        cap.release()

    h = threading.Thread(target=_abrir, daemon=True)
    h.start()
    h.join(timeout)
    return resultado.get("ok", False), resultado.get("forma")


def chequear_camaras(cfg) -> None:
    from homeguard.config import ruta_abs

    for cid, cam in cfg.camaras.items():
        if not cam.activa:
            aviso(f"cámara '{cid}' desactivada en config.yaml (fuente {cam.fuente})")
            continue
        fuente = cam.fuente
        if isinstance(fuente, str) and not fuente.startswith(("http://", "https://", "rtsp://")):
            fuente = str(ruta_abs(fuente))
        abierta, forma = abrir_con_timeout(fuente)
        if abierta:
            ok(f"cámara '{cid}' entrega frames {forma[1]}x{forma[0]} ({cam.fuente})")
        else:
            aviso(f"cámara '{cid}' no responde ({cam.fuente}). Revisá la URL/IP del celular o que la webcam no esté en uso.")


def chequear_telegram() -> None:
    import requests

    from homeguard.config import cargar_secretos

    s = cargar_secretos()
    if not (RAIZ / ".env").exists():
        aviso("no existe .env (copiá .env.example como .env y completá TELEGRAM_TOKEN y TELEGRAM_CHAT_ID)")
        return
    if not s.telegram_token:
        aviso("TELEGRAM_TOKEN vacío en .env: las alertas solo se registrarán en el log")
        return
    try:
        r = requests.get(f"https://api.telegram.org/bot{s.telegram_token}/getMe", timeout=8)
        if r.ok:
            ok(f"token de Telegram válido (bot @{r.json()['result']['username']})")
        else:
            error(f"token de Telegram rechazado: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001
        aviso(f"no se pudo contactar a Telegram (¿sin internet?): {e}")
    if not s.telegram_chat_id:
        aviso("TELEGRAM_CHAT_ID vacío. Obtenelo con: python scripts/probar_telegram.py --obtener-chat-id")
    else:
        ok("TELEGRAM_CHAT_ID configurado")


def chequear_puerto(cfg) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", cfg.servidor.puerto))
            ok(f"puerto {cfg.servidor.puerto} libre")
        except OSError:
            aviso(f"puerto {cfg.servidor.puerto} ocupado (¿HomeGuard ya está corriendo?)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sin-camaras", action="store_true", help="no intenta abrir las cámaras")
    parser.add_argument("--cargar-modelos", action="store_true", help="además de verificar archivos, carga cada modelo")
    args = parser.parse_args()
    from homeguard.logs import consola_utf8

    consola_utf8()

    print("== Python y paquetes ==")
    chequear_python()
    chequear_paquetes()
    print("\n== Configuración ==")
    cfg = chequear_config()
    if cfg:
        print("\n== Modelos ==")
        chequear_modelos(cfg, args.cargar_modelos)
        print("\n== Carpetas ==")
        chequear_carpetas(cfg)
        if not args.sin_camaras:
            print("\n== Cámaras ==")
            chequear_camaras(cfg)
        print("\n== Red ==")
        chequear_puerto(cfg)
    print("\n== Telegram ==")
    chequear_telegram()

    print(f"\nResumen: {contadores['ok']} OK, {contadores['aviso']} avisos, {contadores['error']} errores")
    return 1 if contadores["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
