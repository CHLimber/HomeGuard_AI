# Progreso de HomeGuard AI

| Fase | Estado |
|---|---|
| 0 — Base (repo, venv, modelos, config, verificar_entorno) | ✅ hecha |
| 1 — Esqueleto de punta a punta | ✅ hecha |
| 2 — Bitwise + benchmark | ✅ hecha |
| 3 — Detectores (fuego, piscina, caídas, rostros) | ✅ hecha |
| 4 — Dashboard | ✅ hecha |
| 5 — Robustez | ✅ hecha |
| 6 — Documentación final | ✅ hecha |

## Fase 0
- Python 3.12.10 en `.venv` (no había 3.11 instalado; 3.12 está soportado por ultralytics/torch).
- Versiones instaladas: torch 2.14.1+cpu, ultralytics 8.4.177, opencv-python 5.0.0, supervision 0.30.9, numpy 2.5.4, fastapi 0.143.
- Modelos descargados en `models/` (nombres verificados en Hugging Face, coinciden con los pedidos; `best.pt` se guarda como `fire_smoke_yolov8n.pt`).
- `scripts/verificar_entorno.py --cargar-modelos`: 32 OK, 0 errores; avisos solo por `.env` y celulares.

## Fase 1
- Captura por hilos (webcam/URL/archivo en bucle) con reconexión; pipeline en un hilo; FastAPI en el principal.
- Detector de puerta (absdiff o XOR de binarizadas), motor de reglas (N de M, cooldown, byte de estado, silenciar).
- Panel `/alarma`: botón ARMAR (desbloquea audio), sirena Web Audio 600→1200 Hz, parpadeo rojo, vibración, ack, SILENCIAR, reconexión.
- Telegram en cola con reintentos (sin token: solo log). Eventos en SQLite con foto y latencias.
- Verificado con `run.py --demo` + panel WebSocket simulado: la puerta sintética dispara a los ~6 s del video
  (4 s apertura + 2 s sostenido); latencia detección→panel medida: 4,5–6 ms en localhost.
- 23 tests OK.

## Fase 2
- `bitwise.py`: ROI (AND), unión de zonas (OR), movimiento (XOR de cuantizados), cuantización (AND con máscara de
  bits altos ≡ `(x>>s)<<s`), índice RGB332 (`&`, `>>`, `|`) + `cv2.LUT`, XOR de binarizadas (puerta).
- Integrado: el analizador calcula la máscara de movimiento XOR en cada frame; la puerta usa AND/XOR.
- `python -m homeguard.preproceso.benchmark` → `docs/BENCHMARK.md` + `docs/benchmark.csv` (5 variantes).
  Resultado real: vectorizar ≈ 200x, ROI ≈ 3x; a igual área el HSV nativo de OpenCV es algo más rápido
  que la LUT RGB332 (documentado tal cual en `docs/BITWISE.md`).
- 35 tests OK.

## Fase 3
- Fuego: capa 1 (RGB332+LUT AND movimiento XOR AND zona) → capa 2 YOLO fire-smoke solo si capa 1 supera el umbral.
- Piscina: YOLO general + ByteTrack + PolygonZone; reglas (a) sin supervisor en el borde y (b) tracker inmóvil.
- Caídas: YOLOv8n-pose cada N frames; ratio + ángulo de torso + descenso brusco + inmovilidad (asociación por cercanía).
- Rostros: YuNet + SFace, solo si YOLO ve una persona en la zona "acceso"; similitud coseno vs residentes.
- Página `/calibracion` con los valores crudos de cada detector junto a su umbral (en rojo si lo supera).
- Verificado con modelos reales sobre una foto (example_outputs/largest_selfie.jpg del repo de YuNet):
  11 rostros; mismo rostro espejado/con otro brillo → similitud 0,954; rostros distintos → 0,07–0,20.
- Demo: 3 cámaras a 9,2 FPS cada una; YOLO ≈ 35 ms/frame en esta CPU.
- 56 tests OK (detectores con modelos simulados a partir de la verdad de terreno de los videos sintéticos).

