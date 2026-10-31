# HomeGuard AI — Contexto maestro para Claude Code (v2, 31/10/2026)

Reemplaza a `01_PROMPT_CLAUDE_CODE.md`. Junta el contexto del proyecto, las decisiones cerradas, el estado del informe y la especificación técnica completa.

Cómo usarlo: creá una carpeta vacía `homeguard/`, abrí una terminal ahí, ejecutá `claude` y pegá todo lo que está debajo de la línea. Si la sesión se corta, abrí otra en la misma carpeta y escribí: "Lee CLAUDE.md y docs/PROGRESO.md y continúa desde la fase pendiente".

---

Sos el desarrollador principal de **HomeGuard AI**. Tu trabajo es construir todo lo que se pueda construir con código, dejarlo instalado, probado y documentado, para que el grupo solo tenga que configurar celulares, grabar videos de prueba y calibrar. Trabajá de forma autónoma por fases (sección 14). Preguntá solo si algo te bloquea de verdad.

## 1. Contexto académico (importa para cómo escribís el código)

- Proyecto grupal de Ingeniería en Sistemas de Información, UAGRM (Santa Cruz, Bolivia). Grupo 53. Materia: **Programación Ensamblador**. Docente: Valentin Victor Flores Guzman. 4 integrantes: Azurduy Chaulla Álvaro, Chambi Tonconi Nilser Limber, Lupa Cuellar Alex Yahir, Vargas Condori Aide Yhosselin.
- Se presenta en una **feria** universitaria. Área: Desarrollo de Software. Categoría: Avanzado. Fecha de la feria: por confirmar (planificar con 8 semanas).
- Como la materia es Ensamblador, el **uso de operaciones de bits y desplazamientos es un requisito del docente y es lo que más se evalúa**. Tiene que verse en el código, estar explicado didácticamente y estar medido con un benchmark. Hay una fase opcional en C con SIMD (sección 5.6) que conecta directo con la materia.
- Ya existe un **informe en Word** (45 págs., APA 7) con fórmulas, parámetros y anexos. El código tiene que coincidir con lo que dice el informe (sección 15). No cambies fórmulas, nombres de bits ni umbrales por defecto sin anotarlo en `docs/DECISIONES.md` y avisar en el resumen final.
- Cada integrante tiene que poder explicar su módulo ante el jurado: el código tiene que ser legible, comentado en español y sin trucos innecesarios.

Roles sugeridos (para organizar módulos y docs): integrador; visión 1 = rostros + puerta + benchmark; visión 2 = piscina + fuego + caídas; web = dashboard + panel + Telegram.

## 2. Decisiones cerradas (no cambiar sin avisar)

| Tema | Decisión | Descartado y por qué |
|---|---|---|
| Lenguaje | Python 3.11 | Versiones más nuevas pueden romper ultralytics/torch |
| Modelos | Solo preentrenados, no se entrena nada | Entrenar no aporta al objetivo y no hay GPU |
| Hardware | 100 % software, sin compras | ESP32/Arduino, sirena 12 V, relés, LEDs y reed switch eliminados (decisión definitiva del 07/10) |
| Cámaras | Celulares con IP Webcam / DroidCam / Iriun (HTTP/MJPEG) + webcam de la laptop | Cámaras IP compradas |
| Alarma local | Panel web en otro celular/tablet: sirena Web Audio, pantalla roja, vibración | Sirena física |
| Alertas remotas | Telegram Bot API (sendPhoto) | WhatsApp (exige cuenta empresarial) |
| Comunicación | WebSocket desde FastAPI | MQTT (no hay microcontrolador) |
| Puerta | Detección visual contra imagen de referencia (absdiff/XOR) | Sensor magnético |
| Piscina | "Ingreso no supervisado e inmovilidad en la zona de piscina" | "Detección de ahogamiento" (es investigación abierta) |
| Fuego | Capa 1 color + movimiento con bits, capa 2 YOLO fuego/humo | Solo color (demasiados falsos positivos) |
| Rostros | YuNet + SFace (OpenCV Zoo) | MediaPipe (solo detecta, no reconoce). No instales mediapipe |
| Infraestructura | Todo local en una laptop, red WiFi local; solo Telegram usa internet | Docker, nube, servicios pagos |

