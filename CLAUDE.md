# CLAUDE.md — HomeGuard AI

## Qué es
Sistema de seguridad residencial 100 % software para una feria universitaria (UAGRM, Ing. en Sistemas).
Una laptop con Python recibe video de 1–3 cámaras (webcam + celulares con IP Webcam/DroidCam vía HTTP/MJPEG) y
detecta 5 anomalías: intrusión (rostro desconocido), piscina, fuego/humo, caída y puerta abierta fuera de horario.
Al confirmar una alarma: WebSocket al panel `/alarma` (sirena Web Audio, parpadeo, vibración), foto por Telegram y
registro en SQLite con latencias (requisito < 2 s). El preprocesamiento usa operaciones bitwise vectorizadas.

## Instalar y correr
```bash
py -3.12 -m venv .venv                      # Linux/macOS: python3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python scripts/descargar_modelos.py
.venv/Scripts/python scripts/verificar_entorno.py [--cargar-modelos] [--sin-camaras]
.venv/Scripts/python run.py --demo          # videos sintéticos en bucle, BD data/homeguard_demo.db
.venv/Scripts/python run.py [--sin-telegram] [--puerto 8001]
```
Dashboard: http://localhost:8000/en-vivo · Panel: http://IP:8000/alarma.
En esta máquina de desarrollo (Windows 11): Python 3.12.10 en `.venv`, torch 2.14 CPU, ultralytics 8.4,
opencv-python 5.0, supervision 0.30, numpy 2.5, fastapi 0.143.

## Tests
`.venv/Scripts/python -m pytest -q` → 73 tests, ~20 s. No necesitan cámaras ni internet. Los modelos se simulan con
la verdad de terreno de los videos sintéticos (`scripts/generar_video_sintetico.py` escribe `.mp4` + `.json`).
`pytest.ini` silencia el aviso de deprecación de `sv.ByteTrack`.

## Estructura
```
run.py                      entrada: args, logs, genera videos demo si faltan, uvicorn
config.yaml                 TODOS los umbrales, comentados (los comentarios se muestran en el dashboard)
homeguard/
  config.py                 pydantic (extra=forbid), overrides con claves de puntos, .env, leer_comentarios()
  sistema.py                orquestador: componentes, config en caliente, despachar(), acks, silenciar
  pipeline.py               hilo de procesamiento, JPEG del stream, telemetría (FPS/CPU/RAM/calibración)
  analizador.py             preproceso + detectores de un frame (lo usan pipeline y evaluar_detector)
  anotador.py               dibujo con supervision
  logs.py                   logging + consola_utf8()
  captura/camaras.py        Camara (hilo, último frame, reconexión) y GestorCamaras
  preproceso/bitwise.py     AND/OR/XOR, cuantización, RGB332 + cv2.LUT
  preproceso/benchmark.py   python -m homeguard.preproceso.benchmark → docs/BENCHMARK.md
  detectores/base.py        Zona, PosibleEvento, Contexto, EstadoCamara, Detector
  detectores/modelos.py     carga perezosa de YOLO/YuNet/SFace
  detectores/{puerta,fuego,piscina,caidas,rostros}.py
  reglas/estado.py          byte de estado (bit 0..4 = intrusion, piscina, fuego, caida, puerta)
  reglas/motor.py           N de M por (tipo, cámara, zona), cooldown, estado enclavado, activos
  salidas/{websocket,telegram,registro}.py
  db/{modelos,sesion,consultas}.py   SQLite WAL; consultas compartidas con los scripts
  web/app.py                páginas, /ws/alarma, /ws/estado, /stream/{cam}, /snapshot/{cam}.jpg
  web/api.py                /api/... estado, silenciar, eventos(.csv), camaras, config, zonas, residentes, telegram
  web/templates, web/static CSS propio (sin CDN, funciona offline), JS sin frameworks
scripts/                    verificar_entorno, descargar_modelos, generar_video_sintetico, probar_camara,
                            probar_telegram, evaluar_detector, reporte_latencias
tests/                      pytest (conftest crea un config.yaml temporal sin cámaras y una BD temporal)
docs/                       ARQUITECTURA, DECISIONES, BITWISE, BENCHMARK, PRUEBAS, PROGRESO, GUIA_GRUPO
data/                       videos_prueba/<anomalía>/{positivos,negativos}, eventos/ (fotos), *.db (gitignored)
models/                     pesos (gitignored; se bajan con descargar_modelos.py)
```

