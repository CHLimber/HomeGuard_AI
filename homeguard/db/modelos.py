"""Modelos de la base de datos (SQLAlchemy 2.0, SQLite).

Por privacidad, de los residentes se guarda solo el vector del rostro
(embedding SFace de 128 floats), nunca las fotos.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _ahora() -> datetime:
    return datetime.now()


class Residente(Base):
    __tablename__ = "residente"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    embeddings: Mapped[list[EmbeddingRostro]] = relationship(
        back_populates="residente", cascade="all, delete-orphan")


class EmbeddingRostro(Base):
    __tablename__ = "embedding_rostro"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    residente_id: Mapped[int] = mapped_column(ForeignKey("residente.id", ondelete="CASCADE"))
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32 x 128, normalizado (norma 1)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    residente: Mapped[Residente] = relationship(back_populates="embeddings")

    @staticmethod
    def a_bytes(vector: np.ndarray) -> bytes:
        return np.asarray(vector, dtype=np.float32).ravel().tobytes()

    def como_array(self) -> np.ndarray:
        return np.frombuffer(self.vector, dtype=np.float32)


class Camara(Base):
    """Espejo de las cámaras de la config (sirve de referencia para zonas y eventos)."""
    __tablename__ = "camara"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    fuente: Mapped[str] = mapped_column(String(300))


class Zona(Base):
    __tablename__ = "zona"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camara_id: Mapped[str] = mapped_column(String(50), index=True)
    nombre: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(20))           # acceso, piscina, borde_piscina, puerta, fuego
    puntos: Mapped[list] = mapped_column(JSON)               # [[x, y], ...] normalizados 0-1
    referencia: Mapped[str | None] = mapped_column(String(300), nullable=True)  # imagen de puerta cerrada
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)


class MedioPrueba(Base):
    """Video o serie de imágenes subidos en "Prueba con video": se analizan como una cámara más."""
    __tablename__ = "medio_prueba"
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(10))                 # "video" o "imagenes"
    ruta: Mapped[str] = mapped_column(String(300))                # archivo de video o carpeta de imágenes
    detectores: Mapped[list] = mapped_column(JSON)
    segundos_por_imagen: Mapped[float] = mapped_column(Float, default=3.0)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)


class ConfigOverride(Base):
    """Valores de config.yaml cambiados desde el dashboard (clave con puntos -> valor JSON)."""
    __tablename__ = "config"
    clave: Mapped[str] = mapped_column(String(200), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSON)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, onupdate=_ahora)


class Evento(Base):
    __tablename__ = "evento"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    tipo: Mapped[str] = mapped_column(String(20), index=True)
    camara_id: Mapped[str] = mapped_column(String(50), index=True)
    zona: Mapped[str] = mapped_column(String(100))
    confianza: Mapped[float] = mapped_column(Float, default=0.0)
    detalle: Mapped[dict] = mapped_column(JSON, default=dict)
    foto: Mapped[str | None] = mapped_column(String(300), nullable=True)  # nombre de archivo en carpeta_eventos
    t_deteccion: Mapped[float] = mapped_column(Float)            # epoch (s) en que el motor confirmó la alarma
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, index=True)
    latencia_panel_ms: Mapped[float | None] = mapped_column(Float, nullable=True)     # detección -> ack del panel
    latencia_telegram_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # detección -> Telegram OK
    telegram_estado: Mapped[str] = mapped_column(String(20), default="pendiente")     # pendiente/enviado/error/desactivado
    silenciado: Mapped[bool] = mapped_column(Boolean, default=False)

    def a_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "tipo": self.tipo, "camara_id": self.camara_id, "zona": self.zona,
            "confianza": round(self.confianza or 0.0, 3), "detalle": self.detalle or {},
            "foto": f"/fotos/{self.foto}" if self.foto else None,
            "t_deteccion": self.t_deteccion, "creado_en": self.creado_en.isoformat(timespec="seconds"),
            "latencia_panel_ms": None if self.latencia_panel_ms is None else round(self.latencia_panel_ms, 1),
            "latencia_telegram_ms": None if self.latencia_telegram_ms is None else round(self.latencia_telegram_ms, 1),
            "telegram_estado": self.telegram_estado, "silenciado": self.silenciado,
        }
