# Progreso de HomeGuard AI

| Fase | Estado |
|---|---|
| 0 — Base (repo, venv, modelos, config, verificar_entorno) | ✅ hecha |
| 1 — Esqueleto de punta a punta | ✅ hecha |
| 2 — Bitwise + benchmark | ✅ hecha |
| 3 — Detectores (fuego, piscina, caídas, rostros) | ✅ hecha |
| 4 — Dashboard | ⏳ pendiente |
| 5 — Robustez | ⏳ pendiente |
| 6 — Documentación final | ⏳ pendiente |

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

## Problemas conocidos
- El video sintético de fuego (elipses naranjas) activa la capa 1 pero el YOLO fire-smoke no lo reconoce como
  fuego (esperable): para ver una alarma de fuego real hace falta un video de una llama real.
- El rectángulo del video sintético "zona" no es una persona para YOLO: en `--demo` la piscina no dispara;
  sus reglas se prueban en los tests con detecciones simuladas.
- `sv.ByteTrack` está deprecado en supervision 0.28+ y se elimina en 0.31 → `requirements.txt` fija `<0.31`.
