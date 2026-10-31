"""Fase 7 (opcional): XOR y AND con SIMD escrito en C (nativo/bitwise_simd.c), cargado con ctypes.

Si la librería no está compilada, `disponible()` devuelve False y el resto del sistema
sigue igual: nada de HomeGuard depende de este módulo, solo el benchmark (variante E)
y tests/test_nativo.py. Para compilarla: nativo/compilar.bat (Windows) o nativo/compilar.sh.

Uso:
    from homeguard.preproceso import nativo
    if nativo.disponible():
        dif = nativo.xor(gris_anterior, gris_actual)     # = cv2.bitwise_xor
        print(nativo.nivel())                            # "AVX2", "SSE2" o "escalar"
"""
from __future__ import annotations

import ctypes
import logging
import sys

import numpy as np

from homeguard.config import RAIZ

log = logging.getLogger(__name__)

CARPETA = RAIZ / "nativo"
NIVELES = {0: "escalar", 1: "SSE2", 2: "AVX2"}

if sys.platform == "win32":
    _NOMBRES = ["bitwise_simd.dll"]
elif sys.platform == "darwin":
    _NOMBRES = ["libbitwise_simd.dylib"]
else:
    _NOMBRES = ["libbitwise_simd.so"]

_lib: ctypes.CDLL | None = None
_cargada = False


def _cargar() -> ctypes.CDLL | None:
    """Carga la librería una sola vez; None si no existe o no se puede cargar."""
    global _lib, _cargada
    if _cargada:
        return _lib
    _cargada = True
    for nombre in _NOMBRES:
        ruta = CARPETA / nombre
        if not ruta.exists():
            continue
        try:
            lib = ctypes.CDLL(str(ruta))
        except OSError as e:  # por ejemplo, una DLL de 32 bits con Python de 64
            log.warning("No se pudo cargar %s: %s", ruta, e)
            continue
        p = ctypes.c_void_p
        for funcion, argumentos in (("hg_xor", [p, p, p, ctypes.c_size_t]),
                                    ("hg_and", [p, p, p, ctypes.c_size_t]),
                                    ("hg_xor_and", [p, p, p, p, ctypes.c_size_t])):
            getattr(lib, funcion).argtypes = argumentos
            getattr(lib, funcion).restype = None
        for funcion in ("hg_nivel", "hg_nivel_detectado"):
            getattr(lib, funcion).argtypes = []
            getattr(lib, funcion).restype = ctypes.c_int
        lib.hg_forzar_nivel.argtypes = [ctypes.c_int]
        lib.hg_forzar_nivel.restype = ctypes.c_int
        _lib = lib
        log.info("Librería SIMD cargada: %s (nivel %s)", ruta.name, NIVELES.get(lib.hg_nivel(), "?"))
        break
    return _lib


def disponible() -> bool:
    """True si nativo/bitwise_simd.(dll|so|dylib) está compilada y se pudo cargar."""
    return _cargar() is not None


def _requerir() -> ctypes.CDLL:
    lib = _cargar()
    if lib is None:
        raise RuntimeError("La librería SIMD no está compilada: ejecutá nativo/compilar.bat o nativo/compilar.sh")
    return lib


def nivel() -> str:
    """Nivel de instrucciones en uso: "AVX2", "SSE2" o "escalar"."""
    return NIVELES[_requerir().hg_nivel()]


def nivel_detectado() -> str:
    """Lo máximo que soporta esta CPU."""
    return NIVELES[_requerir().hg_nivel_detectado()]


def forzar_nivel(k: int | None) -> str:
    """Usa como máximo el nivel k (0 escalar, 1 SSE2, 2 AVX2); None vuelve a lo detectado."""
    return NIVELES[_requerir().hg_forzar_nivel(-1 if k is None else k)]


def validar(*arrays: np.ndarray, salida: np.ndarray | None = None) -> np.ndarray:
    """Comprueba que todos sean uint8, contiguos y de la misma forma; devuelve el array de salida.

    El código C recorre la memoria como n bytes seguidos: un array no contiguo (por ejemplo un
    recorte frame[y0:y1, x0:x1]) tiene "huecos" entre filas y daría un resultado incorrecto.
    """
    forma = arrays[0].shape
    for a in arrays:
        if not isinstance(a, np.ndarray) or a.dtype != np.uint8:
            raise TypeError("se esperaba un np.ndarray uint8")
        if a.shape != forma:
            raise ValueError(f"formas distintas: {a.shape} y {forma}")
        if not a.flags.c_contiguous:
            raise ValueError("el array no es contiguo: usá np.ascontiguousarray(...)")
    if salida is None:
        return np.empty(forma, np.uint8)
    if salida.dtype != np.uint8 or salida.shape != forma or not salida.flags.c_contiguous \
            or not salida.flags.writeable:
        raise ValueError("salida tiene que ser uint8, contigua, escribible y de la misma forma")
    return salida


def xor(a: np.ndarray, b: np.ndarray, salida: np.ndarray | None = None) -> np.ndarray:
    """a XOR b (mismo resultado que cv2.bitwise_xor)."""
    lib = _requerir()
    s = validar(a, b, salida=salida)
    lib.hg_xor(a.ctypes.data, b.ctypes.data, s.ctypes.data, a.size)
    return s


def and_(a: np.ndarray, b: np.ndarray, salida: np.ndarray | None = None) -> np.ndarray:
    """a AND b (mismo resultado que cv2.bitwise_and)."""
    lib = _requerir()
    s = validar(a, b, salida=salida)
    lib.hg_and(a.ctypes.data, b.ctypes.data, s.ctypes.data, a.size)
    return s


def xor_and(a: np.ndarray, b: np.ndarray, mascara: np.ndarray, salida: np.ndarray | None = None) -> np.ndarray:
    """(a XOR b) AND mascara: lo que cambió entre a y b, solo dentro de la máscara."""
    lib = _requerir()
    s = validar(a, b, mascara, salida=salida)
    lib.hg_xor_and(a.ctypes.data, b.ctypes.data, mascara.ctypes.data, s.ctypes.data, a.size)
    return s
