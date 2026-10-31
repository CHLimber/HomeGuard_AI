"""Byte de estado de la alarma.

Cada anomalía ocupa un bit de un único entero de 8 bits. El panel web
decodifica el mismo byte en JavaScript con `estado & (1 << n)`.

    bit:     7 6 5 4 3 2 1 0
                   │ │ │ │ └─ INTRUSION
                   │ │ │ └─── PISCINA
                   │ │ └───── FUEGO
                   │ └─────── CAIDA
                   └───────── PUERTA

Ejemplo: fuego + puerta = 0b0001_0100 = 20.
"""
from __future__ import annotations

# Informe, ecuación del byte de estado y Anexo A: bit n = 1 << n
INTRUSION = 1 << 0  # 1
PISCINA = 1 << 1    # 2
FUEGO = 1 << 2      # 4
CAIDA = 1 << 3      # 8
PUERTA = 1 << 4     # 16

# nombre de anomalía -> número de bit (mismo orden que usa el panel)
BIT_POR_TIPO: dict[str, int] = {"intrusion": 0, "piscina": 1, "fuego": 2, "caida": 3, "puerta": 4}
MASCARA_POR_TIPO: dict[str, int] = {tipo: 1 << bit for tipo, bit in BIT_POR_TIPO.items()}
TODAS = INTRUSION | PISCINA | FUEGO | CAIDA | PUERTA  # 0b11111 = 31


def activar(estado: int, tipo: str) -> int:
    """Enciende el bit de la anomalía (OR)."""
    return (estado | MASCARA_POR_TIPO[tipo]) & 0xFF


def desactivar(estado: int, tipo: str) -> int:
    """Apaga el bit de la anomalía (AND con el complemento)."""
    return estado & ~MASCARA_POR_TIPO[tipo] & 0xFF


def esta_activo(estado: int, tipo: str) -> bool:
    """Consulta el bit de la anomalía (AND)."""
    return bool(estado & MASCARA_POR_TIPO[tipo])


def codificar(tipos: list[str] | set[str]) -> int:
    """Lista de anomalías -> byte."""
    estado = 0
    for t in tipos:
        estado = activar(estado, t)
    return estado


def decodificar(estado: int) -> list[str]:
    """Byte -> lista de anomalías activas (en orden de bit)."""
    return [tipo for tipo, bit in BIT_POR_TIPO.items() if (estado >> bit) & 1]
