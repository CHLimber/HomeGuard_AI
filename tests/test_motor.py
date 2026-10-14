from homeguard.config import CfgAlarma, CfgAlarmas, CfgMotor
from homeguard.detectores.base import PosibleEvento
from homeguard.reglas import estado as est
from homeguard.reglas.motor import MotorReglas


def motor(n=3, m=5, cooldown=10.0, auto_limpiar=0.0) -> MotorReglas:
    regla = CfgAlarma(votos_n=n, votos_m=m, cooldown_s=cooldown)
    alarmas = CfgAlarmas(intrusion=regla, piscina=regla, fuego=regla, caida=regla, puerta=regla)
    return MotorReglas(alarmas, CfgMotor(auto_limpiar_s=auto_limpiar))


def obs(activo: bool, t: float, tipo="fuego", zona="cocina", cam="cam1") -> PosibleEvento:
    return PosibleEvento(tipo=tipo, camara_id=cam, zona=zona, activo=activo, t=t, confianza=0.8)


def alimentar(mt: MotorReglas, secuencia: list[int], t0: float = 0.0, paso: float = 0.1, **kw):
    disparos = []
    for i, v in enumerate(secuencia):
        disparos += mt.procesar([obs(bool(v), t0 + i * paso, **kw)])
    return disparos


def test_votacion_3_de_5_no_dispara_con_2():
    mt = motor(3, 5)
    assert alimentar(mt, [1, 0, 1, 0, 0, 0, 0]) == []
    assert mt.estado == 0


def test_votacion_3_de_5_dispara_al_tercer_voto():
    mt = motor(3, 5)
    disparos = alimentar(mt, [1, 0, 1, 0, 1])
    assert len(disparos) == 1
    assert disparos[0].votos == 3
    assert mt.estado == est.FUEGO


def test_votos_viejos_salen_de_la_ventana():
    mt = motor(3, 5)
    # 2 positivos, luego 4 negativos (salen de la ventana), luego 1 positivo: solo 1 voto en ventana
    assert alimentar(mt, [1, 1, 0, 0, 0, 0, 1]) == []


def test_k_consecutivos_con_n_igual_m():
    mt = motor(5, 5)
    assert alimentar(mt, [1, 1, 1, 1, 0, 1, 1, 1, 1]) == []
    assert len(alimentar(mt, [1], t0=1.0)) == 1  # 5.º consecutivo


def test_cooldown_impide_repetir():
    mt = motor(1, 1, cooldown=10.0)
    assert len(alimentar(mt, [1], t0=0.0)) == 1
    assert alimentar(mt, [1, 1, 1], t0=1.0) == []        # dentro del cooldown
    assert len(alimentar(mt, [1], t0=10.5)) == 1          # pasado el cooldown


def test_cooldown_es_por_tipo_y_zona():
    mt = motor(1, 1, cooldown=60.0)
    assert len(mt.procesar([obs(True, 0.0, zona="cocina")])) == 1
    assert len(mt.procesar([obs(True, 0.1, zona="living")])) == 1           # otra zona
    assert len(mt.procesar([obs(True, 0.2, tipo="puerta", zona="cocina")])) == 1  # otro tipo
    assert mt.procesar([obs(True, 0.3, zona="cocina")]) == []
    assert mt.estado == est.FUEGO | est.PUERTA


def test_silenciar_apaga_estado_y_mantiene_cooldown():
    mt = motor(1, 1, cooldown=30.0)
    alimentar(mt, [1])
    assert mt.estado == est.FUEGO
    assert mt.silenciar() == 0
    assert alimentar(mt, [1], t0=5.0) == []
    assert mt.estado == 0


def test_auto_limpiar():
    mt = motor(1, 1, cooldown=100.0, auto_limpiar=3.0)
    alimentar(mt, [1])
    alimentar(mt, [0], t0=2.0)
    assert mt.estado == est.FUEGO
    alimentar(mt, [0], t0=3.5)
    assert mt.estado == 0


def test_activos_para_semaforo():
    mt = motor(3, 5)
    mt.procesar([obs(True, 0.0)])
    assert mt.activos == est.FUEGO and mt.estado == 0
    mt.procesar([obs(False, 0.1)])
    assert mt.activos == 0


def test_punta_a_punta_varios_detectores():
    """Secuencia simulada de varias anomalías y cámaras: solo disparan las que cumplen su regla."""
    from homeguard.config import cargar_config

    cfg = cargar_config()
    mt = MotorReglas(cfg.alarmas, cfg.motor)
    disparos = []
    t = 0.0
    for i in range(20):
        t += 0.1
        lote = [
            obs(i % 2 == 0, t, tipo="fuego", zona="cocina"),               # 1 de cada 2 => 3 de 5 se cumple
            obs(i >= 15, t, tipo="intrusion", zona="entrada"),             # 5 consecutivos al final
            obs(i in (3, 7, 11), t, tipo="piscina", zona="pileta"),        # disperso: nunca 3 de 5
            obs(i == 19, t, tipo="puerta", zona="principal", cam="cam2"),  # 1 de 1
        ]
        disparos += mt.procesar(lote)
    tipos = sorted(d.tipo for d in disparos)
    assert tipos == ["fuego", "intrusion", "puerta"]
    assert mt.estado == est.codificar(["fuego", "intrusion", "puerta"])
