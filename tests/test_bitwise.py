"""Funciones bitwise con resultados conocidos sobre matrices pequeñas."""
import cv2
import numpy as np

from homeguard.preproceso import bitwise as bw


def test_aplicar_mascara_and():
    img = np.array([[10, 20], [30, 40]], np.uint8)
    mascara = np.array([[255, 0], [0, 255]], np.uint8)
    assert bw.aplicar_mascara(img, mascara).tolist() == [[10, 0], [0, 40]]
    color = np.dstack([img, img, img])
    assert bw.aplicar_mascara(color, mascara)[:, :, 2].tolist() == [[10, 0], [0, 40]]


def test_combinar_mascaras():
    a = np.array([[255, 255, 0, 0]], np.uint8)
    b = np.array([[255, 0, 255, 0]], np.uint8)
    assert bw.combinar_mascaras(a, b, modo="and").tolist() == [[255, 0, 0, 0]]
    assert bw.combinar_mascaras(a, b, modo="or").tolist() == [[255, 255, 255, 0]]
    assert bw.combinar_mascaras(a, b, modo="xor").tolist() == [[0, 255, 255, 0]]


def test_mascara_bits_altos():
    assert bw.mascara_bits_altos(4) == 0b1111_0000
    assert bw.mascara_bits_altos(3) == 0b1110_0000
    assert bw.mascara_bits_altos(8) == 0xFF


def test_cuantizar_and_igual_a_desplazamientos():
    img = np.array([[182, 15, 255, 0, 128]], np.uint8)
    assert bw.cuantizar(img, 4).tolist() == [[176, 0, 240, 0, 128]]  # 0b1011_0110 -> 0b1011_0000
    rng = np.random.default_rng(1)
    grande = rng.integers(0, 256, (40, 50), dtype=np.uint8)
    for bits in range(1, 9):
        assert np.array_equal(bw.cuantizar(grande, bits), bw.cuantizar_desplazando(grande, bits))


def test_movimiento_xor_ignora_ruido_y_detecta_cambio():
    anterior = np.full((6, 6), 100, np.uint8)          # 0b0110_0100
    actual = anterior.copy()
    actual[0, 0] = 103                                 # ruido: 0b0110_0111, mismos 4 bits altos
    actual[2:5, 2:5] = 200                             # cambio real: 0b1100_1000
    m = bw.mascara_movimiento_xor(anterior, actual, bits=4, apertura_px=0)
    assert m[0, 0] == 0
    assert m[2:5, 2:5].tolist() == [[255] * 3] * 3
    assert int(m.sum()) // 255 == 9
    # con apertura 3x3 el bloque de 3x3 sobrevive y un píxel suelto no
    actual[0, 5] = 250
    m = bw.mascara_movimiento_xor(anterior, actual, bits=4, apertura_px=3)
    assert m[0, 5] == 0 and m[3, 3] == 255


def test_binarizar_y_xor():
    a = bw.binarizar(np.array([[10, 200], [90, 160]], np.uint8), umbral=127)
    b = bw.binarizar(np.array([[10, 10], [200, 160]], np.uint8), umbral=127)
    assert a.tolist() == [[0, 255], [0, 255]]
    assert bw.xor_binarizadas(a, b).tolist() == [[0, 255], [255, 0]]


def test_indice_rgb332():
    naranja = np.array([[[0, 140, 255]]], np.uint8)        # BGR
    assert int(bw.indice_rgb332(naranja)[0, 0]) == 240       # 224 | 16 | 0
    blanco = np.array([[[255, 255, 255]]], np.uint8)
    assert int(bw.indice_rgb332(blanco)[0, 0]) == 0xFF
    azul = np.array([[[255, 0, 0]]], np.uint8)
    assert int(bw.indice_rgb332(azul)[0, 0]) == 0b11


def test_lut_fuego_clasifica_colores():
    lut = bw.construir_lut_fuego(hue_min=0, hue_max=35, sat_min=100, val_min=150)
    assert lut.shape == (256,) and lut.dtype == np.uint8
    pixeles = np.array([[[0, 140, 255], [0, 220, 255], [255, 0, 0], [0, 200, 0], [128, 128, 128], [0, 0, 40]]],
                       np.uint8)  # naranja, amarillo, azul, verde, gris, rojo oscuro
    assert bw.mascara_color_lut(pixeles, lut)[0].tolist() == [255, 255, 0, 0, 0, 0]


def test_lut_coincide_con_hsv_en_colores_centrales():
    """La LUT da lo mismo que evaluar la regla HSV sobre el color central de cada celda."""
    lut = bw.construir_lut_fuego(0, 35, 100, 150)
    idx = np.arange(256)
    centros = np.stack([((idx & 3) << 6) + 32, ((idx & 0x1C) << 3) + 16, (idx & 0xE0) + 16], -1).astype(np.uint8)
    centros = centros.reshape(1, 256, 3)
    hsv = cv2.inRange(cv2.cvtColor(centros, cv2.COLOR_BGR2HSV), (0, 100, 150), (35, 255, 255))
    assert np.array_equal(bw.mascara_color_lut(centros, lut)[0], hsv[0])


def test_porcentaje_activos():
    m = np.zeros((10, 10), np.uint8)
    m[:5, :] = 255
    assert bw.porcentaje_activos(m) == 50.0
    roi = np.zeros((10, 10), np.uint8)
    roi[:, :2] = 255                  # 20 píxeles de ROI, 10 activos
    assert bw.porcentaje_activos(m, roi) == 50.0
    assert bw.porcentaje_activos(m, np.zeros_like(m)) == 0.0


def test_mascara_poligono_y_roi():
    m = bw.mascara_poligono(10, 10, [[2, 2], [5, 2], [5, 5], [2, 5]])
    assert int(m.sum()) // 255 == 16  # cuadrado de 4x4 (bordes incluidos)
    u = bw.mascara_roi(10, 10, [[[0, 0], [1, 0], [1, 1], [0, 1]], [[8, 8], [9, 8], [9, 9], [8, 9]]])
    assert int(u.sum()) // 255 == 8   # OR de dos cuadrados de 2x2
    assert bw.bbox_poligono([[2, 2], [5, 2], [5, 5], [2, 5]], 10, 10) == (2, 2, 6, 6)


def test_benchmark_variantes_coinciden(tmp_path):
    """El bucle Python y las versiones vectorizadas con bits dan exactamente el mismo resultado."""
    from homeguard.preproceso import benchmark as bm

    filas = bm.ejecutar(repeticiones=2, frames_python=1, ancho=160, carpeta_salida=tmp_path)
    res = {f["variante"]: f["porcentaje_resultado"] for f in filas}
    assert res["A"] == res["C"] == res["D"]
    assert (tmp_path / "BENCHMARK.md").exists() and (tmp_path / "benchmark.csv").exists()
