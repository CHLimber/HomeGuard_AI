"""Genera las tablas que el grupo pega en el informe Word (sección 6.2 "Resultados esperados").

Junta en un solo lugar, sin volver a medir nada:
  1. Benchmark bitwise         <- docs/benchmark.csv (python -m homeguard.preproceso.benchmark)
  2. Precisión/recall/F1       <- bloques de docs/PRUEBAS.md (scripts/evaluar_detector.py)
  3. Latencias panel/Telegram  <- eventos de la BD (los mismos cálculos que scripts/reporte_latencias.py)

Uso:
    python scripts/generar_tablas_informe.py              BD real (data/homeguard.db)
    python scripts/generar_tablas_informe.py --demo       BD del modo demo
    python scripts/generar_tablas_informe.py --desde 2026-11-20

Salida: docs/informe/tablas_informe.md y un CSV por tabla (benchmark.csv, detectores.csv, latencias.csv).
Donde todavía no hay datos se escribe "Por medir": este script nunca inventa resultados.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from homeguard.config import cargar_config, ruta_abs  # noqa: E402
from homeguard.db import consultas  # noqa: E402
from homeguard.db.sesion import BaseDatos  # noqa: E402
from scripts.evaluar_detector import RUTA_PRUEBAS, TIPO_DE_DETECTOR  # noqa: E402
from scripts.reporte_latencias import resumen  # noqa: E402

RUTA_BENCHMARK = RAIZ / "docs" / "benchmark.csv"
CARPETA_SALIDA = RAIZ / "docs" / "informe"
POR_MEDIR = "Por medir"
NOMBRE_DETECTOR = {"rostros": "Intrusión (rostros)", "piscina": "Piscina", "fuego": "Fuego / humo",
                   "caidas": "Caídas", "puerta": "Puerta"}
# Fila de resumen que escribe evaluar_detector.py: | VP | FP | VN | FN | Precisión | Recall | F1 | Exactitud |
FILA_METRICAS = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|"
                           r"\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*$", re.M)


def _tabla_md(encabezado: list[str], filas: list[list[str]], derecha_desde: int = 1) -> list[str]:
    alineacion = ["---" if i < derecha_desde else "---:" for i in range(len(encabezado))]
    return (["| " + " | ".join(encabezado) + " |", "|" + "|".join(alineacion) + "|"]
            + ["| " + " | ".join(c.replace("|", "\\|") for c in f) + " |" for f in filas])  # "|" del OR


def _escribir_csv(ruta: Path, encabezado: list[str], filas: list[list[str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel en Windows abre bien los acentos
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(encabezado)
        w.writerows(filas)


def _num(valor: float, decimales: int = 0) -> str:
    """Número con coma decimal, como en el informe."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def tabla_benchmark(ruta_csv: Path) -> tuple[list[str], list[list[str]]]:
    encabezado = ["Variante", "Descripción", "ms/frame (mediana)", "FPS equivalentes", "Aceleración vs. A"]
    if not ruta_csv.exists():
        return encabezado, []
    with ruta_csv.open(encoding="utf-8") as f:
        filas = [[r["variante"], r["descripcion"], _num(float(r["ms_mediana"]), 3),
                  _num(float(r["fps_equivalente"]), 1), _num(float(r["aceleracion_vs_A"]), 1) + "x"]
                 for r in csv.DictReader(f)]
    return encabezado, filas


def metricas_detectores(ruta_pruebas: Path) -> dict[str, dict[str, float] | None]:
    """Lee la fila de resumen de cada bloque <!-- detector:INICIO/FIN --> (None si el detector no se evaluó)."""
    texto = ruta_pruebas.read_text(encoding="utf-8") if ruta_pruebas.exists() else ""
    resultado: dict[str, dict[str, float] | None] = {}
    for detector in TIPO_DE_DETECTOR:
        bloque = re.search(rf"<!-- {detector}:INICIO -->(.*?)<!-- {detector}:FIN -->", texto, re.S)
        fila = FILA_METRICAS.search(bloque.group(1)) if bloque else None
        if fila is None:
            resultado[detector] = None
            continue
        vp, fp, vn, fn = (int(x) for x in fila.groups()[:4])
        precision, recall, f1, exactitud = (float(x) for x in fila.groups()[4:])
        resultado[detector] = {"VP": vp, "FP": fp, "VN": vn, "FN": fn, "videos": vp + fp + vn + fn,
                               "precision": precision, "recall": recall, "f1": f1, "exactitud": exactitud}
    return resultado


