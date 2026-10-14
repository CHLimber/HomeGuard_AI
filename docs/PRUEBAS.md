# Pruebas y métricas

> **Este documento lo completa el grupo con sus propios videos.** No hay resultados inventados: las secciones
> marcadas con `<!-- ...:INICIO -->` / `<!-- ...:FIN -->` las reescriben automáticamente
> `scripts/evaluar_detector.py` y `scripts/reporte_latencias.py`.

## 1. Pruebas automáticas (código)

```bash
python -m pytest -q
```

No necesitan cámaras ni modelos (usan videos sintéticos y modelos simulados). Ver la lista de casos en
`tests/`. Cubren: funciones bitwise, byte de estado, votación N de M, cooldown, los 5 detectores, el motor de punta a
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
| piscina | niño/muñeco o mascota en la zona sin adulto en el borde; persona quieta > 10 s en el agua | adulto en el borde mientras alguien está en el agua; nadie en la piscina |
| fuego | vela/encendedor/fogata en la zona (con cuidado), video de fuego real en una pantalla | objeto naranja quieto, luz cálida, persona con ropa naranja moviéndose |
| caída | caída sobre colchoneta y quedarse quieto > 5 s | sentarse, agacharse, acostarse despacio, caer y levantarse enseguida |
| puerta | abrir la puerta y dejarla abierta > 2 s | puerta cerrada con gente pasando delante; cambio de luz |

Evaluación de cada detector:

```bash
python scripts/evaluar_detector.py --detector rostros --carpeta data/videos_prueba/intrusion --zonas-de celular1
python scripts/evaluar_detector.py --detector piscina --carpeta data/videos_prueba/piscina   --zonas-de celular2
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

### Piscina
<!-- piscina:INICIO -->
_Pendiente: ejecutar `scripts/evaluar_detector.py --detector piscina ...`._
<!-- piscina:FIN -->

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
