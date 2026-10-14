# CLAUDE.md — HomeGuard AI

## Qué es
Sistema de seguridad residencial 100 % software (proyecto UAGRM, feria). Una laptop con Python
recibe video de 1–3 cámaras (webcam + celulares con IP Webcam/DroidCam) y detecta 5 anomalías:
intrusión (rostro desconocido), piscina, fuego/humo, caída y puerta abierta fuera de horario.
Al confirmar una alarma: WebSocket al panel `/alarma` (sirena Web Audio), foto por Telegram y
registro en SQLite con latencias (requisito < 2 s). Preproceso con operaciones bitwise vectorizadas.

## Instalar y correr
```bash
py -3.12 -m venv .venv            # Linux/macOS: python3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python scripts/descargar_modelos.py
.venv/Scripts/python scripts/verificar_entorno.py
.venv/Scripts/python run.py --demo          # videos sintéticos en bucle
.venv/Scripts/python run.py                 # cámaras reales de config.yaml
```

## Tests
`.venv/Scripts/python -m pytest -q`

## Estado actual
Ver `docs/PROGRESO.md` (fases 0–6). Al terminar cada fase: tests, `run.py --demo`, actualizar
PROGRESO.md y este archivo, `git commit`.

## Convenciones
- Código y comentarios en español, type hints. Sin bucles píxel a píxel (salvo línea base del benchmark).
- Ningún umbral hardcodeado: todo en `config.yaml` (comentado) y validado en `homeguard/config.py`.
- Commits sin líneas de atribución a Claude.
