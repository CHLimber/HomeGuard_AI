# Progreso de HomeGuard AI

| Fase | Estado |
|---|---|
| 0 — Base (repo, venv, modelos, config, verificar_entorno) | ✅ hecha |
| 1 — Esqueleto de punta a punta | ⏳ pendiente |
| 2 — Bitwise + benchmark | ⏳ pendiente |
| 3 — Detectores (fuego, piscina, caídas, rostros) | ⏳ pendiente |
| 4 — Dashboard | ⏳ pendiente |
| 5 — Robustez | ⏳ pendiente |
| 6 — Documentación final | ⏳ pendiente |

## Fase 0
- Python 3.12.10 en `.venv` (no había 3.11 instalado; 3.12 está soportado por ultralytics/torch).
- Versiones instaladas: torch 2.14.1+cpu, ultralytics 8.4.177, opencv-python 5.0.0, supervision 0.30.9, numpy 2.5.4, fastapi 0.143.
- Modelos descargados en `models/` (nombres verificados en Hugging Face, coinciden con los pedidos; `best.pt` se guarda como `fire_smoke_yolov8n.pt`).
- `scripts/verificar_entorno.py --cargar-modelos`: 32 OK, 0 errores; avisos solo por `.env` y celulares.

## Problemas conocidos
- `sv.ByteTrack` está deprecado en supervision 0.28+ y se elimina en 0.31 → `requirements.txt` fija `<0.31`.
