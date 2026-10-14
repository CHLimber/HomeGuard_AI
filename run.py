"""Punto de entrada de HomeGuard AI.

Uso:
    python run.py                  cámaras reales de config.yaml
    python run.py --demo           videos de data/videos_prueba en bucle (BD aparte)
    python run.py --sin-telegram   no envía nada a Telegram (solo log)
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from pathlib import Path

os.environ.setdefault("YOLO_VERBOSE", "False")

import uvicorn  # noqa: E402

from homeguard.config import RUTA_CONFIG, cargar_config, ruta_abs  # noqa: E402
from homeguard.logs import configurar_logs  # noqa: E402

log = logging.getLogger("homeguard")


def ips_locales() -> list[str]:
    """IPs de la laptop en la red local (para abrir el panel desde el celular)."""
    ips: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no envía nada: solo elige la interfaz de salida
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="usa videos en bucle en lugar de cámaras")
    parser.add_argument("--sin-telegram", action="store_true", help="no envía alertas a Telegram")
    parser.add_argument("--config", default=str(RUTA_CONFIG), help="ruta de config.yaml")
    parser.add_argument("--host", default=None, help="host del servidor (por defecto el de config.yaml)")
    parser.add_argument("--puerto", type=int, default=None, help="puerto (por defecto el de config.yaml)")
    args = parser.parse_args()

    cfg = cargar_config(args.config, demo=args.demo)
    configurar_logs(cfg.general.nivel_log, ruta_abs(cfg.general.archivo_log))

    if args.demo:
        from scripts.generar_video_sintetico import generar_todos

        faltan = [c.fuente for c in cfg.camaras.values() if isinstance(c.fuente, str) and not ruta_abs(c.fuente).exists()]
        if faltan:
            log.info("Generando videos sintéticos para el modo demo...")
            generar_todos(ruta_abs("data/videos_prueba/sinteticos"))

    from homeguard.sistema import Sistema
    from homeguard.web.app import crear_app

    host = args.host or cfg.servidor.host
    puerto = args.puerto or cfg.servidor.puerto
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, puerto))
        except OSError:
            log.error("El puerto %d está ocupado: ¿HomeGuard ya está abierto en otra ventana? "
                      "Cerralo o usá --puerto 8001", puerto)
            return 1

    sistema = Sistema(demo=args.demo, sin_telegram=args.sin_telegram, ruta_config=Path(args.config))
    app = crear_app(sistema)

    print("\n" + "=" * 64)
    print(f" HomeGuard AI {'(MODO DEMO)' if args.demo else ''}")
    print(f"   Dashboard:        http://localhost:{puerto}/en-vivo")
    for ip in ips_locales():
        print(f"   Panel (celular):  http://{ip}:{puerto}/alarma")
    print(" Ctrl+C para salir")
    print("=" * 64 + "\n")

    uvicorn.run(app, host=host, port=puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