def tabla_detectores(ruta_pruebas: Path) -> tuple[list[str], list[list[str]]]:
    encabezado = ["Detector", "Videos", "VP", "FP", "VN", "FN", "Precisión", "Recall", "F1"]
    filas = []
    for detector, m in metricas_detectores(ruta_pruebas).items():
        if m is None:
            filas.append([NOMBRE_DETECTOR[detector]] + [POR_MEDIR] * (len(encabezado) - 1))
        else:
            filas.append([NOMBRE_DETECTOR[detector], str(m["videos"]), str(m["VP"]), str(m["FP"]), str(m["VN"]),
                          str(m["FN"]), _num(m["precision"], 2), _num(m["recall"], 2), _num(m["f1"], 2)])
    return encabezado, filas


def tabla_latencias(eventos: list, objetivo_ms: float) -> tuple[list[str], list[list[str]]]:
    encabezado = ["Medición", "Eventos", "Media (ms)", "P95 (ms)", "Máximo (ms)",
                  f"% ≤ {_num(objetivo_ms / 1000, 1)} s"]
    filas = []
    for nombre, campo in (("Detección → panel", "latencia_panel_ms"), ("Detección → Telegram", "latencia_telegram_ms")):
        r = resumen([getattr(e, campo) for e in eventos if getattr(e, campo) is not None], objetivo_ms)
        if r is None:
            filas.append([nombre, "0"] + [POR_MEDIR] * 4)
        else:
            filas.append([nombre, str(r["n"]), _num(r["promedio"]), _num(r["p95"]), _num(r["maximo"]),
                          _num(r["pct_objetivo"]) + " %"])
    return encabezado, filas


def generar(eventos: list, objetivo_ms: float, ruta_benchmark: Path, ruta_pruebas: Path, carpeta: Path,
            origen: str) -> Path:
    """Escribe tablas_informe.md y los CSV en `carpeta`. Devuelve la ruta del Markdown."""
    secciones = [
        ("benchmark", "Tabla 1. Benchmark del preprocesamiento bitwise (frame 640×480)",
         tabla_benchmark(ruta_benchmark), "python -m homeguard.preproceso.benchmark", 2),
        ("detectores", "Tabla 2. Precisión, recall y F1 por detector",
         tabla_detectores(ruta_pruebas), "python scripts/evaluar_detector.py --detector <detector> --carpeta ...", 1),
        ("latencias", "Tabla 3. Latencias de las alertas",
         tabla_latencias(eventos, objetivo_ms), "python scripts/reporte_latencias.py", 1),
    ]
    lineas = [
        "# Tablas para el informe (sección 6.2 \"Resultados esperados\")",
        "",
        f"_Generado por `scripts/generar_tablas_informe.py` el {datetime.now():%d/%m/%Y %H:%M}. "
        f"Latencias: {origen}. \"{POR_MEDIR}\" = todavía no hay datos medidos._",
    ]
    for clave, titulo, (encabezado, filas), comando, derecha_desde in secciones:
        lineas += ["", f"## {titulo}", ""]
        if filas:
            lineas += _tabla_md(encabezado, filas, derecha_desde)
        else:
            lineas.append(f"{POR_MEDIR}: ejecutar `{comando}`.")
        _escribir_csv(carpeta / f"{clave}.csv", encabezado, filas)
    if eventos:
        lineas += ["", "La latencia al panel se mide con el ack del panel, así que incluye la vuelta: es una cota "
                       "superior."]
    ruta_md = carpeta / "tablas_informe.md"
    ruta_md.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")
    return ruta_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="usar la base de datos del modo demo")
    parser.add_argument("--bd", default=None, help="ruta de la base de datos")
    parser.add_argument("--desde", default=None, help="solo eventos desde esta fecha (AAAA-MM-DD)")
    parser.add_argument("--benchmark", default=str(RUTA_BENCHMARK), help="CSV del benchmark")
    parser.add_argument("--pruebas", default=str(RUTA_PRUEBAS), help="docs/PRUEBAS.md con los resultados")
    parser.add_argument("--salida", default=str(CARPETA_SALIDA), help="carpeta donde escribir las tablas")
    args = parser.parse_args(argv)
    from homeguard.logs import consola_utf8

    consola_utf8()

    cfg = cargar_config(demo=args.demo)
    ruta_bd = args.bd or ruta_abs(cfg.general.base_datos)
    bd = BaseDatos(ruta_bd)
    eventos = consultas.eventos(bd, datetime.fromisoformat(args.desde) if args.desde else None)
    bd.cerrar()

    con_ack = sum(e.latencia_panel_ms is not None for e in eventos)
    origen = (f"{len(eventos)} eventos ({con_ack} con ack del panel) de `{Path(ruta_bd).name}`"
              + (f" desde {args.desde}" if args.desde else ""))
    ruta_md = generar(eventos, cfg.panel.latencia_objetivo_ms, Path(args.benchmark), Path(args.pruebas),
                      Path(args.salida), origen)
    print(ruta_md.read_text(encoding="utf-8"))
    print(f"Escrito en {ruta_md} (y un CSV por tabla en la misma carpeta)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
