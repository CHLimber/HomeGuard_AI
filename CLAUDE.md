# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proyecto
HomeGuard AI: sistema de seguridad residencial 100 % software para una feria universitaria (UAGRM). Una laptop con
Python recibe video de 1–3 cámaras (webcam + celulares con IP Webcam/DroidCam por HTTP/MJPEG) y detecta 5 anomalías:
intrusión (rostro desconocido), piscina, fuego/humo, caída y puerta abierta fuera de horario. Al confirmar una alarma
la envía por WebSocket al panel `/alarma` (sirena Web Audio), manda una foto por Telegram y la registra en SQLite con
sus latencias (requisito: menos de 2 s). Requisito académico: el preprocesamiento usa operaciones de bits vectorizadas
y tiene un benchmark (`docs/BITWISE.md`, `docs/BENCHMARK.md`).

## Comandos
En Windows, Python 3.12 en `.venv` (en Linux/macOS, `.venv/bin/python`):
```bash
.venv/Scripts/python -m pytest -q                                    # todos los tests (~20 s, sin cámaras ni internet)
.venv/Scripts/python -m pytest tests/test_motor.py -q                # un archivo
.venv/Scripts/python -m pytest tests/test_puerta.py -k horario -q    # un test por nombre
.venv/Scripts/python run.py --demo [--sin-telegram] [--puerto 8001]  # videos sintéticos en bucle, BD data/homeguard_demo.db
.venv/Scripts/python run.py                                          # cámaras reales de config.yaml
.venv/Scripts/python scripts/verificar_entorno.py [--cargar-modelos] [--sin-camaras]
.venv/Scripts/python scripts/descargar_modelos.py                    # pesos a models/ (gitignored)
.venv/Scripts/python -m homeguard.preproceso.benchmark               # reescribe docs/BENCHMARK.md y docs/benchmark.csv
.venv/Scripts/python scripts/evaluar_detector.py --detector fuego --carpeta data/videos_prueba/fuego [--bd ...]
.venv/Scripts/python scripts/reporte_latencias.py [--demo]
.venv/Scripts/python scripts/probar_camara.py 0 [--sin-ventana]     # o una URL http://IP:8080/video; muestra FPS
.venv/Scripts/python scripts/probar_telegram.py [--obtener-chat-id]
.venv/Scripts/python scripts/generar_tablas_informe.py [--demo] [--desde AAAA-MM-DD]  # → docs/informe/
.venv/Scripts/python scripts/generar_lut_fuego.py --bits 9 [--muestras carpeta]       # → data/lut_fuego_512.npy
nativo\compilar.bat                                                 # Fase 7 opcional (gcc/MinGW o cl)
```
`scripts/` es un paquete: `run.py --demo`, el benchmark y `tests/conftest.py` importan
`scripts.generar_video_sintetico.generar_todos` para crear los videos sintéticos si faltan.
Dashboard: http://localhost:8000/en-vivo · Panel: http://IP:8000/alarma. No hay linter configurado.
Al terminar un cambio, verificar con los tests y con `run.py --demo`: la puerta sintética dispara una alarma a los
~6 s, y después una vez por cada cooldown de 30 s (si el sistema está armado).

## Arquitectura (lo que no se ve leyendo un solo archivo)

**Flujo e hilos.** Un hilo por cámara (`captura/camaras.py`) guarda solo el último frame; los archivos se reproducen
en bucle a su FPS real. Un único hilo de procesamiento (`pipeline.py`) recorre las cámaras, llama a
`Analizador.analizar()`, pasa las observaciones a `MotorReglas.procesar()` y por cada `Disparo` llama a
`Sistema.despachar()`. FastAPI/uvicorn corre en el hilo principal. El pipeline emite por WebSocket con
`asyncio.run_coroutine_threadsafe` sobre el loop que captura el lifespan de `web/app.py` (`GestorWebSocket.fijar_loop`).
Telegram tiene su propio hilo con `queue.Queue`.

**Contrato de los detectores** (`detectores/base.py`): `procesar(frame, ctx) -> list[PosibleEvento]`.
- Devuelven **una observación por zona evaluada, con `activo=True/False`**: el motor necesita las negativas para votar
  N de M.
- Usan **`ctx.t` y nunca `time.time()`**, así los tests y el evaluador corren más rápido que el tiempo real.
- Escriben sus valores crudos en `ctx.calibracion` (los muestra la página Calibración).
- **No deciden alarmas.** Solo el motor enciende bits del byte de estado (`reglas/estado.py`; el JS del panel lo
  decodifica igual).
- Reparto de reglas: las temporales propias de cada anomalía (2 s de puerta, inmovilidad, etc.) viven en el detector,
  y esas anomalías usan 1 de 1 en el motor; las de "cuántos frames" (K consecutivos = N de N, 3 de 5) viven en el motor.