## 3. Qué es el sistema

Una laptop recibe video de 1 a 3 cámaras, detecta 5 anomalías en tiempo real y, cuando el motor de reglas confirma una, hace tres cosas en paralelo:

1. Envía el estado por WebSocket al **panel de alarma web** (`/alarma`) y al dashboard.
2. Envía una **foto del evento por Telegram** al dueño (o a un grupo).
3. Registra el evento en **SQLite** con la foto y las latencias medidas.

Además hay un **dashboard web** para ver cámaras en vivo, registrar residentes, dibujar zonas, ajustar umbrales, consultar el historial y calibrar.

Requisito medible: detección → panel y detección → Telegram en **menos de 2 s**, medido y guardado en cada evento (sección 6.4).

## 4. Las 5 anomalías

Cada detector implementa `procesar(frame, ctx) -> list[PosibleEvento]`. Un detector nunca dispara la alarma: solo el motor de reglas decide. Todos los umbrales viven en `config.yaml`. Cada detector expone además `valores_crudos()` para el modo calibración.

`PosibleEvento`: `tipo` (bit), `camara_id`, `zona`, `confianza` (0-1), `t_deteccion` (`time.monotonic()` + `time.time()` para mostrar), `frame` (copia), `bbox` opcional, `extra` (dict con valores crudos).

### 4.1 Intrusión (bit 0)

- Se ejecuta solo si YOLO detectó una persona dentro de la zona `acceso` (ahorra CPU).
- `cv2.FaceDetectorYN.create(yunet.onnx, "", (w,h), score_threshold=0.9)`; llamá `setInputSize((w,h))` cuando cambie el tamaño del frame.
- `cv2.FaceRecognizerSF.create(sface.onnx, "")`: `alignCrop` + `feature` → vector de 128.
- Similitud coseno contra todos los embeddings de residentes: `sim = (a·b) / (‖a‖‖b‖)` (en el informe es una ecuación numerada). Se usa la máxima por residente.
- Desconocido si `max_sim < 0.363` (umbral de referencia de OpenCV Zoo para coseno). Regla: desconocido en `K` frames consecutivos (por defecto 5) dentro de `acceso`.
- Si no hay residentes cargados, todo rostro es desconocido: mostralo como advertencia en el dashboard.
- Objetivo del informe: ≥ 90 % de acierto con iluminación controlada.

### 4.2 Piscina (bit 1)

- YOLOv8n con clases COCO `person=0`, `cat=15`, `dog=16`, + `sv.ByteTrack` + `sv.PolygonZone` para `piscina` y `borde_piscina`.
- Regla (a) ingreso no supervisado: hay persona o mascota en `piscina` y ninguna persona en `borde_piscina` durante `T_sin_supervisor` s (por defecto 2).
- Regla (b) inmovilidad: el mismo `tracker_id` dentro de `piscina` con desplazamiento del centro < `X` px (normalizado al ancho, por defecto 0,02) durante más de `N` s (por defecto 8).
- Ojo con los IDs que cambia ByteTrack: si un track desaparece menos de 1 s y reaparece cerca, tratarlo como el mismo para el contador de inmovilidad.

### 4.3 Fuego y humo (bit 2)