## Convenciones
- Código, comentarios, logs y UI en español. Type hints. Identificadores en español salvo términos técnicos.
- Sin bucles Python píxel a píxel (salvo la variante A del benchmark). Operaciones matriz-matriz con `cv2.bitwise_*`;
  con un escalar, NumPy (`cv2.bitwise_and(img, escalar)` falla con imágenes chicas).
- **Ningún umbral hardcodeado**: va en `config.yaml` con un comentario + campo en `homeguard/config.py`.
- Los detectores: una `PosibleEvento` por zona evaluada (`activo` True/False), tiempo de `ctx.t` (nunca
  `time.time()`), valores crudos en `ctx.calibracion`. Solo el motor de reglas decide alarmas.
- Nuevas dependencias: evitarlas. Sin Docker, MQTT, nube ni hardware.
- Decisiones no cubiertas por el pedido → la opción más simple para una demo en vivo, anotada en `docs/DECISIONES.md`.
- Commits sin líneas de atribución a Claude. `.gitattributes` normaliza a LF.

## Dónde está cada umbral
`config.yaml`:
- `alarmas.<tipo>.{votos_n, votos_m, cooldown_s}`: motor de reglas (intrusión 5/5, piscina 3/5, fuego 3/5, caída 1/1, puerta 1/1)
- `detectores.rostros.umbral_similitud` (0,363), `confianza_rostro`, `tamano_min_rostro_px`
- `detectores.piscina.{tiempo_sin_supervisor_s, inmovil_desplazamiento_px, inmovil_tiempo_s}`
- `detectores.fuego.{hue_min, hue_max, sat_min, val_min, umbral_capa1_pct, confianza_capa2}`
- `detectores.caidas.{ratio_min 1.4, angulo_max_grados 45, ventana_descenso_s 1, descenso_min_relativo, inmovil_tiempo_s 5, cada_n_frames}`
- `detectores.puerta.{metodo, umbral_diferencia, porcentaje_min 25, duracion_min_s 2, horarios_permitidos}`
- `preproceso.{bits_movimiento, apertura_movimiento_px}`, `procesamiento.*` (FPS, imgsz), `telegram.*`, `panel.latencia_objetivo_ms`
Los cambios hechos desde el dashboard están en la tabla `config` de la BD (prevalecen sobre el YAML).

## Estado actual
Fases 0–6 terminadas (detalle en `docs/PROGRESO.md`). Funciona de punta a punta en `--demo`: la puerta sintética
dispara, el panel recibe la alerta con ack (latencia ~5–20 ms en localhost) y el evento queda con foto en la BD.
Pendiente del grupo (`docs/GUIA_GRUPO.md`): `.env` de Telegram, URLs de los celulares, zonas, residentes, videos de
prueba (→ `scripts/evaluar_detector.py` llena `docs/PRUEBAS.md`) y calibración.

## Problemas conocidos
- El YOLO fire-smoke no reconoce la llama sintética (elipses): en `--demo` el fuego solo activa la capa 1.
- El rectángulo de `zona.mp4` no es una persona para YOLO: en `--demo` la piscina no dispara (sí en los tests).
- La vibración y el wake lock pueden no funcionar en Android por `http://IP` (sin HTTPS); ver GUIA_GRUPO.
- `sv.ByteTrack` se elimina en supervision 0.31 → fijado `<0.31`. Si algún día se actualiza, migrar a `trackers`.
- La latencia al panel se mide con el ack (incluye la vuelta): es una cota superior.
- Un solo hilo de procesamiento: con 3 cámaras y todos los detectores, ~9 FPS por cámara en la laptop de desarrollo
  (16 hilos). En una laptop más lenta, bajar `imgsz_yolo`/`fps_objetivo`.

## Cómo continuar
Leer `docs/PROGRESO.md` (estado y pendientes) y `docs/DECISIONES.md`. Antes de cambiar algo: correr los tests;
al terminar: tests + `run.py --demo` + actualizar PROGRESO.md y este archivo + `git commit`.