**Modelos caros solo cuando hace falta.** `ctx.detecciones_generales()` corre el YOLO general + ByteTrack de forma
perezosa, una vez por frame, y lo comparten piscina y rostros. YuNet/SFace corren solo si hay una persona en la zona
"acceso". El YOLO de fuego corre solo si la capa 1 bitwise supera su umbral. La pose corre cada `cada_n_frames`.
Los modelos se cargan de forma perezosa en `detectores/modelos.py`. YuNet y SFace no son thread-safe: una instancia
por hilo, o una con nombre (el alta de residentes usa `instancia="registro"` con un lock).

**Configuración en capas.** `config.yaml` (comentado y validado con pydantic `extra="forbid"` en `config.py`) +
overrides del dashboard en la tabla `config` de la BD, como claves con puntos. `Sistema._aplicar_config()` los propaga
en caliente al motor, Telegram y las cámaras. En `--demo`, las cámaras salen de `demo.camaras` (los overrides de
cámara usan ese prefijo) y la BD es otra. Las descripciones de los umbrales en el dashboard salen de los comentarios
del YAML (`leer_comentarios`). **Todo umbral nuevo va en `config.yaml` con un comentario y un campo en `config.py`.**

**Orden de `despachar()`:** JPEG a disco → WebSocket → cola de Telegram → INSERT en la BD. La alerta llega primero
al panel. Si el ack del panel llega antes que el INSERT, queda en `_acks_anticipados`. La latencia al panel es
`ack − t_detección`, y por eso es una cota superior.

**Prueba con video (modo exposición).** `homeguard/pruebas.py` guarda los medios subidos (tabla `medio_prueba`,
archivos en `general.carpeta_pruebas`). `Sistema._con_pruebas()` los agrega a `config.camaras` como `prueba_<id>`
cada vez que se aplica la config; solo `Sistema.prueba_activa` está activa. Una fuente que es carpeta se reproduce
como presentación (`tipo_fuente == "imagenes"`) y el pipeline pasa `fuente_estatica=True`: fuego no exige movimiento.
`/api/camaras` y la edición de cámaras ignoran las `prueba_*`.

**Código compartido con los scripts.** `analizador.py` y `db/consultas.py` (overrides, zonas, embeddings) los usan el
sistema en vivo y `scripts/evaluar_detector.py`. Los evaluadores escriben en `docs/PRUEBAS.md` entre los marcadores
`<!-- detector:INICIO/FIN -->`.

## Tests
- `tests/conftest.py` crea un `config.yaml` temporal sin cámaras, con BD y carpetas en `tmp_path`, y genera los videos
  sintéticos una vez por sesión.
- YOLO, pose y rostros se simulan: `Analizador.detector_general`, `DetectorFuego(inferir_capa2=...)`,
  `DetectorCaidas(inferir_pose=...)`, `DetectorRostros(detectar=...)`. Los videos traen la verdad de terreno en un
  `.json` (cajas, apertura de la puerta).
- `pytest.ini` silencia el aviso de deprecación de `sv.ByteTrack`.

## Convenciones y trampas
- Código, comentarios, logs y UI en español, con type hints.
- Sin bucles Python píxel a píxel (salvo la variante A del benchmark).
- Operaciones matriz-con-matriz con `cv2.bitwise_*`; con un escalar, NumPy (`cv2.bitwise_and(img, escalar)` falla
  con imágenes chicas).
- `supervision` está fijado `<0.31` porque ahí desaparece `sv.ByteTrack`.
- OpenCV 5: los avisos "Targets are not supported" se silencian en `modelos.py`.
- Los scripts llaman a `consola_utf8()`, porque Windows usa cp1252 al redirigir la salida y los caracteres como `≤`
  o `→` rompen el `print`.
- Frontend sin CDN (tiene que funcionar offline en la feria): CSS propio en `web/static`, JS sin frameworks.
- Sin Docker, MQTT, nube ni hardware. Mantener las dependencias al mínimo. Las decisiones no cubiertas se anotan en
  `docs/DECISIONES.md`.
- Valores por defecto de `config.yaml` = Anexo C del informe Word; cada fórmula del informe lleva un comentario
  `# Informe, ecuación de …`. No cambiar fórmulas ni defaults sin anotarlo en `docs/DECISIONES.md` (39–40 listan
  las diferencias aceptadas).
- Las claves de la tabla `config` que empiezan con `_` (p. ej. `_sistema.armado`) son internas: no se validan ni se
  restauran. Desarmado, los detectores siguen corriendo pero el motor no confirma nada.
- `homeguard/preproceso/nativo.py` carga `nativo/` con ctypes solo si está compilado; todo tiene que funcionar sin él.
- Commits sin líneas de atribución a Claude.

## Estado
Las fases 0–6 y la revisión contra `Contexto_CaludeCode.md` (la especificación original) están hechas. La
Fase 7 (SIMD en C) tiene el código, pero no se compiló (`docs/PROGRESO.md`). Lo pendiente lo hace el grupo a mano (`docs/GUIA_GRUPO.md`): `.env`
de Telegram, URLs de los celulares, zonas, residentes, videos de prueba y calibración.

Limitaciones conocidas en `--demo`: el YOLO de fuego no reconoce la llama sintética y YOLO no ve el rectángulo de
`zona.mp4` como persona, así que fuego y piscina solo se ejercitan por completo en los tests.
