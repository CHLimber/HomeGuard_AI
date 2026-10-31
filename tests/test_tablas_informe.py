"""Tablas para el informe: benchmark, métricas por detector y latencias, sin inventar datos."""
from __future__ import annotations

import csv
import time
from datetime import datetime

import yaml

from homeguard.db import consultas
from homeguard.db import modelos as m
from homeguard.db.sesion import BaseDatos
from scripts import generar_tablas_informe as gti
from scripts.evaluar_detector import escribir_en_pruebas

BENCHMARK_CSV = """variante,descripcion,repeticiones,ms_media,ms_mediana,ms_min,fps_equivalente,porcentaje_resultado,aceleracion_vs_A
A,Bucle Python,3,120.0,116.0751,115.9,8.6151,1.98,1.0
D,Bits con ROI,100,0.3,0.2736,0.23,3654.303,1.98,424.1736
"""

BLOQUE_FUEGO = """_Generado por `scripts/evaluar_detector.py --detector fuego`._

| VP | FP | VN | FN | Precisión | Recall | F1 | Exactitud |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | 1 | 4 | 1 | 0.80 | 0.80 | 0.80 | 0.80 |

| Video | Esperado | ¿Disparó? | Resultado | 1.ª alarma (s) | Frames analizados | ms/frame |
|---|---|---|---|---:|---:|---:|
| a.mp4 | positivo | sí | **VP** | 1.0 | 10 | 5.0 |"""


def _evento(tipo: str, panel: float | None, telegram: float | None, creado: datetime | None = None) -> m.Evento:
    return m.Evento(tipo=tipo, camara_id="cam", zona="z", t_deteccion=time.time(), latencia_panel_ms=panel,
                    latencia_telegram_ms=telegram, **({"creado_en": creado} if creado else {}))


def _leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def test_sin_datos_todo_por_medir(tmp_path):
    ruta_md = gti.generar([], 2000, tmp_path / "no_existe.csv", tmp_path / "no_existe.md", tmp_path / "salida", "0")
    texto = ruta_md.read_text(encoding="utf-8")
    assert texto.count("Por medir") >= 3
    detectores = _leer_csv(tmp_path / "salida" / "detectores.csv")
    assert len(detectores) == 6 and all(c == "Por medir" for f in detectores[1:] for c in f[1:])
    assert len(_leer_csv(tmp_path / "salida" / "benchmark.csv")) == 1  # solo el encabezado


def test_benchmark_y_detectores(tmp_path):
    (tmp_path / "benchmark.csv").write_text(BENCHMARK_CSV, encoding="utf-8")
    pruebas = tmp_path / "PRUEBAS.md"
    pruebas.write_text("# Pruebas\n<!-- fuego:INICIO -->\n_Pendiente_\n<!-- fuego:FIN -->\n", encoding="utf-8")
    escribir_en_pruebas(pruebas, "fuego", BLOQUE_FUEGO)

    gti.generar([], 2000, tmp_path / "benchmark.csv", pruebas, tmp_path / "salida", "0")
    bench = _leer_csv(tmp_path / "salida" / "benchmark.csv")
    assert bench[2] == ["D", "Bits con ROI", "0,274", "3654,3", "424,2x"]
    detectores = {f[0]: f for f in _leer_csv(tmp_path / "salida" / "detectores.csv")[1:]}
    assert detectores["Fuego / humo"] == ["Fuego / humo", "10", "4", "1", "4", "1", "0,80", "0,80", "0,80"]
    assert detectores["Puerta"][1] == "Por medir"


def test_latencias_desde_la_bd(ruta_config_prueba, tmp_path):
    ruta_bd = yaml.safe_load(ruta_config_prueba.read_text(encoding="utf-8"))["general"]["base_datos"]
    bd = BaseDatos(ruta_bd)
    with bd.sesion() as s:
        s.add_all([_evento("puerta", 100, 1000), _evento("puerta", 300, 3000), _evento("fuego", 200, None),
                   _evento("puerta", 50, 50, creado=datetime(2020, 1, 1))])
    assert len(consultas.eventos(bd)) == 4
    eventos = consultas.eventos(bd, datetime(2021, 1, 1))
    bd.cerrar()

    gti.generar(eventos, 2000, tmp_path / "x.csv", tmp_path / "x.md", tmp_path / "salida", "3 eventos")
    filas = _leer_csv(tmp_path / "salida" / "latencias.csv")
    assert filas[0][-1] == "% ≤ 2,0 s"
    assert filas[1] == ["Detección → panel", "3", "200", "290", "300", "100 %"]
    assert filas[2] == ["Detección → Telegram", "2", "2000", "2900", "3000", "50 %"]