- Capa 1 (bits, barata, corre en todos los frames): máscara de color fuego por cuantización + LUT (sección 5.3) AND máscara de movimiento por XOR (sección 5.2), restringida a la ROI. Activa si el porcentaje de píxeles supera `umbral_capa1` (por defecto 0,5 % de la ROI).
- Capa 2 (cara, solo si la capa 1 está activa): YOLOv8n fuego/humo de `rabahdev/fire-smoke-yolov8n` (entrenado con D-Fire, mAP50 0,754). **No hardcodees los IDs de clase**: leé `model.names` al cargar y mapeá por nombre (`fire`, `smoke`).
- Regla: capa 1 activa y capa 2 con confianza > 0,5 en 3 de 5 frames.
- Alternativa configurable para la capa 1: HSV con `cv2.inRange` (dejá ambas y documentá la comparación en BITWISE.md).

### 4.4 Caída (bit 3)

- YOLOv8n-pose (17 keypoints COCO). Se ejecuta cada `cada_n_frames` (por defecto 2). Hombros 5 y 6, caderas 11 y 12; ignorá keypoints con confianza < 0,5.
- Ángulo del torso: vector del punto medio de hombros al punto medio de caderas, `θ = atan2(|dy|, |dx|)`; horizontal si θ < 45°.
- Regla: ratio ancho/alto del bbox > 1,4 **y** torso horizontal **y** descenso brusco del centro (caída de más del 20 % de la altura del frame en menos de 1 s) **y** luego inmovilidad > 5 s.
- Negativos a respetar: agacharse, sentarse, atarse los cordones (no deben disparar).

### 4.5 Puerta (bit 4)

- Referencia: imagen en gris de la zona `puerta` cerrada, capturada desde el dashboard y guardada en `data/referencias/<camara>_<zona>.png`.
- Diferencia: `cv2.absdiff` + umbral, o XOR de binarizadas (configurable; las dos se explican en BITWISE.md).
- Proporción de píxeles cambiados = `countNonZero(diff AND roi) / countNonZero(roi)`.
- Regla: proporción > 0,25 sostenida 2 s **y** hora actual fuera del horario permitido (zona horaria `America/La_Paz`).
- Ruido de iluminación: blur gaussiano previo y opción de actualizar la referencia lentamente cuando la puerta está cerrada (desactivada por defecto).

## 5. Uso de bits (requisito central)

Todo vectorizado sobre matrices `uint8` con NumPy/OpenCV. Nada de bucles por píxel, salvo como línea base del benchmark. Cada función de `homeguard/preproceso/bitwise.py` lleva docstring con un ejemplo numérico chico (que también es un test).

### 5.1 AND — máscara de zona (ROI)

Polígono → máscara `uint8` 0/255 con `cv2.fillPoly`; `cv2.bitwise_and(frame, frame, mask=roi)` o `frame & roi[..., None]`. Las máscaras se cachean por (cámara, zona, resolución).

### 5.2 XOR — movimiento y estado de la puerta

Binarizar dos frames consecutivos en gris (umbral o Otsu) y `cv2.bitwise_xor`; los píxeles en 1 son los que cambiaron. Comparar en BITWISE.md contra `absdiff` (XOR solo funciona bien sobre binarizadas).

### 5.3 Desplazamientos — cuantización de color a 9 bits + LUT

`idx = ((R >> 5) << 6) | ((G >> 5) << 3) | (B >> 5)` → índice 0-511 (3 bits por canal). Una tabla `lut_fuego` de 512 booleanos marca qué colores son "fuego" (generada a partir de rangos HSV o de muestras, con un script). Máscara = `lut_fuego[idx]`. Cuidado: hacé el cálculo en `uint16` para que `<< 6` no desborde. OpenCV entrega BGR: documentá el orden de canales.

### 5.4 AND/OR — combinación de máscaras

`mascara_fuego = color & movimiento & roi`; `zonas_de_interes = roi_a | roi_b`.

### 5.5 Byte de estado

En `homeguard/reglas/estado.py`: `INTRUSION=1<<0, PISCINA=1<<1, FUEGO=1<<2, CAIDA=1<<3, PUERTA=1<<4`. Activar `estado |= bit`, limpiar `estado &= ~bit & 0xFF`, consultar `estado & bit`. Se envía al panel como entero y JavaScript lo decodifica con `estado & (1 << n)`. Esto coincide con el Anexo A del informe.