## Fase 4
- Páginas: En vivo (MJPEG anotado + semáforo + CPU/RAM/FPS), Calibración, Zonas (editor de polígonos sobre un
  frame congelado + captura de referencia de puerta), Residentes (alta con 3-5 fotos → solo embeddings), Configuración
  (cámaras, probar Telegram, umbrales generados desde config.yaml con sus comentarios como ayuda), Historial
  (filtros, miniaturas, latencias en verde/rojo vs 2 s, exportación CSV).
- Cambios de configuración desde el dashboard: se guardan como overrides en la tabla `config` y se aplican en caliente
  (motor de reglas, cámaras, detectores). "Restaurar config.yaml" los borra.
- Verificado: alta real de residente con YuNet+SFace vía API; capturas de todas las páginas con Edge headless.
- 62 tests OK.

## Fase 5
- Cámaras: reconexión con espera exponencial (probado: la fuente aparece después y se conecta sola); el stream
  muestra "sin señal" si el último frame tiene más de 3 s.
- Telegram: cola en hilo propio, reintentos sin internet, errores permanentes (token/chat inválido) sin reintento,
  descarte de eventos viejos, re-encolado de pendientes al arrancar. Encolar nunca bloquea.
- Errores: un detector que falla no frena a los demás (log limitado a 1 cada 10 s); el hilo de procesamiento
  sobrevive a cualquier excepción; mensaje claro si el puerto está ocupado.
- Consola UTF-8 en todos los scripts (Windows usa cp1252 al redirigir la salida).
- `scripts/evaluar_detector.py` (VP/FP/VN/FN, precisión, recall, F1 → docs/PRUEBAS.md) y
  `scripts/reporte_latencias.py` (promedio, mediana, P95, % bajo 2 s → docs/PRUEBAS.md).
- Consultas de BD compartidas en `homeguard/db/consultas.py`.
- 73 tests OK.

## Fase 6
- README (instalación Windows y Linux/macOS, uso, scripts, problemas frecuentes), ARQUITECTURA (Mermaid: componentes,
  secuencia de una alarma, modelo de datos), DECISIONES (38 decisiones con su porqué), PRUEBAS (protocolo +
  secciones que llenan los scripts, sin resultados inventados), GUIA_GRUPO (pasos manuales), CLAUDE.md completo.

## Pendiente (lo hace el grupo, ver GUIA_GRUPO.md)
- `.env` con TELEGRAM_TOKEN y TELEGRAM_CHAT_ID → `scripts/probar_telegram.py`.
- URLs de los celulares (IP Webcam/DroidCam) y activarlos en config.yaml o en el dashboard.
- Dibujar zonas por cámara y capturar la referencia de la puerta cerrada.
- Registrar residentes (3–5 fotos c/u).
- Grabar videos positivos/negativos por anomalía → `scripts/evaluar_detector.py` → docs/PRUEBAS.md.
- Sesión con panel + Telegram → `scripts/reporte_latencias.py`.
- Calibrar umbrales con la página Calibración, en la casa y en la feria.
- Re-ejecutar el benchmark en la laptop de la feria.

## Problemas conocidos
- El video sintético de fuego (elipses naranjas) activa la capa 1 pero el YOLO fire-smoke no lo reconoce como
  fuego (esperable): para ver una alarma de fuego real hace falta un video de una llama real.
- El rectángulo del video sintético "zona" no es una persona para YOLO: en `--demo` la piscina no dispara;
  sus reglas se prueban en los tests con detecciones simuladas.
- Vibración y wake lock pueden no funcionar en Android por `http://IP` sin HTTPS (workaround en GUIA_GRUPO).
- La latencia al panel se mide con el ack: incluye el viaje de vuelta (cota superior).
- `sv.ByteTrack` está deprecado en supervision 0.28+ y se elimina en 0.31 → `requirements.txt` fija `<0.31`.
