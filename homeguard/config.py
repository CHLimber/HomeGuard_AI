"""Carga y validación de la configuración.

La configuración efectiva se arma en tres capas:
  1. config.yaml (comentado, es la referencia de todos los umbrales)
  2. overrides guardados en la BD desde el dashboard (claves con puntos,
     ej. "detectores.puerta.porcentaje_min" -> 30)
  3. secretos del archivo .env (token y chat de Telegram)

Todo se valida con pydantic: un valor mal escrito en config.yaml hace fallar el
arranque con un mensaje claro en lugar de romper en plena demo.
"""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config.yaml"

TIPOS_ANOMALIA = ("intrusion", "piscina", "fuego", "caida", "puerta")
TIPOS_ZONA = ("acceso", "piscina", "borde_piscina", "puerta", "fuego")
NOMBRES_DETECTOR = ("rostros", "piscina", "fuego", "caidas", "puerta")


class _Base(BaseModel):
    # extra="forbid": una clave mal escrita en config.yaml es un error, no se ignora
    model_config = ConfigDict(extra="forbid")


class CfgServidor(_Base):
    host: str = "0.0.0.0"
    puerto: int = 8000


class CfgGeneral(_Base):
    base_datos: str = "data/homeguard.db"
    carpeta_eventos: str = "data/eventos"
    carpeta_referencias: str = "data/referencias"
    carpeta_pruebas: str = "data/pruebas"
    max_mb_prueba: float = Field(500, gt=0)
    archivo_log: str = "data/homeguard.log"
    nivel_log: str = "INFO"


class CfgProcesamiento(_Base):
    ancho_proceso: int = Field(640, ge=160, le=1920)
    fps_objetivo: float = Field(10, gt=0, le=60)
    hilos_torch: int = Field(4, ge=1)
    imgsz_yolo: int = Field(480, ge=160, le=1280)
    fps_stream: float = Field(10, gt=0, le=30)
    calidad_jpeg_stream: int = Field(70, ge=10, le=100)
    intervalo_telemetria_s: float = Field(0.5, gt=0)
    precargar_modelos: bool = True


class CfgCaptura(_Base):
    reintento_inicial_s: float = Field(1.0, gt=0)
    reintento_max_s: float = Field(15.0, gt=0)
    timeout_sin_frames_s: float = Field(5.0, gt=0)


class CfgPreproceso(_Base):
    bits_movimiento: int = Field(4, ge=1, le=8)
    apertura_movimiento_px: int = Field(3, ge=0)


class CfgCamara(_Base):
    nombre: str
    fuente: int | str
    activa: bool = True
    segundos_por_imagen: float = Field(3.0, gt=0)
    detectores: list[Literal["rostros", "piscina", "fuego", "caidas", "puerta"]] = Field(default_factory=list)


class CfgAlarma(_Base):
    votos_n: int = Field(ge=1)
    votos_m: int = Field(ge=1)
    cooldown_s: float = Field(ge=0)

    @field_validator("votos_m")
    @classmethod
    def _m_mayor_igual_n(cls, m: int, info: Any) -> int:
        n = info.data.get("votos_n", 1)
        if m < n:
            raise ValueError(f"votos_m ({m}) debe ser >= votos_n ({n})")
        return m


class CfgAlarmas(_Base):
    intrusion: CfgAlarma
    piscina: CfgAlarma
    fuego: CfgAlarma
    caida: CfgAlarma
    puerta: CfgAlarma


class CfgMotor(_Base):
    auto_limpiar_s: float = Field(0, ge=0)


class CfgYoloGeneral(_Base):
    modelo: str = "models/yolov8n.pt"
    confianza: float = Field(0.4, ge=0, le=1)
    clases: list[int] = Field(default_factory=lambda: [0, 15, 16])


class CfgRostros(_Base):
    modelo_detector: str
    modelo_reconocedor: str
    umbral_similitud: float = Field(0.363, ge=-1, le=1)
    confianza_rostro: float = Field(0.9, ge=0, le=1)
    nms: float = Field(0.3, ge=0, le=1)
    tamano_min_rostro_px: int = Field(40, ge=0)
    usar_resolucion_original: bool = True
    exigir_persona_yolo: bool = True