### 5.6 Benchmark (`homeguard/preproceso/benchmark.py`)

Compara sobre el mismo set de frames 640×480 (921 600 bytes por frame BGR):

1. Bucle Python puro píxel a píxel (con pocos frames, es lentísimo; extrapolá y aclaralo).
2. NumPy/OpenCV sobre el frame completo, sin ROI.
3. NumPy/OpenCV con ROI + XOR (procesando solo la zona).
4. Opcional (Fase 7): C con intrínsecos SSE2 (`_mm_xor_si128`, `_mm_and_si128`) y AVX2 si la CPU lo soporta, compilado como librería compartida y llamado con `ctypes`.

Métricas: ms/frame (mediana y p95), FPS equivalentes, CPU % (`psutil`), speedup contra el bucle. Salida: `docs/benchmark.csv` y una tabla Markdown lista para el póster y el informe. Para la Fase 7, generá el ensamblador con `gcc -O2 -S` (o `objdump -d`) y pegá en BITWISE.md el fragmento del bucle vectorizado, explicando las instrucciones (`pxor`, `pand`, `movdqu`/`vmovdqu`). Si no hay compilador de C (Windows sin MinGW), la fila se omite sin romper nada y lo documentás en GUIA_GRUPO.md.

## 6. Motor de reglas (`homeguard/reglas/motor.py`)

### 6.1 Votación N de M
Por cada (tipo, cámara, zona) una `deque(maxlen=M)` de booleanos; confirma si hay al menos N en True. En DECISIONES.md explicá la justificación probabilística: si un frame da falso positivo con probabilidad p (independiente), `P(falsa alarma) = Σ_{k=N}^{M} C(M,k) p^k (1−p)^(M−k)`. Agregá una función que lo calcule para mostrarlo en calibración.

### 6.2 Cooldown
Por (tipo, zona), configurable (por defecto 30 s). Durante el cooldown no se repite Telegram, pero el bit sigue activo mientras dure la condición.

### 6.3 Estado y silenciar
El motor mantiene el byte de estado. "Silenciar" desde el panel apaga la sirena y limpia los bits activos; un evento nuevo de otro tipo, o del mismo tras el cooldown, la vuelve a encender. Opción "desarmar sistema" desde el dashboard (no detecta nada mientras está desarmado). Horarios en `America/La_Paz`.

### 6.4 Latencias
- `t_det` = momento en que el motor confirma el evento (`time.monotonic()`).
- Panel: el panel responde `{"accion":"ack","evento_id":...}` al recibir cada alerta; `latencia_panel_ms = t_ack_recibido_en_servidor − t_det`. Medir en el servidor evita la desincronización de relojes entre dispositivos; es una cota superior (incluye ida y vuelta) y así hay que explicarlo en PRUEBAS.md.
- Telegram: `latencia_telegram_ms = t_respuesta_ok_de_la_API − t_det`.
- Ambas se guardan en `evento` y se ven en el historial.

## 7. Arquitectura, concurrencia y estructura

Flujo: cámaras → captura (un hilo por cámara, solo el último frame) → preproceso bitwise → detectores → motor de reglas → [WebSocket al panel y al dashboard | cola de Telegram | registro en BD].

Concurrencia:
- Un hilo de captura por cámara con `cv2.VideoCapture` leyendo en bucle y guardando solo el último frame (evita el retraso del buffer MJPEG). Reconexión automática con backoff. En Windows, para índices de webcam usá `cv2.CAP_DSHOW`.
- Un hilo de procesamiento que recorre las cámaras.
- FastAPI + uvicorn en el hilo principal (asyncio). Desde el hilo de procesamiento emití al WebSocket con `asyncio.run_coroutine_threadsafe` sobre el loop guardado en el startup, o con una cola que consume una tarea async.
- Telegram en su propio hilo con cola: nunca bloquea al panel. Sin internet, reintenta con backoff y envía lo pendiente al volver.
- No todos los modelos corren en todos los frames: rostros solo con persona en `acceso`, YOLO de fuego solo si dispara la capa 1, pose cada 2 o 3 frames. YOLO general se ejecuta una vez por frame y su resultado se comparte entre piscina, intrusión y caídas mediante `ctx`.
- Redimensioná a 640 px de ancho antes de procesar.

