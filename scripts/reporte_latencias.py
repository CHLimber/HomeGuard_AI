"""Resume las latencias medidas en cada evento (BD) y las escribe en docs/PRUEBAS.md.

Uso:
    python scripts/reporte_latencias.py            usa la BD real (data/homeguard.db)
    python scripts/reporte_latencias.py --demo     usa la BD del modo demo
    python scripts/reporte_latencias.py --desde 2026-10-20

Latencias registradas por evento:
  - detección -> panel:    desde que el motor confirma la alarma hasta que llega el "ack" del panel
                           (incluye la vuelta del ack, así que es una cota superior)
  - detección -> Telegram: desde que el motor confirma hasta que la API de Telegram responde OK
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from homeguard.config import cargar_config, ruta_abs  # noqa: E402
from homeguard.db import modelos as m  # noqa: E402
from homeguard.db.sesion import BaseDatos  # noqa: E402
from scripts.evaluar_detector import RUTA_PRUEBAS, escribir_en_pruebas  # noqa: E402


def percentil(valores: list[float], p: float) -> float:
    v = sorted(valores)
    k = (len(v) - 1) * p
    i = int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


def fila(nombre: str, valores: list[float], objetivo: float) -> str:
    if not valores:
        return f"| {nombre} | 0 | — | — | — | — | — |"
    bajo = sum(v <= objetivo for v in valores) / len(valores) * 100
    return (f"| {nombre} | {len(valores)} | {statistics.mean(valores):.0f} | {statistics.median(valores):.0f} | "
            f"{percentil(valores, 0.95):.0f} | {max(valores):.0f} | {bajo:.0f} % |")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="usar la base de datos del modo demo")
    parser.add_argument("--bd", default=None, help="ruta de la base de datos")
    parser.add_argument("--desde", default=None, help="solo eventos desde esta fecha (AAAA-MM-DD)")
    parser.add_argument("--salida", default=str(RUTA_PRUEBAS))
    args = parser.parse_args(argv)
    from homeguard.logs import consola_utf8

    consola_utf8()

    cfg = cargar_config(demo=args.demo)
    objetivo = cfg.panel.latencia_objetivo_ms
    bd = BaseDatos(args.bd or ruta_abs(cfg.general.base_datos))
    q = select(m.Evento)
    if args.desde:
        q = q.where(m.Evento.creado_en >= datetime.fromisoformat(args.desde))
    with bd.sesion() as s:
        eventos = list(s.scalars(q))
    bd.cerrar()

    lineas = [
        f"_Generado por `scripts/reporte_latencias.py` el {datetime.now():%d/%m/%Y %H:%M} con {len(eventos)} eventos"
        f"{' (modo demo)' if args.demo else ''}. Objetivo: < {objetivo:.0f} ms._",
        "",
        "| Medición | Eventos | Promedio (ms) | Mediana (ms) | P95 (ms) | Máximo (ms) | ≤ objetivo |",
        "|---|---:|---:|---:|---:|---:|---:|",
        fila("Detección → panel", [e.latencia_panel_ms for e in eventos if e.latencia_panel_ms is not None], objetivo),
        fila("Detección → Telegram",
             [e.latencia_telegram_ms for e in eventos if e.latencia_telegram_ms is not None], objetivo),
        "",
        "| Anomalía | Eventos | Panel prom. (ms) | Telegram prom. (ms) |",
        "|---|---:|---:|---:|",
    ]
    for tipo in ("intrusion", "piscina", "fuego", "caida", "puerta"):
        evs = [e for e in eventos if e.tipo == tipo]
        panel = [e.latencia_panel_ms for e in evs if e.latencia_panel_ms is not None]
        tg = [e.latencia_telegram_ms for e in evs if e.latencia_telegram_ms is not None]
        prom_panel = f"{statistics.mean(panel):.0f}" if panel else "—"
        prom_tg = f"{statistics.mean(tg):.0f}" if tg else "—"
        lineas.append(f"| {tipo} | {len(evs)} | {prom_panel} | {prom_tg} |")
    texto = "\n".join(lineas)
    print(texto)
    escribir_en_pruebas(Path(args.salida), "latencias", texto)
    print(f"\nEscrito en {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
