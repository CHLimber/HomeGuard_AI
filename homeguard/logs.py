"""Configuración de logs: consola + archivo rotativo."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"


def consola_utf8() -> None:
    """UTF-8 también cuando la salida se redirige a un archivo o tubería (en Windows sería cp1252)."""
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")


def configurar_logs(nivel: str = "INFO", archivo: Path | None = None) -> None:
    consola_utf8()
    raiz = logging.getLogger()
    raiz.setLevel(nivel.upper())
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
    consola = logging.StreamHandler()
    consola.setFormatter(logging.Formatter(FORMATO, "%H:%M:%S"))
    raiz.addHandler(consola)
    if archivo:
        archivo.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(archivo, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(FORMATO))
        raiz.addHandler(fh)
    # librerías muy verbosas
    for ruidoso in ("ultralytics", "httpx", "urllib3", "uvicorn.access", "multipart"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