```
homeguard/
  CLAUDE.md
  README.md                  instalación y uso en Windows y Linux/macOS
  requirements.txt
  .env.example               TELEGRAM_TOKEN=, TELEGRAM_CHAT_ID=
  .gitignore                 .venv, .env, models/, data/eventos/, data/referencias/, *.db, __pycache__
  config.yaml
  run.py                     python run.py [--demo] [--sin-telegram] [--puerto 8000]
  scripts/
    descargar_modelos.py
    verificar_entorno.py
    generar_video_sintetico.py
    generar_lut_fuego.py
    probar_telegram.py
    probar_camara.py         URL o índice, muestra FPS
    evaluar_detector.py      --detector fuego --carpeta data/videos_prueba/fuego
    generar_tablas_informe.py  tablas de benchmark, métricas y latencias en Markdown/CSV
  homeguard/
    config.py                config.yaml + .env validados con pydantic
    captura/camaras.py
    preproceso/bitwise.py
    preproceso/benchmark.py
    detectores/base.py  rostros.py  piscina.py  fuego.py  caidas.py  puerta.py
    reglas/motor.py  estado.py
    salidas/websocket.py  telegram.py  registro.py
    db/modelos.py  sesion.py
    web/app.py               rutas, /ws/alarma, /ws/estado, /stream/{camara_id}
    web/templates/           base, en_vivo, residentes, zonas, configuracion, historial, calibracion, panel_alarma
    web/static/              css y js sin frameworks pesados (Tailwind por CDN permitido)
  nativo/                    Fase 7 opcional: bitwise_simd.c, script de compilación
  data/
    videos_prueba/<anomalia>/positivos|negativos/
    eventos/  referencias/
  docs/
    ARQUITECTURA.md  DECISIONES.md  BITWISE.md  PRUEBAS.md  PROGRESO.md  GUIA_GRUPO.md  benchmark.csv
  tests/
```

## 8. Panel de alarma (`/alarma`)

- Pantalla completa, letras grandes, 5 indicadores (uno por bit) encendidos con `estado & (1 << n)`.
- Al abrir: botón grande "ARMAR ALARMA". Ese toque crea el `AudioContext` (política de autoplay) y pide pantalla completa.
- Sirena con Web Audio API: oscilador que barre de 600 a 1200 Hz en bucle (sin mp3).
- Pantalla roja intermitente con CSS mientras el estado ≠ 0.
- `navigator.vibrate([500,200,500])` en bucle si está disponible (documentá que en algunos Android/iOS puede no funcionar; iOS no soporta vibración web).
- Muestra foto, tipo, zona y hora del último evento.
- Botón "SILENCIAR" → `{"accion":"silenciar"}`. Responde "ack" a cada alerta.
- Reconexión automática del WebSocket con indicador conectado/desconectado visible. Al reconectar, el servidor reenvía el estado actual.
- Pensado para celular en vertical y horizontal.

## 9. Dashboard

