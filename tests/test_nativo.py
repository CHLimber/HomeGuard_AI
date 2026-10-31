"""Fase 7: librería SIMD en C (nativo/bitwise_simd.c) cargada con ctypes.

Los tests contra la librería real se saltan si no está compilada. Los demás usan una
librería falsa en Python con la misma interfaz (hg_xor, hg_and, ...) para probar el
paso de punteros del wrapper y la variante E del benchmark sin compilador.
"""
import ctypes

import cv2
import numpy as np
import pytest

from homeguard.preproceso import nativo

requiere_lib = pytest.mark.skipif(not nativo.disponible(), reason="nativo/bitwise_simd no está compilada")

# tamaños que no son múltiplos de 16 (SSE2) ni de 32 (AVX2): ejercitan la cola escalar
FORMAS = [(1,), (15,), (17,), (31,), (33,), (7, 13), (480, 641), (3, 5, 3)]


def _aleatorios(forma, n, semilla=0):
    rng = np.random.default_rng(semilla)
    return [rng.integers(0, 256, forma, dtype=np.uint8) for _ in range(n)]


@requiere_lib
@pytest.mark.parametrize("nivel", [0, 1, 2])
@pytest.mark.parametrize("forma", FORMAS)
def test_igual_que_opencv(nivel, forma):
    a, b, m = _aleatorios(forma, 3)
    try:
        nativo.forzar_nivel(nivel)  # si la CPU no llega a ese nivel, usa el máximo que tiene
        assert np.array_equal(nativo.xor(a, b), cv2.bitwise_xor(a, b))
        assert np.array_equal(nativo.and_(a, b), cv2.bitwise_and(a, b))
        assert np.array_equal(nativo.xor_and(a, b, m), cv2.bitwise_and(cv2.bitwise_xor(a, b), m))
    finally:
        nativo.forzar_nivel(None)


@requiere_lib
def test_nivel_y_salida_en_el_lugar():
    assert nativo.nivel() in ("escalar", "SSE2", "AVX2")
    a, b = _aleatorios((100,), 2, semilla=1)
    esperado = cv2.bitwise_and(a, b)
    nativo.and_(a, b, salida=a)  # puede escribir sobre una de las entradas
    assert np.array_equal(a, esperado)


def test_validar_rechaza_arrays_incorrectos():
    a = np.zeros((4, 4), np.uint8)
    with pytest.raises(TypeError):
        nativo.validar(a, a.astype(np.int16))
    with pytest.raises(ValueError):
        nativo.validar(a, np.zeros((4, 5), np.uint8))
    with pytest.raises(ValueError):  # recorte no contiguo
        nativo.validar(a[:, :2], a[:, 2:])
    with pytest.raises(ValueError):
        nativo.validar(a, a, salida=np.zeros((4, 4), np.int32))
    assert nativo.validar(a, a).shape == (4, 4)


# ---------------------------------------------------------------------------
# Librería falsa: misma interfaz que bitwise_simd.c, implementada con NumPy
# ---------------------------------------------------------------------------

def _vista(direccion: int, n: int) -> np.ndarray:
    return np.ctypeslib.as_array((ctypes.c_uint8 * n).from_address(direccion)) if n else np.empty(0, np.uint8)


class _LibFalsa:
    def hg_xor(self, a, b, s, n):
        _vista(s, n)[:] = _vista(a, n) ^ _vista(b, n)

    def hg_and(self, a, b, s, n):
        _vista(s, n)[:] = _vista(a, n) & _vista(b, n)

    def hg_xor_and(self, a, b, m, s, n):
        _vista(s, n)[:] = (_vista(a, n) ^ _vista(b, n)) & _vista(m, n)

    def hg_nivel(self):
        return 2


@pytest.fixture
def lib_falsa(monkeypatch):
    monkeypatch.setattr(nativo, "_lib", _LibFalsa())
    monkeypatch.setattr(nativo, "_cargada", True)


def test_wrapper_pasa_bien_los_punteros(lib_falsa):
    a, b, m = _aleatorios((37, 23), 3, semilla=2)
    assert np.array_equal(nativo.xor(a, b), a ^ b)
    assert np.array_equal(nativo.and_(a, b), a & b)
    assert np.array_equal(nativo.xor_and(a, b, m), (a ^ b) & m)
    assert nativo.nivel() == "AVX2"


def test_sin_libreria_no_rompe(monkeypatch):
    monkeypatch.setattr(nativo, "_lib", None)
    monkeypatch.setattr(nativo, "_cargada", True)
    assert nativo.disponible() is False
    with pytest.raises(RuntimeError):
        nativo.xor(np.zeros(4, np.uint8), np.zeros(4, np.uint8))


def test_benchmark_omite_e_sin_libreria(monkeypatch, tmp_path):
    from homeguard.preproceso import benchmark as bm

    monkeypatch.setattr(nativo, "_lib", None)
    monkeypatch.setattr(nativo, "_cargada", True)
    filas = bm.ejecutar(repeticiones=1, frames_python=1, ancho=160, carpeta_salida=tmp_path)
    assert [f["variante"] for f in filas] == ["A", "B", "B2", "C", "D"]


def test_benchmark_variante_e_igual_a_d(lib_falsa, tmp_path):
    from homeguard.preproceso import benchmark as bm

    filas = bm.ejecutar(repeticiones=1, frames_python=1, ancho=160, carpeta_salida=tmp_path)
    res = {f["variante"]: f["porcentaje_resultado"] for f in filas}
    assert res["E"] == res["D"] == res["A"]
    assert "| E |" in (tmp_path / "BENCHMARK.md").read_text(encoding="utf-8")
