"""La anomalía "piscina" se quitó: una BD anterior con sus overrides, zonas o medios de prueba no debe romper nada."""
from homeguard.config import cargar_config
from homeguard.db import consultas
from homeguard.db import modelos as m


def test_overrides_de_piscina_se_descartan_y_los_demas_se_conservan(sistema, ruta_config_prueba):
    with sistema.bd.sesion() as s:
        s.add_all([
            m.ConfigOverride(clave="detectores.piscina.inmovil_tiempo_s", valor=5.0),
            m.ConfigOverride(clave="alarmas.piscina.votos_n", valor=2),
            m.ConfigOverride(clave="detectores.puerta.porcentaje_min", valor=33.0),
        ])
    assert consultas.leer_overrides(sistema.bd) == {"detectores.puerta.porcentaje_min": 33.0}

    cfg, error = consultas.config_efectiva(sistema.bd, ruta_config_prueba)
    assert error is None                                  # sin descartar, extra="forbid" invalidaría todos los overrides
    assert cfg.detectores.puerta.porcentaje_min == 33.0


def test_lista_de_detectores_de_una_camara_pierde_piscina(sistema):
    with sistema.bd.sesion() as s:
        s.add(m.ConfigOverride(clave="camaras.laptop.detectores", valor=["rostros", "piscina", "puerta"]))
    assert consultas.leer_overrides(sistema.bd) == {"camaras.laptop.detectores": ["rostros", "puerta"]}


def test_zonas_de_piscina_se_ignoran(sistema):
    with sistema.bd.sesion() as s:
        s.add_all([
            m.Zona(camara_id="laptop", nombre="Piscina", tipo="piscina", puntos=[[0, 0], [1, 0], [1, 1]]),
            m.Zona(camara_id="laptop", nombre="Borde", tipo="borde_piscina", puntos=[[0, 0], [1, 0], [1, 1]]),
            m.Zona(camara_id="laptop", nombre="Puerta", tipo="puerta", puntos=[[0, 0], [1, 0], [1, 1]]),
        ])
    assert [z.nombre for z in consultas.zonas_de_camara(sistema.bd, "laptop")] == ["Puerta"]


def test_medio_de_prueba_con_piscina_no_rompe_la_config(sistema):
    with sistema.bd.sesion() as s:
        s.add(m.MedioPrueba(id="viejo", nombre="Vieja", tipo="video", ruta="x.mp4",
                            detectores=["piscina", "fuego"], segundos_por_imagen=3.0))
    cfg = sistema._con_pruebas(cargar_config(sistema.ruta_config))
    assert cfg.camaras["prueba_viejo"].detectores == ["fuego"]