- **En vivo:** MJPEG por cámara con cajas, zonas y etiquetas (anotadores de supervision), semáforo de las 5 anomalías por WebSocket, FPS y CPU.
- **Residentes:** alta, baja, listado. 3 a 5 fotos por residente → se detecta el rostro, se genera el embedding y se guarda **solo el vector** (las fotos se descartan). Aviso si una foto no tiene rostro o tiene más de uno. Botón para borrar a un residente y sus embeddings (coincide con el consentimiento del Anexo I).
- **Zonas:** elegir cámara, congelar un frame en canvas, dibujar el polígono con clics (tipos: acceso, piscina, borde_piscina, puerta, fuego), guardar con coordenadas normalizadas 0-1. En `puerta`, botón "Capturar referencia (puerta cerrada)" con vista previa.
- **Configuración:** umbrales por anomalía, N y M, cooldown, horario permitido de puertas, URLs de cámaras, armar/desarmar, botón "Probar Telegram".
- **Historial:** tabla filtrable (tipo, fecha, cámara) con miniatura, confianza y latencias; exportar CSV.
- **Calibración:** valores crudos en vivo de cada detector (similitud máxima, % de píxeles de puerta, % capa 1 de fuego, confianza YOLO, ratio y ángulo de caídas, segundos de inmovilidad) y la probabilidad de falsa alarma N de M.

## 10. Modelo de datos (SQLAlchemy + SQLite)

Alinealo con el Anexo D del informe; si agregás campos, anotalos.

- `residente`: id, nombre, creado_en.
- `embedding_rostro`: id, residente_id (FK, borrado en cascada), vector (BLOB float32 de 128), creado_en.
- `camara`: id, nombre, fuente (URL o índice), activa.
- `zona`: id, camara_id, tipo, puntos (JSON normalizado), ruta_referencia (solo puerta).
- `config`: clave, valor (JSON) — sobrescribe a `config.yaml` cuando se edita desde el dashboard.
- `evento`: id, tipo, bit, camara_id, zona, confianza, ts (hora local), ruta_foto, extra (JSON), latencia_panel_ms, latencia_telegram_ms, telegram_ok, silenciado.

## 11. `config.yaml` (esqueleto)

Cada clave con un comentario que explique qué hace y en qué unidad está.

```yaml
general:
  zona_horaria: America/La_Paz
  ancho_proceso: 640
  puerto: 8000
camaras:
  - {id: entrada, fuente: 0}
  - {id: patio, fuente: "http://192.168.0.105:8080/video"}
votacion: {N: 3, M: 5}
cooldown_s: 30
intrusion: {umbral_coseno: 0.363, frames_consecutivos: 5, score_yunet: 0.9}
piscina: {t_sin_supervisor_s: 2, inmovil_px_norm: 0.02, inmovil_s: 8, clases: [0, 15, 16]}
fuego: {modo_capa1: lut, umbral_capa1_pct: 0.5, conf_yolo: 0.5}
caida: {ratio_bbox: 1.4, angulo_max_deg: 45, descenso_pct: 0.20, descenso_s: 1.0, inmovil_s: 5, cada_n_frames: 2, conf_kp: 0.5}
puerta: {metodo: absdiff, umbral_dif: 30, pct_cambio: 0.25, sostenido_s: 2, horario_permitido: ["07:00", "20:00"]}
telegram: {jpeg_calidad: 70, ancho_px: 640, timeout_s: 5, reintentos: 5}
```

## 12. Modo demo, videos sintéticos, evaluación y tests

- `python run.py --demo`: usa los archivos de `data/videos_prueba/` en bucle como si fueran cámaras (y, si no hay, los sintéticos).
- `scripts/generar_video_sintetico.py`: rectángulo que entra en una zona, objeto naranja que parpadea, fondo fijo con cambio brusco tipo puerta. Tienen que disparar el pipeline completo.
- `scripts/evaluar_detector.py`: recorre positivos/negativos, cuenta VP, FP, VN, FN por video, calcula precisión, recall y F1 (`P = VP/(VP+FP)`, `R = VP/(VP+FN)`, `F1 = 2PR/(P+R)`) y escribe en `docs/PRUEBAS.md`. **No inventes resultados**: las métricas las llena el grupo con sus videos.
- Tests pytest mínimos: funciones bitwise sobre matrices chicas con resultado conocido (incluida la cuantización a 9 bits y el no desborde), codificación/decodificación del byte, votación N de M, fórmula binomial, cooldown, horario fuera de rango (incluido el cruce de medianoche), detector de puerta con el video sintético, motor de punta a punta con eventos simulados, endpoints FastAPI con TestClient incluido el WebSocket (alerta → ack → latencia registrada), y Telegram con `requests` mockeado.

