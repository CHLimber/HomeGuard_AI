"""Evalúa un detector con videos etiquetados y escribe los resultados en docs/PRUEBAS.md.

Estructura esperada:
    data/videos_prueba/<anomalia>/positivos/*.mp4   videos donde SÍ ocurre la anomalía
    data/videos_prueba/<anomalia>/negativos/*.mp4   videos donde NO ocurre (situaciones parecidas)

Uso:
    python scripts/evaluar_detector.py --detector fuego --carpeta data/videos_prueba/fuego
    python scripts/evaluar_detector.py --detector puerta --carpeta data/videos_prueba/puerta --zonas-de celular1

Cada video se pasa por el mismo analizador y motor de reglas que usa el sistema en vivo
(con los umbrales de config.yaml + los cambios del dashboard). Un video "dispara" si el motor
confirma al menos una alarma del tipo evaluado. Resultado por video:
    VP: positivo y disparó  ·  FN: positivo y no disparó
    FP: negativo y disparó  ·  VN: negativo y no disparó

Zonas (en este orden de prioridad):
  1. un archivo <video>.zonas.json al lado del video:
       [{"nombre": "Puerta", "tipo": "puerta", "puntos": [[0.4,0.2],[0.6,0.2],[0.6,0.9],[0.4,0.9]]}]
  2. --zonas-de CAMARA: usa las zonas dibujadas en el dashboard para esa cámara
  3. si no hay ninguna: una zona que cubre toda la imagen con el tipo que necesita el detector
Para "rostros" se usan los residentes registrados en la base de datos.
El tiempo se toma del video (frame / FPS), así la evaluación corre más rápido que en vivo.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from homeguard.analizador import Analizador  # noqa: E402
from homeguard.config import RUTA_CONFIG, Config, cargar_config, ruta_abs  # noqa: E402
from homeguard.detectores.base import Zona  # noqa: E402
from homeguard.detectores.modelos import Modelos  # noqa: E402
from homeguard.reglas.motor import MotorReglas  # noqa: E402

TIPO_DE_DETECTOR = {"rostros": "intrusion", "piscina": "piscina", "fuego": "fuego", "caidas": "caida", "puerta": "puerta"}
ZONA_POR_DEFECTO = {"rostros": "acceso", "piscina": "piscina", "puerta": "puerta"}  # fuego y caídas no la necesitan
EXTENSIONES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
RUTA_PRUEBAS = RAIZ / "docs" / "PRUEBAS.md"


@dataclass
class ResultadoVideo:
    archivo: str
    esperado: bool
    disparo: bool
    t_primera_alarma: float | None
    frames: int
    ms_por_frame: float

    @property
    def clase(self) -> str:
        if self.esperado:
            return "VP" if self.disparo else "FN"
        return "FP" if self.disparo else "VN"


def zonas_para(video: Path, detector: str, zonas_bd: list[Zona]) -> list[Zona]:
    sidecar = video.with_suffix(".zonas.json")
    if sidecar.exists():
        datos = json.loads(sidecar.read_text(encoding="utf-8"))
        return [Zona(i + 1, "eval", z["nombre"], z["tipo"], z["puntos"]) for i, z in enumerate(datos)]
    if zonas_bd:
        return zonas_bd
    tipo = ZONA_POR_DEFECTO.get(detector)
    if tipo is None:
        return []
    return [Zona(1, "eval", "toda la imagen", tipo, [[0, 0], [1, 0], [1, 1], [0, 1]])]


def evaluar_video(video: Path, esperado: bool, detector: str, cfg: Config, analizador: Analizador,
                  zonas: list[Zona]) -> ResultadoVideo:
    analizador.reiniciar()
    motor = MotorReglas(cfg.alarmas, cfg.motor)
    cap = cv2.VideoCapture(str(video))
    fps_video = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # analizar al mismo ritmo que en vivo (fps_objetivo): las reglas cuentan frames analizados
    paso = max(1, round(fps_video / cfg.procesamiento.fps_objetivo))
    tipo = TIPO_DE_DETECTOR[detector]
    hora = datetime.now().replace(hour=3, minute=0)  # madrugada: fuera de cualquier horario permitido típico
    i = analizados = 0
    t_alarma = None
    tiempos = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % paso == 0:
            t = i / fps_video
            inicio = time.perf_counter()
            _, obs = analizador.analizar("eval", frame, t, cfg, zonas, [detector], hora=hora)
            tiempos.append((time.perf_counter() - inicio) * 1000)
            analizados += 1
            if t_alarma is None and any(d.tipo == tipo for d in motor.procesar(obs)):
                t_alarma = t
        i += 1
    cap.release()
    return ResultadoVideo(video.name, esperado, t_alarma is not None, t_alarma, analizados,
                          statistics.mean(tiempos) if tiempos else 0.0)


def metricas(res: list[ResultadoVideo]) -> dict[str, float | int]:
    c = {k: sum(r.clase == k for r in res) for k in ("VP", "FP", "VN", "FN")}
    vp, fp, vn, fn = c["VP"], c["FP"], c["VN"], c["FN"]
    precision = vp / (vp + fp) if vp + fp else 0.0
    recall = vp / (vp + fn) if vp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    exactitud = (vp + vn) / len(res) if res else 0.0
    return {**c, "precision": precision, "recall": recall, "f1": f1, "exactitud": exactitud}


def tabla_markdown(detector: str, carpeta: Path, res: list[ResultadoVideo], m: dict) -> str:
    lineas = [
        f"_Generado por `scripts/evaluar_detector.py --detector {detector}` el {datetime.now():%d/%m/%Y %H:%M} "
        f"con {len(res)} videos de `{carpeta.as_posix()}`._",
        "",
        "| VP | FP | VN | FN | Precisión | Recall | F1 | Exactitud |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {m['VP']} | {m['FP']} | {m['VN']} | {m['FN']} | {m['precision']:.2f} | {m['recall']:.2f} | "
        f"{m['f1']:.2f} | {m['exactitud']:.2f} |",
        "",
        "| Video | Esperado | ¿Disparó? | Resultado | 1.ª alarma (s) | Frames analizados | ms/frame |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for r in res:
        lineas.append(f"| {r.archivo} | {'positivo' if r.esperado else 'negativo'} | {'sí' if r.disparo else 'no'} | "
                      f"**{r.clase}** | {'' if r.t_primera_alarma is None else f'{r.t_primera_alarma:.1f}'} | "
                      f"{r.frames} | {r.ms_por_frame:.1f} |")
    return "\n".join(lineas)


def escribir_en_pruebas(ruta: Path, marca: str, contenido: str) -> None:
    """Reemplaza el bloque entre <!-- marca:INICIO --> y <!-- marca:FIN --> (o lo agrega al final)."""
    inicio, fin = f"<!-- {marca}:INICIO -->", f"<!-- {marca}:FIN -->"
    texto = ruta.read_text(encoding="utf-8") if ruta.exists() else "# Pruebas\n"
    bloque = f"{inicio}\n{contenido}\n{fin}"
    if inicio in texto and fin in texto:
        texto = re.sub(re.escape(inicio) + r".*?" + re.escape(fin), lambda _: bloque, texto, flags=re.S)
    else:
        texto = texto.rstrip() + f"\n\n## Resultados: {marca}\n\n{bloque}\n"
    ruta.write_text(texto, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--detector", required=True, choices=sorted(TIPO_DE_DETECTOR))
    parser.add_argument("--carpeta", required=True, help="carpeta con subcarpetas positivos/ y negativos/")
    parser.add_argument("--zonas-de", default=None, help="usar las zonas dibujadas para esta cámara en el dashboard")
    parser.add_argument("--salida", default=str(RUTA_PRUEBAS), help="archivo Markdown donde escribir los resultados")
    parser.add_argument("--no-escribir", action="store_true", help="solo mostrar por consola")
    parser.add_argument("--bd", default=None, help="base de datos de donde leer zonas/residentes/ajustes "
                                                   "(por defecto la de config.yaml)")
    args = parser.parse_args(argv)
    from homeguard.logs import consola_utf8

    consola_utf8()
    logging.basicConfig(level=logging.WARNING)

    carpeta = Path(args.carpeta)
    if not carpeta.is_absolute():
        carpeta = RAIZ / carpeta
    videos = [(v, etiqueta == "positivos") for etiqueta in ("positivos", "negativos")
              for v in sorted((carpeta / etiqueta).glob("*")) if v.suffix.lower() in EXTENSIONES]
    if not videos:
        print(f"No hay videos en {carpeta}/positivos ni {carpeta}/negativos")
        return 1

    from homeguard.db import consultas
    from homeguard.db.sesion import BaseDatos

    bd = BaseDatos(args.bd or ruta_abs(cargar_config().general.base_datos))
    cfg, error = consultas.config_efectiva(bd, RUTA_CONFIG)
    if error:
        print(f"Aviso: se ignoran los cambios del dashboard porque son inválidos ({error})")
    cfg.detectores.puerta.horarios_permitidos = []  # la evaluación mide la detección, no el horario

    analizador = Analizador(Modelos(cfg.procesamiento.hilos_torch))
    if args.detector == "rostros":
        matriz, nombres = consultas.embeddings_residentes(bd)
        analizador.detectores["rostros"].fijar_residentes(matriz, nombres)
        print(f"Residentes cargados: {len(set(nombres))} ({len(nombres)} vectores)")
    zonas_bd: list[Zona] = []
    if args.zonas_de:
        zonas_bd = consultas.zonas_de_camara(bd, args.zonas_de)
        print(f"Zonas de '{args.zonas_de}': {[z.nombre for z in zonas_bd]}")

    resultados = []
    for video, esperado in videos:
        r = evaluar_video(video, esperado, args.detector, cfg, analizador, zonas_para(video, args.detector, zonas_bd))
        resultados.append(r)
        print(f"  {r.clase}  {video.parent.name}/{video.name}  (alarma: {r.t_primera_alarma})")
    m = metricas(resultados)
    print(f"VP={m['VP']} FP={m['FP']} VN={m['VN']} FN={m['FN']}  precisión={m['precision']:.2f} "
          f"recall={m['recall']:.2f} F1={m['f1']:.2f}")
    if not args.no_escribir:
        escribir_en_pruebas(Path(args.salida), args.detector, tabla_markdown(args.detector, carpeta, resultados, m))
        print(f"Resultados escritos en {args.salida}")
    bd.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
