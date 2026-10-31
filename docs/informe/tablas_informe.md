# Tablas para el informe (sección 6.2 "Resultados esperados")

_Generado por `scripts/generar_tablas_informe.py` el 31/10/2026 18:24. Latencias: 0 eventos (0 con ack del panel) de `homeguard.db`. "Por medir" = todavía no hay datos medidos._

## Tabla 1. Benchmark del preprocesamiento bitwise (frame 640×480)

| Variante | Descripción | ms/frame (mediana) | FPS equivalentes | Aceleración vs. A |
|---|---|---:|---:|---:|
| A | Bucle Python píxel a píxel (línea base) | 117,132 | 8,5 | 1,0x |
| B | OpenCV clásico sin ROI (HSV + absdiff) | 0,996 | 1004,0 | 117,6x |
| B2 | OpenCV clásico con ROI (HSV + absdiff) | 0,276 | 3620,6 | 424,1x |
| C | Bits sin ROI (AND, XOR, >>, \|, LUT) | 3,594 | 278,2 | 32,6x |
| D | Bits con ROI (recorte + AND + XOR + LUT) — HomeGuard | 1,459 | 685,3 | 80,3x |

## Tabla 2. Precisión, recall y F1 por detector

| Detector | Videos | VP | FP | VN | FN | Precisión | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Intrusión (rostros) | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir |
| Piscina | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir |
| Fuego / humo | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir |
| Caídas | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir |
| Puerta | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir | Por medir |

## Tabla 3. Latencias de las alertas

| Medición | Eventos | Media (ms) | P95 (ms) | Máximo (ms) | % ≤ 2,0 s |
|---|---:|---:|---:|---:|---:|
| Detección → panel | 0 | Por medir | Por medir | Por medir | Por medir |
| Detección → Telegram | 0 | Por medir | Por medir | Por medir | Por medir |