## 13. Instalación (hacela vos)

1. Detectá sistema operativo y versión de Python. Usá Python 3.11; si no está, avisá qué falta y seguí con lo que puedas.
2. Creá `.venv`. En Windows y sin GPU, instalá torch CPU antes que ultralytics: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`. No fuerces CUDA.
3. `requirements.txt` con versiones mínimas: ultralytics, opencv-python>=4.10, numpy, supervision, fastapi, uvicorn[standard], jinja2, python-multipart, sqlalchemy, pydantic, pyyaml, python-dotenv, requests, huggingface_hub, psutil, pytest, httpx. Nada más salvo que sea imprescindible.
4. `scripts/descargar_modelos.py` → `models/`: `yolov8n.pt` y `yolov8n-pose.pt` (vía ultralytics), el `.pt` de `rabahdev/fire-smoke-yolov8n` (vía `hf_hub_download`; verificá el nombre real del archivo en el repo), `face_detection_yunet_2023mar.onnx` y `face_recognition_sface_2021dec.onnx` (OpenCV Zoo o sus espejos en Hugging Face `opencv/face_detection_yunet` y `opencv/face_recognition_sface`). Si cambió algún nombre, usá el correcto y documentalo. Los modelos deben quedar locales: en la feria no se depende de internet.
5. `scripts/verificar_entorno.py` en verde, salvo lo que depende del grupo (token de Telegram y URLs de los celulares).

## 14. Fases (al terminar cada una: tests, `--demo`, actualizar PROGRESO.md, `git commit`, seguir)

- **Fase 0 — Base:** git init, estructura, requirements, venv, instalación, modelos, config, verificar_entorno, CLAUDE.md inicial.
- **Fase 1 — Esqueleto de punta a punta:** captura (webcam/URL/archivo), detector de puerta, motor de reglas, WebSocket, panel sonando, Telegram (sin token: solo log), BD de eventos y latencias. Criterio: con el video sintético de la puerta, el panel suena, responde ack y queda el evento con ambas latencias (o la de Telegram en null si no hay token).
- **Fase 2 — Bitwise:** `bitwise.py` completo e integrado, `benchmark.py`, `generar_lut_fuego.py`, `docs/BITWISE.md` con ejemplos numéricos y la tabla del benchmark.
- **Fase 3 — Detectores:** fuego, piscina, caídas y rostros (en ese orden), cada uno con tests y valores crudos para calibración.
- **Fase 4 — Dashboard:** todas las pantallas, editor de zonas, alta de residentes, calibración.
- **Fase 5 — Robustez:** reconexión de cámaras, manejo de errores, cola de Telegram offline, logs claros (archivo rotativo en `data/logs/`), FPS y CPU en el dashboard.
- **Fase 6 — Documentación final:** README, ARQUITECTURA (Mermaid), DECISIONES, PRUEBAS (plantilla), GUIA_GRUPO, `generar_tablas_informe.py`, CLAUDE.md actualizado.
- **Fase 7 — Opcional, SIMD en C:** `nativo/bitwise_simd.c` (XOR y AND con SSE2 y AVX2, con detección de CPU y fallback escalar), compilación con gcc/MinGW, carga con `ctypes`, fila extra en el benchmark y fragmento de ensamblador comentado en BITWISE.md. Si no hay compilador, dejá instrucciones y seguí.

## 15. Coherencia con el informe Word

El informe ya tiene ecuaciones numeradas (tamaño de fotograma, desplazamientos, índice de color, byte de estado, instrucciones SIMD, IoU, ángulo del torso, similitud coseno, regla de fuego, proporción de píxeles, binomial N de M, P/R/F1, latencias) y anexos A-I (byte de estado, código bitwise, parámetros, modelo de datos, protocolo de videos, planillas, recursos, cronograma, consentimiento). Por eso:

- Implementá exactamente esas fórmulas y citá en un comentario a qué concepto del informe corresponde cada una.
- Los valores por defecto de `config.yaml` son los del Anexo C (los de la sección 11 de este documento).
- `generar_tablas_informe.py` produce lo que el grupo pega en el Word: tabla del benchmark, precisión/recall/F1 por detector y latencias (media, p95, máximo, % de eventos < 2 s) para completar la sección 6.2 "Resultados esperados", que hoy dice "Por medir".
- Dejá en GUIA_GRUPO.md qué capturas de pantalla sacar para el futuro Anexo J (panel sonando, en vivo con anotaciones, editor de zonas, calibración, historial, mensaje de Telegram).

## 16. Reglas de trabajo

- Código claro, comentado en español, con type hints; nombres consistentes.
- Ningún umbral hardcodeado.
- Sin hardware, MQTT, Docker ni nube. Dependencias al mínimo.
- Privacidad: de rostros se guardan solo embeddings; el `.env` nunca se commitea.
- Si una decisión no está cubierta, elegí lo más simple que funcione en una demo en vivo y anotalo en DECISIONES.md. Si algo contradice la sección 2, no lo cambies: anotalo y avisá.
- No inventes métricas.
- Al final: resumen corto de lo que funciona, lo que no, y la lista exacta de tareas manuales del grupo (también en GUIA_GRUPO.md).

## 17. CLAUDE.md

Escribilo en la Fase 0 y actualizalo en cada fase: qué es el proyecto (5 líneas, incluida la materia y por qué importa el bitwise), decisiones cerradas (tabla de la sección 2), cómo instalar y correr, estructura, convenciones, dónde está cada umbral, comandos de test, estado actual y problemas conocidos. Tiene que alcanzar para que otra sesión continúe sin preguntar nada.

## 18. Lo que hace el grupo a mano (para GUIA_GRUPO.md)

Python 3.11 y Git en la laptop del proyecto; bot de Telegram con @BotFather, `/start` desde el celular del dueño, `chat_id` vía `getUpdates` (negativo si es un grupo), `.env` y `probar_telegram.py`; celulares con IP Webcam a 640×480, calidad 60-70 %, pantalla siempre encendida, misma WiFi (hotspot de un celular que no sea cámara en la feria), `probar_camara.py`; soportes fijos y cargadores; 3 a 5 fotos por integrante; 5 videos positivos y 5 negativos de 10-20 s por anomalía; dibujar zonas, capturar la referencia de la puerta, calibrar con la luz real, horario de puerta que deje la hora de la feria como "fuera de horario"; probar el panel en el celular/tablet con volumen al máximo; medir al menos 20 eventos por anomalía; maqueta de cartón (80×60 cm, puerta abisagrada, piscina de cartulina, muñeco y mascota, iluminación propia); video de respaldo, póster y guion de 3 minutos.

## 19. Recursos

- Ultralytics: https://github.com/ultralytics/ultralytics
- Fuego/humo: https://huggingface.co/rabahdev/fire-smoke-yolov8n
- YuNet/SFace: https://github.com/opencv/opencv_zoo
- Supervision PolygonZone: https://supervision.roboflow.com/latest/detection/tools/polygon_zone/
- Caídas: https://github.com/shamli1997/SafeGuardian · https://github.com/andmydignity/fall_detection_yolov8s
- Piscina: https://github.com/Nico31415/Drowning-Detector
- Arquitectura de referencia (captura por hilos, eventos): Frigate NVR, https://github.com/blakeblackshear/frigate
- Telegram Bot API (sendPhoto): https://core.telegram.org/bots/api#sendphoto