from homeguard.reglas import estado as est


def test_constantes_son_bits_distintos():
    assert [est.INTRUSION, est.PISCINA, est.FUEGO, est.CAIDA, est.PUERTA] == [1, 2, 4, 8, 16]
    assert est.TODAS == 0b11111


def test_codificar_y_decodificar():
    byte = est.codificar(["fuego", "puerta"])
    assert byte == 0b10100 == 20
    assert est.decodificar(byte) == ["fuego", "puerta"]
    assert est.decodificar(0) == []
    assert est.decodificar(est.TODAS) == ["intrusion", "piscina", "fuego", "caida", "puerta"]


def test_activar_desactivar_consultar():
    e = est.activar(0, "caida")
    assert e == 8 and est.esta_activo(e, "caida") and not est.esta_activo(e, "fuego")
    e = est.activar(e, "intrusion")
    assert e == 9
    e = est.desactivar(e, "caida")
    assert e == 1
    assert est.desactivar(e, "caida") == 1  # apagar un bit apagado no cambia nada


def test_decodificacion_igual_a_javascript():
    # el panel hace (estado & (1 << n)) !== 0
    byte = est.codificar(["piscina", "puerta"])
    js = [(byte & (1 << n)) != 0 for n in range(5)]
    assert js == [False, True, False, False, True]
