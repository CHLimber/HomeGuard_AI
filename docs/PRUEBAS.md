# Pruebas y métricas

> **Este documento lo completa el grupo con sus propios videos.** No hay resultados inventados: las secciones
> marcadas con `<!-- ...:INICIO -->` / `<!-- ...:FIN -->` las reescriben automáticamente
> `scripts/evaluar_detector.py` y `scripts/reporte_latencias.py`.

## 1. Pruebas automáticas (código)

```bash
python -m pytest -q
```

No necesitan cámaras ni modelos (usan videos sintéticos y modelos simulados). Ver la lista de casos en
`tests/`. Cubren: funciones bitwise, byte de estado, votación N de M, cooldown, los 4 detectores, el motor de punta a
punta, la API y el WebSocket (con ack y latencia), la reconexión de cámaras, la cola de Telegram sin internet y el
evaluador.

## 2. Protocolo para los videos de prueba

Para cada anomalía, grabá con **la misma cámara y el mismo encuadre que vas a usar en la feria**:

- `data/videos_prueba/<anomalía>/positivos/`: videos donde **sí** ocurre la anomalía (mínimo 10).
- `data/videos_prueba/<anomalía>/negativos/`: situaciones **parecidas** donde **no** debe sonar (mínimo 10).
- De 10 a 30 segundos cada uno, en `.mp4`. Variá la iluminación, la ropa, la distancia y quién actúa.
- Si la anomalía usa zonas, poné al lado de cada video un `<video>.zonas.json` o usá `--zonas-de <cámara>`.
  Ver el encabezado de `scripts/evaluar_detector.py`.

| Anomalía | Positivos (ejemplos) | Negativos (ejemplos) |
|---|---|---|
| intrusión | persona NO registrada mira a la cámara en la zona de acceso | residentes registrados entrando; persona de espaldas |
| fuego | vela/encendedor/fogata en la zona (con cuidado), video de fuego real en una pantalla | objeto naranja quieto, luz cálida, persona con ropa naranja moviéndose |
| caída | caída sobre colchoneta y quedarse quieto > 5 s | sentarse, agacharse, acostarse despacio, caer y levantarse enseguida |
| puerta | abrir la puerta y dejarla abierta > 2 s | puerta cerrada con gente pasando delante; cambio de luz |

Evaluación de cada detector:

```bash
python scripts/evaluar_detector.py --detector rostros --carpeta data/videos_prueba/intrusion --zonas-de celular1
python scripts/evaluar_detector.py --detector fuego   --carpeta data/videos_prueba/fuego
python scripts/evaluar_detector.py --detector caidas  --carpeta data/videos_prueba/caida
python scripts/evaluar_detector.py --detector puerta  --carpeta data/videos_prueba/puerta    --zonas-de celular1
```

Definiciones: **VP** = positivo que disparó · **FN** = positivo que no disparó · **FP** = negativo que disparó ·
**VN** = negativo que no disparó. **Precisión** = VP / (VP + FP) (de las alarmas, cuántas eran reales).
**Recall** = VP / (VP + FN) (de las situaciones reales, cuántas detectó).

## 3. Resultados por detector

### Intrusión (rostros)
<!-- rostros:INICIO -->
_Pendiente: ejecutar `scripts/evaluar_detector.py --detector rostros ...`._
<!-- rostros:FIN -->

### Fuego / humo
<!-- fuego:INICIO -->
_Pendiente: ejecutar `scripts/evaluar_detector.py --detector fuego ...`._
<!-- fuego:FIN -->

### Caídas
<!-- caidas:INICIO -->
_Pendiente: ejecutar `scripts/evaluar_detector.py --detector caidas ...`._
<!-- caidas:FIN -->

### Puerta
<!-- puerta:INICIO -->
_Pendiente: ejecutar `scripts/evaluar_detector.py --detector puerta ...`._
<!-- puerta:FIN -->

## 4. Latencias (requisito: < 2 s)

Se miden solas en cada evento real: **detección → panel** (ack del panel) y **detección → Telegram** (respuesta OK
de la API). Después de una sesión de pruebas con el panel abierto y Telegram configurado:

```bash
python scripts/reporte_latencias.py               # eventos reales
python scripts/reporte_latencias.py --demo        # eventos del modo demo
```

<!-- latencias:INICIO -->
_Pendiente: ejecutar `scripts/reporte_latencias.py` después de una sesión de pruebas con el panel y Telegram._
<!-- latencias:FIN -->

Referencia medida durante el desarrollo (laptop y panel en la misma máquina, sin Telegram): detección → panel entre
4 y 18 ms en `--demo`. **En la feria hay que medir con el celular real por Wi-Fi.**

## 5. Rendimiento

| Medición | Dónde se ve |
|---|---|
| FPS de captura y de análisis por cámara, ms por frame | Dashboard → En vivo |
| CPU del sistema y del proceso, RAM | Dashboard → En vivo |
| ms por detector | Dashboard → Calibración |
| Impacto de las operaciones bitwise | [BENCHMARK.md](BENCHMARK.md) (`python -m homeguard.preproceso.benchmark`) |

Anotar acá los valores en la laptop de la feria, con todas las cámaras conectadas:

| Cámaras activas | FPS análisis por cámara | CPU HomeGuard | RAM |
|---|---|---|---|
| | | | |

## 6. Prueba de punta a punta en la feria (manual)