class CfgPiscina(_Base):
    tiempo_sin_supervisor_s: float = Field(2.0, ge=0)
    inmovil_desplazamiento_px: float = Field(15, ge=0)
    inmovil_tiempo_s: float = Field(8.0, gt=0)
    olvidar_track_s: float = Field(3.0, gt=0)


class CfgFuego(_Base):
    modelo: str
    hue_min: int = Field(0, ge=0, le=180)
    hue_max: int = Field(35, ge=0, le=180)
    sat_min: int = Field(100, ge=0, le=255)
    val_min: int = Field(150, ge=0, le=255)
    modo_capa1: Literal["lut332", "lut9", "hsv"] = "lut9"
    lut_archivo: str = ""
    umbral_capa1_pct: float = Field(0.5, ge=0, le=100)
    confianza_capa2: float = Field(0.5, ge=0, le=1)
    clases_capa2: list[int] = Field(default_factory=lambda: [0, 1])


class CfgCaidas(_Base):
    modelo: str
    confianza: float = Field(0.25, ge=0, le=1)
    imgsz: int = Field(640, ge=0)
    cada_n_frames: int = Field(2, ge=1)
    confianza_keypoint: float = Field(0.5, ge=0, le=1)
    ratio_min: float = Field(1.4, gt=0)
    angulo_max_grados: float = Field(45, ge=0, le=90)
    ventana_descenso_s: float = Field(1.0, gt=0)
    descenso_min_relativo: float = Field(0.25, ge=0)
    radio_asociacion_px: float = Field(120, gt=0)
    inmovil_desplazamiento_px: float = Field(20, ge=0)
    inmovil_desplazamiento_relativo: float = Field(0.15, ge=0)
    levantarse_relativo: float = Field(0.25, ge=0)
    inmovil_tiempo_s: float = Field(3.0, ge=0)
    olvidar_tras_s: float = Field(6.0, gt=0)


class CfgPuerta(_Base):
    metodo: Literal["absdiff", "xor"] = "absdiff"
    umbral_diferencia: int = Field(30, ge=1, le=255)
    umbral_binarizacion: int = Field(0, ge=0, le=255)
    desenfoque_px: int = Field(5, ge=0)
    porcentaje_min: float = Field(25.0, ge=0, le=100)
    duracion_min_s: float = Field(2.0, ge=0)
    horarios_permitidos: list[str] = Field(default_factory=list)
    referencia_automatica: bool = True

    @field_validator("horarios_permitidos")
    @classmethod
    def _formato_horario(cls, rangos: list[str]) -> list[str]:
        for r in rangos:
            if not re.fullmatch(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}", r.strip()):
                raise ValueError(f"horario inválido '{r}', se espera 'HH:MM-HH:MM'")
        return [r.strip() for r in rangos]


class CfgDetectores(_Base):
    rostros: CfgRostros
    piscina: CfgPiscina
    fuego: CfgFuego
    caidas: CfgCaidas
    puerta: CfgPuerta


class CfgTelegram(_Base):
    activo: bool = True
    ancho_foto: int = Field(640, ge=160)
    calidad_jpeg: int = Field(70, ge=10, le=100)
    timeout_s: float = Field(5, gt=0)
    reintento_max_s: float = Field(60, gt=0)
    descartar_tras_min: float = Field(120, gt=0)


class CfgPanel(_Base):
    latencia_objetivo_ms: float = Field(2000, gt=0)


class CfgZonaDemo(_Base):
    camara: str
    nombre: str
    tipo: Literal["acceso", "piscina", "borde_piscina", "puerta", "fuego"]
    puntos: list[list[float]]


class CfgDemo(_Base):
    base_datos: str = "data/homeguard_demo.db"
    camaras: dict[str, CfgCamara] = Field(default_factory=dict)
    zonas: list[CfgZonaDemo] = Field(default_factory=list)


