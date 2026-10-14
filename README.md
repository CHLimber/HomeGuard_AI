# HomeGuard AI

Sistema de seguridad residencial **100 % software** (proyecto de feria, Ingeniería en Sistemas de Información,
UAGRM). Una laptop con Python recibe video de 1 a 3 cámaras (la webcam y celulares con IP Webcam o DroidCam) y
detecta en tiempo real 5 anomalías:

| # | Anomalía | Cómo se detecta |
|---|---|---|
| 1 | Intrusión | Rostro desconocido en la zona "acceso" (YuNet + SFace, similitud coseno con los residentes) |
| 2 | Piscina | Persona o mascota en la piscina sin un adulto en el borde, o alguien inmóvil en el agua (YOLOv8n + ByteTrack) |
| 3 | Fuego / humo | Capa 1 bitwise (color fuego AND movimiento) → capa 2 YOLOv8n fire-smoke |
| 4 | Caída | Pose (YOLOv8n-pose): cuerpo horizontal + descenso brusco + inmovilidad |
| 5 | Puerta | Zona de la puerta distinta de la referencia "cerrada" durante 2 s fuera del horario permitido |

Cuando el motor de reglas confirma una alarma, en paralelo:
1. el **panel de alarma** (`/alarma`, en un celular o tablet) suena con una sirena, parpadea en rojo y vibra;
2. llega una **foto por Telegram** al celular del dueño;
3. queda **registrado en SQLite** con la foto y la latencia medida (objetivo: menos de 2 s).

El preprocesamiento usa **operaciones de bits vectorizadas** (AND, OR, XOR, desplazamientos). Están explicadas en
[docs/BITWISE.md](docs/BITWISE.md) y su impacto se mide en [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Requisitos

- Python **3.11 o 3.12** (ultralytics/torch todavía no siempre soportan la última versión).
- Windows 10/11, Linux o macOS. No hace falta GPU: torch se instala en versión CPU.
- ~2 GB libres (dependencias + modelos). Internet solo para instalar y para Telegram.

## Instalación

### Windows (PowerShell)

```powershell
cd homeguard
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1          # si PowerShell lo bloquea: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\descargar_modelos.py
copy .env.example .env              # y completá TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
python scripts\verificar_entorno.py
```

### Linux / macOS

```bash
cd homeguard
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/descargar_modelos.py
cp .env.example .env                # y completá TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
python scripts/verificar_entorno.py
```

`verificar_entorno.py` tiene que terminar con **0 errores**. Los avisos sobre `.env` o los celulares dependen de
la configuración del grupo ([docs/GUIA_GRUPO.md](docs/GUIA_GRUPO.md)).

## Uso

```bash
python run.py --demo           # sin cámaras: videos sintéticos en bucle (BD aparte: data/homeguard_demo.db)
python run.py                  # cámaras reales definidas en config.yaml
python run.py --sin-telegram   # no envía nada a Telegram (solo log)
python run.py --puerto 8001    # otro puerto
```

Al arrancar se muestran las direcciones:

- **Dashboard:** `http://localhost:8000/en-vivo` (en la laptop)
- **Panel de alarma:** `http://IP-DE-LA-LAPTOP:8000/alarma` (en el celular o tablet, en la misma red Wi-Fi).
  Tocá **ARMAR ALARMA** para habilitar el sonido.

| Página | Para qué |
|---|---|
| En vivo | Video de cada cámara con zonas y detecciones dibujadas, semáforo de las 5 anomalías, FPS, CPU y RAM |
| Calibración | Valores crudos de cada detector (similitud, % de píxeles, ratio, ángulo…) al lado de su umbral |
| Zonas | Dibujar polígonos sobre un frame congelado y capturar la referencia de la puerta cerrada |
| Residentes | Registrar personas de la casa con 3 a 5 fotos (se guarda solo el vector del rostro) |
| Configuración | URLs de cámaras, umbrales, probar Telegram |
| Historial | Eventos con foto, confianza y latencias; exportar CSV |

Todos los umbrales están en [`config.yaml`](config.yaml), comentados. Lo que se cambia desde el dashboard se guarda
en la base de datos y se aplica encima de `config.yaml`. El botón **Restaurar config.yaml** lo deshace.

## Scripts

| Comando | Qué hace |
|---|---|
| `python scripts/verificar_entorno.py [--cargar-modelos] [--sin-camaras]` | Revisa Python, paquetes, modelos, cámaras, puerto y Telegram |
| `python scripts/descargar_modelos.py` | Descarga los 5 modelos a `models/` |
| `python scripts/probar_camara.py 0` · `... http://IP:8080/video` | Abre una cámara y muestra sus FPS |
| `python scripts/probar_telegram.py [--obtener-chat-id]` | Envía un mensaje y una foto de prueba / muestra tu chat id |
| `python scripts/generar_video_sintetico.py` | Genera los videos sintéticos de prueba |
| `python scripts/evaluar_detector.py --detector fuego --carpeta data/videos_prueba/fuego` | VP/FP/VN/FN con tus videos → `docs/PRUEBAS.md` |
| `python scripts/reporte_latencias.py` | Latencias medidas en los eventos → `docs/PRUEBAS.md` |
| `python -m homeguard.preproceso.benchmark` | Benchmark bitwise → `docs/BENCHMARK.md` |

## Tests

```bash
python -m pytest -q
```

Cubren las funciones bitwise, el byte de estado, la votación N de M, el cooldown, los 5 detectores (con los videos
sintéticos y modelos simulados), el motor de punta a punta, la API, el WebSocket con ack y latencia, la reconexión
de cámaras, la cola de Telegram sin internet y el evaluador.

## Problemas frecuentes

- **El celular no abre el panel:** la laptop y el celular tienen que estar en la misma red. En Windows, aceptá el
  aviso del firewall para Python en "redes privadas" (o marcá la red Wi-Fi como privada). Usar el hotspot de un
  celular suele ser lo más simple en una feria.
- **El panel no suena:** hay que tocar **ARMAR ALARMA** cada vez que se abre la página (política de autoplay de los
  navegadores) y tener el volumen alto. El botón **Probar sirena** sirve para verificarlo.
- **No vibra / la pantalla se apaga:** la vibración y el bloqueo de pantalla pueden no funcionar en Android si la
  página se abre por IP sin HTTPS. Poné el tiempo de pantalla del dispositivo en "nunca". Ver la guía del grupo.
- **Cámara del celular "sin señal":** revisá la URL (IP Webcam: `http://IP:8080/video`, DroidCam:
  `http://IP:4747/video`) con `scripts/probar_camara.py`. DroidCam acepta un solo cliente a la vez.
- **Va lento:** bajá `procesamiento.fps_objetivo` o `procesamiento.imgsz_yolo`, o subí `detectores.caidas.cada_n_frames`.

## Documentación

- [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md): diagramas y explicación de cada módulo
- [docs/DECISIONES.md](docs/DECISIONES.md): decisiones técnicas y su porqué
- [docs/BITWISE.md](docs/BITWISE.md): operaciones de bits con ejemplos numéricos
- [docs/PRUEBAS.md](docs/PRUEBAS.md): protocolo y resultados de las pruebas (los completa el grupo)
- [docs/GUIA_GRUPO.md](docs/GUIA_GRUPO.md): lo que el grupo tiene que hacer a mano
- [docs/PROGRESO.md](docs/PROGRESO.md): estado del desarrollo y problemas conocidos