| # | Prueba | Resultado esperado | ¿OK? |
|---|---|---|---|
| 1 | Abrir `/alarma` en la tablet y tocar ARMAR | Pitido corto; indicador "Conectado" | |
| 2 | Probar sirena | Suena 2 s | |
| 3 | Disparar cada anomalía frente a su cámara | Panel rojo + sirena + vibración; foto en Telegram | |
| 4 | SILENCIAR | Se apaga en el panel y en el dashboard | |
| 5 | Desenchufar el Wi-Fi del celular cámara 30 s | "sin señal" y reconexión sola al volver | |
| 6 | Cortar internet y disparar una alarma | El panel suena igual; Telegram llega al volver internet | |
| 7 | Cerrar y reabrir el panel | Reconecta y muestra el estado actual | |

## 7. Medición con videos de internet (16/11/2026)

Hecha por fuera del protocolo de la sección 2 (no son videos del grupo ni de la cámara de la feria), con los videos
que estaban subidos en «Prueba con video». Sirve para comparar antes/después de las decisiones nº 55 y 56, **no**
reemplaza la medición con videos propios.

### Caídas (pose real, YOLOv8n-pose)

Compilación A: 12 clips de caídas de cámaras de timbre (2 a 6 s cada uno) y un tramo de 6,5 s sin caída.
Compilación B: 10 minutos de clips variados de caídas, sin etiquetar; cada alarma se revisó mirando el video.

| Medida | Antes | Después |
|---|---:|---:|
| A: caídas reconocidas (hubo descenso y quedó en el suelo) | 1 / 12 | 11 / 12 |
| A: alarma confirmada, repitiendo la última pose 4 s | 1 / 12 | 11 / 12 |
| A: alarma confirmada tal cual está el video | 0 / 12 | 0 / 12 |
| A: alarmas en el tramo sin caída | 0 | 0 |
| B: caídas distintas con alarma | 2 | 18 (15 reales, 1 dudosa, 2 falsas) |

- Tal cual está el video A no confirma ninguna: los clips se cortan 1 a 3 s después de la caída y la regla pide 3 s
  de inmovilidad. Para mostrar compilaciones así en «Prueba con video» hay que bajar `inmovil_tiempo_s`.
- B, falsas: una nace de un corte de escena (persona de pie en un clip, agachada en el siguiente) y otra de un
  adulto que se inclina junto a una niña sentada. Dudosa: una niña que cae y se levanta enseguida.
- No se contaron todas las caídas de B, así que de ese video no hay recall.
- La única caída de A que no reconoce es una persona que camina alejándose de la cámara y cae lejos, detrás de
  una reja.

### Fuego / humo

4 videos de incendios (ensayos NIST y otros) y 3 sin fuego (anuncio con una esfera naranja, living con luz cálida
filmado con el celular en la mano, compilación de caídas en exteriores).

| | VP | FP | VN | FN | Precisión | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Antes | 3 | 2 | 1 | 1 | 0,60 | 0,75 |
| Después (`confianza_humo: 0.70`) | 3 | 0 | 3 | 1 | 1,00 | 0,75 |

El incendio que falta es una llama blanca/azulada tapada por humo: la capa 1 (color naranja) no se activa.

### Puerta (banco sintético)

No hay videos de una puerta real, así que se midió con 15 videos **sintéticos** de 12 s (la misma puerta dibujada
de `scripts/generar_video_sintetico.py`, con variaciones), zona sobre la puerta y referencia automática (primer
frame). Mide la lógica del detector, no cómo se ve una puerta de verdad. Los dos métodos (`absdiff` y `xor`) dan
el mismo resultado en los 15.

| | VP | FP | VN | FN | Precisión | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Antes | 5 | 2 | 6 | 2 | 0,71 | 0,71 | 0,71 |
| Después (`compensar_iluminacion: true`, decisión nº 57) | 5 | 1 | 7 | 2 | 0,83 | 0,71 | 0,77 |

| Escenario | Esperado | Resultado | 1.ª alarma (s) |
|---|---|---|---:|
| Abre del todo a los 4 s, 5 s abierta | alarma | **VP** | 6,0 |
| Abre a medias (50 % de la hoja) | alarma | **VP** | 6,0 |
| Abre un tercio (33 %) | alarma | **VP** | 6,0 |
| Abre despacio (2 s en abrirse) | alarma | **VP** | 6,5 |
| Abierta solo 3 s | alarma | **VP** | 6,0 |
| Abre con poca luz (toda la escena 60 niveles más oscura) | alarma | **FN** | |
| Abre y lo que se ve detrás tiene un gris parecido al de la hoja | alarma | **FN** | |
| Siempre cerrada | nada | **VN** | |
| Una persona pasa por delante (2 s) | nada | **VN** | |
| Abierta solo 1 s (menos que `duracion_min_s`) | nada | **VN** | |
| La luz cambia de a poco (+25 niveles en 6 s) | nada | **VN** | |
| La cámara tiembla (±3 px) | nada | **VN** | |
| Ruido fuerte de sensor (±18 niveles) | nada | **VN** | |
| Se apaga una luz (−45 niveles de golpe) | nada | antes **FP**, ahora **VN** | |
| Una persona se queda parada delante de la puerta 5 s | nada | **FP** | 6,0 |

- La alarma llega 2,0 s después de abrir (`duracion_min_s`), 2,5 s si la puerta se abre despacio. El detector
  tarda unos 2 ms por frame.
- **Lo que falla es propio de comparar con una referencia:** si la puerta abierta se parece a la cerrada (poca
  luz, o un fondo del mismo tono) la diferencia no llega a `umbral_diferencia` (30); y cualquier cosa que tape la
  puerta más de 2 s cuenta como cambio. Para la feria: capturar la referencia con la luz del lugar, elegir una
  puerta que contraste con lo que hay detrás y, si hace falta, bajar `umbral_diferencia`.

### Intrusión

Sin medir: no hay videos de rostros ni residentes registrados.