class Config(_Base):
    servidor: CfgServidor = Field(default_factory=CfgServidor)
    general: CfgGeneral = Field(default_factory=CfgGeneral)
    procesamiento: CfgProcesamiento = Field(default_factory=CfgProcesamiento)
    captura: CfgCaptura = Field(default_factory=CfgCaptura)
    preproceso: CfgPreproceso = Field(default_factory=CfgPreproceso)
    camaras: dict[str, CfgCamara] = Field(default_factory=dict)
    alarmas: CfgAlarmas
    motor: CfgMotor = Field(default_factory=CfgMotor)
    yolo_general: CfgYoloGeneral = Field(default_factory=CfgYoloGeneral)
    detectores: CfgDetectores
    telegram: CfgTelegram = Field(default_factory=CfgTelegram)
    panel: CfgPanel = Field(default_factory=CfgPanel)
    demo: CfgDemo = Field(default_factory=CfgDemo)


class Secretos(BaseModel):
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @property
    def telegram_configurado(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


# ---------------------------------------------------------------------------
# Funciones de carga
# ---------------------------------------------------------------------------

def ruta_abs(ruta: str | Path) -> Path:
    """Convierte una ruta relativa del config en absoluta respecto de la raíz del proyecto."""
    p = Path(ruta)
    return p if p.is_absolute() else RAIZ / p


def cargar_yaml(ruta: str | Path = RUTA_CONFIG) -> dict[str, Any]:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def aplicar_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Aplica overrides con claves de puntos ('a.b.c': valor) sobre una copia del dict."""
    resultado = copy.deepcopy(base)
    for clave, valor in overrides.items():
        partes = clave.split(".")
        nodo = resultado
        for p in partes[:-1]:
            if not isinstance(nodo.get(p), dict):
                nodo[p] = {}
            nodo = nodo[p]
        nodo[partes[-1]] = valor
    return resultado


def aplanar(d: dict[str, Any], prefijo: str = "") -> dict[str, Any]:
    """Inverso de aplicar_overrides: {'a': {'b': 1}} -> {'a.b': 1}."""
    plano: dict[str, Any] = {}
    for k, v in d.items():
        clave = f"{prefijo}{k}"
        if isinstance(v, dict):
            plano.update(aplanar(v, clave + "."))
        else:
            plano[clave] = v
    return plano


def construir_config(datos: dict[str, Any], demo: bool = False) -> Config:
    """Valida un dict y devuelve Config. En modo demo reemplaza cámaras y BD por las de 'demo'."""
    cfg = Config.model_validate(datos)
    if demo:
        cfg.camaras = dict(cfg.demo.camaras)
        cfg.general.base_datos = cfg.demo.base_datos
    return cfg


def cargar_config(
    ruta: str | Path = RUTA_CONFIG,
    overrides: dict[str, Any] | None = None,
    demo: bool = False,
) -> Config:
    datos = cargar_yaml(ruta)
    if overrides:
        datos = aplicar_overrides(datos, overrides)
    return construir_config(datos, demo=demo)


def leer_comentarios(ruta: str | Path = RUTA_CONFIG) -> dict[str, str]:
    """Comentarios al final de cada línea de config.yaml, por clave con puntos (los usa el dashboard)."""
    comentarios: dict[str, str] = {}
    pila: list[tuple[int, str]] = []  # (indentación, clave)
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            m = re.match(r"^(\s*)([A-Za-z_]\w*)\s*:(.*)$", linea.rstrip("\n"))
            if not m:
                continue
            sangria, clave, resto = len(m.group(1)), m.group(2), m.group(3)
            while pila and pila[-1][0] >= sangria:
                pila.pop()
            ruta_clave = ".".join([c for _, c in pila] + [clave])
            if "#" in resto:
                comentarios[ruta_clave] = resto.split("#", 1)[1].strip()
            if resto.split("#", 1)[0].strip() == "":  # la clave abre un bloque
                pila.append((sangria, clave))
    return comentarios


def cargar_secretos() -> Secretos:
    load_dotenv(RAIZ / ".env")
    return Secretos(
        telegram_token=os.getenv("TELEGRAM_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )
