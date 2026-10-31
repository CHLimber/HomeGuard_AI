# Operaciones de bits en HomeGuard AI

Este documento explica cada operación de bits que usa el sistema, con ejemplos numéricos, dónde está
en el código y cuánto aporta. El código está en `homeguard/preproceso/bitwise.py` y el estado de
alarma en `homeguard/reglas/estado.py`.

**Regla general:** ninguna operación se hace con un bucle de Python píxel a píxel. Se aplican a la
matriz completa de una vez (NumPy u OpenCV, implementados en C con instrucciones SIMD). El único
bucle píxel a píxel es la variante A del benchmark, que sirve de línea base.

## Repaso: un píxel es un byte

Una imagen en gris de 640x480 es una matriz de 307 200 bytes (`uint8`, valores 0–255). Un byte
tiene 8 bits:

```
valor 182  =  1 0 1 1 0 1 1 0
bit:          7 6 5 4 3 2 1 0     (el bit 7 vale 128, el bit 0 vale 1)
              └─ más significativos (MSB) ─┘ └─ menos significativos (LSB) ─┘
```

Los bits altos llevan la información gruesa (claro/oscuro). Los bits bajos cambian con el ruido del
sensor aunque la escena esté quieta.

Las **máscaras** del sistema valen 0 (`0000 0000`) o 255 (`1111 1111`), y no 0/1, para poder
combinarlas bit a bit:

```
x AND 255 = x      (1111 1111 deja pasar todos los bits)
x AND 0   = 0      (0000 0000 los apaga todos)
```

---

## 1. AND: región de interés (ROI) y combinación de máscaras

**Dónde:** `aplicar_mascara`, `combinar_mascaras(modo="and")`, `porcentaje_activos`.

Cada zona dibujada en el dashboard (puerta, piscina, cocina…) se convierte una sola vez en una
máscara 0/255. Después, un AND la aplica a cualquier frame:

```
píxeles:  [ 10   20 ]      máscara: [ 255   0 ]      AND →  [ 10   0 ]
          [ 30   40 ]               [   0 255 ]             [  0  40 ]

20 AND 0   = 0001 0100 AND 0000 0000 = 0000 0000 = 0
40 AND 255 = 0010 1000 AND 1111 1111 = 0010 1000 = 40
```

El AND también **combina condiciones**. En el detector de fuego, un píxel cuenta solo si cumple las
tres a la vez:

```
color_fuego AND movimiento AND zona
   255      AND    255     AND 255  = 255  → cuenta
   255      AND      0     AND 255  =   0  → no cuenta (objeto naranja quieto: no es llama)
```

## 2. OR: unir zonas y armar índices

**Dónde:** `mascara_roi` (une polígonos), `indice_rgb332`, byte de estado.

```
zona A: [255   0   0]
zona B: [  0   0 255]
A OR B: [255   0 255]
```

## 3. XOR: detectar cambios

**Dónde:** `mascara_movimiento_xor` (movimiento entre frames), `xor_binarizadas` (detector de puerta, método `xor`).

`a XOR b` da 0 si y solo si `a == b`. Cada bit encendido del resultado marca un bit que cambió.

```
100 XOR 100 = 0110 0100 XOR 0110 0100 = 0000 0000 = 0     (no cambió)
100 XOR 200 = 0110 0100 XOR 1100 1000 = 1010 1100 = 172   (cambió → ≠ 0)
```

**Puerta (método xor):** se binariza la referencia (puerta cerrada) y el frame actual con el mismo
umbral, y el XOR marca los píxeles que pasaron de claro a oscuro o al revés:

```
referencia binarizada: [255 255   0]
actual binarizada:     [255   0   0]
XOR:                   [  0 255   0]   → 1 de 3 píxeles cambiados = 33 %
```

## 4. Desplazamientos (>>, <<) y cuantización

**Dónde:** `cuantizar`, `cuantizar_desplazando`, `mascara_bits_altos`, `indice_rgb332`.

Correr a la derecha `s` lugares divide por 2^s y descarta los bits bajos. Volver a correr a la
izquierda los rellena con ceros:

```
182 >> 4 = 1011 0110 >> 4 = 0000 1011 = 11
11  << 4 = 0000 1011 << 4 = 1011 0000 = 176
```

`(x >> 4) << 4` equivale a `x AND 1111 0000`. La máscara se construye con un desplazamiento:
`(0xFF << 4) & 0xFF = 0xF0`. El código usa la versión con un solo AND, que es más rápida, y el test
`test_cuantizar_and_igual_a_desplazamientos` verifica que las dos dan exactamente lo mismo para
todos los valores de `bits`.

### Movimiento = XOR de frames cuantizados

Si se hiciera XOR de los frames crudos, el ruido del sensor (±3 niveles) marcaría movimiento en todos
lados. Al cuantizar primero, se comparan solo los 4 bits altos (`preproceso.bits_movimiento`):

```
ruido:  100 → 103    0110 0100 → 0110 0111    AND 0xF0: 0110 0000 vs 0110 0000 → XOR = 0   ✔ ignorado
cambio: 100 → 200    0110 0100 → 1100 1000    AND 0xF0: 0110 0000 vs 1100 0000 → XOR ≠ 0   ✔ movimiento
```

Después una **apertura morfológica** (`preproceso.apertura_movimiento_px`) borra los píxeles sueltos
que quedan cerca del límite entre dos niveles.

## 5. Índice de color RGB332 + tabla de búsqueda (LUT)

**Dónde:** `indice_rgb332`, `construir_lut_fuego`, `mascara_color_lut` y la capa 1 del detector de fuego.

Un color BGR ocupa 3 bytes (16,7 millones de combinaciones). Se empaquetan sus bits más
significativos en **un solo byte**, el formato RGB332 (3 bits de rojo, 3 de verde y 2 de azul):

```
índice = (R AND 1110 0000) OR ((G AND 1110 0000) >> 3) OR (B >> 6)
            RRR0 0000              000G GG00             0000 00BB
```

Ejemplo, naranja BGR = (0, 140, 255):

```
R = 255 = 1111 1111 → AND 1110 0000            = 1110 0000 = 224
G = 140 = 1000 1100 → AND 1110 0000 = 1000 0000 → >> 3 = 0001 0000 = 16
B =   0 = 0000 0000 → >> 6                      = 0000 0000 = 0
índice = 224 OR 16 OR 0 = 1111 0000 = 240
```

Como el índice tiene solo 256 valores posibles, al arrancar se precalcula una **tabla de 256
entradas** con la respuesta a "¿este color es fuego?". La regla HSV de `config.yaml` (`hue_min`,
`hue_max`, `sat_min`, `val_min`) se evalúa una vez sobre el color central de cada celda. Después,
clasificar un frame completo es una sola búsqueda por píxel: `cv2.LUT(indice, tabla)`.

```
tabla[240] = 255   (naranja → fuego)
tabla[3]   = 0     (azul    → no)
```

Ventaja: la regla de color puede ser tan compleja como se quiera (varios rangos, excepciones) y el
costo por frame no cambia, porque siempre es una búsqueda en la tabla. Desventaja: con 3-3-2 bits se
pierde precisión de color. Por eso la capa 1 solo filtra y la capa 2 (YOLO) confirma.

### 5.1 Variante del informe: índice de 9 bits + tabla de 512

**Dónde:** `indice_rgb9`, `construir_lut_fuego_9bits`, `mascara_color_lut9`; se activa con
`detectores.fuego.modo_capa1: lut9`.

Es la ecuación del índice de color del informe: 3 bits por canal, 9 bits en total (0 a 511).

```
idx = ((R >> 5) << 6) OR ((G >> 5) << 3) OR (B >> 5)
       RRR 000 000         000 GGG 000         000 000 BBB
```

Ejemplo, el mismo naranja BGR = (0, 140, 255):

```
R = 255 = 1111 1111 → >> 5 = 111 → << 6 = 111 000 000 = 448
G = 140 = 1000 1100 → >> 5 = 100 → << 3 = 000 100 000 =  32
B =   0 = 0000 0000 → >> 5 = 000                       =   0
idx = 448 OR 32 OR 0 = 111 100 000 = 480
```

Dos detalles:
- **Orden de los canales.** OpenCV entrega los píxeles como B, G, R. La función separa los canales
  con `b, g, r = cv2.split(bgr)` y recién ahí aplica la fórmula con R en los bits altos.
- **Desborde.** El índice ocupa 9 bits y no entra en un byte: en `uint8`, `7 << 6 = 448` quedaría en
  `448 AND 1111 1111 = 192`. Por eso se calcula en `uint16`. El blanco da 511 y no 255.

La tabla tiene 512 entradas, una por índice, con 255 ("fuego") o 0. Es la tabla de booleanos del
informe, guardada como 0/255 para que `tabla[idx]` ya sea una máscara que se combina con AND.
`cv2.LUT` solo acepta tablas de 256, así que la búsqueda se hace con indexación de NumPy, que
también es vectorizada: `mascara = tabla[idx]`.

### 5.2 Comparación de los tres modos de la capa 1

`detectores.fuego.modo_capa1` elige cómo se calcula el "color fuego". Los tres modos usan la misma regla
HSV de `config.yaml` (tono `hue_min`–`hue_max`, saturación ≥ `sat_min`, brillo ≥ `val_min`).

| Modo | Cómo se calcula | Precisión de color | Tiempo en un frame de 640×480 |
|---|---|---|---|
| `lut332` (por defecto) | índice de 8 bits (3-3-2) + `cv2.LUT` | 256 celdas; el azul solo tiene 2 bits | ≈ 1,0 ms |
| `lut9` (informe) | índice de 9 bits (3-3-3) en `uint16` + `tabla[idx]` | 512 celdas | ≈ 3,2 ms |
| `hsv` (sin bits) | `cv2.cvtColor` a HSV + `cv2.inRange` | exacta | ≈ 0,5 ms |

Los tiempos son de la laptop de desarrollo y valen para la imagen completa. El detector solo procesa el
recorte de la zona, así que en la práctica el tiempo es menor.

`lut9` es más lento porque pasa a `uint16` y busca en la tabla con NumPy, y `cv2.LUT` (de 8 bits) está
optimizado con SIMD. Con 3,2 ms por frame igual entra de sobra en el presupuesto de ~100 ms (10 FPS). Las
tablas también se pueden generar a partir de muestras reales de fuego con `scripts/generar_lut_fuego.py`
y cargarse con `detectores.fuego.lut_archivo`. Con muestras, la regla deja de ser un rectángulo en HSV, y
eso no se puede hacer con `inRange`.

## 6. Byte de estado de la alarma

**Dónde:** `homeguard/reglas/estado.py` (Python) y `homeguard/web/static/js/comun.js` (JavaScript del panel).

Las 5 anomalías caben en un byte, un bit cada una:

```
INTRUSION = 1 << 0 = 0000 0001 = 1
PISCINA   = 1 << 1 = 0000 0010 = 2
FUEGO     = 1 << 2 = 0000 0100 = 4
CAIDA     = 1 << 3 = 0000 1000 = 8
PUERTA    = 1 << 4 = 0001 0000 = 16
```

| Operación | Código | Ejemplo |
|---|---|---|
| encender | `estado \| FUEGO` | `0000 0000 \| 0000 0100 = 0000 0100` (4) |
| encender otra | `estado \| PUERTA` | `0000 0100 \| 0001 0000 = 0001 0100` (20) |
| consultar | `estado & (1 << n)` | `0001 0100 & 0000 0100 = 4 ≠ 0` → fuego activo |
| apagar | `estado & ~FUEGO` | `0001 0100 & 1111 1011 = 0001 0000` (16) |
| silenciar | `estado = 0` | todas apagadas |

El servidor manda un solo número por WebSocket y el panel enciende cada indicador con
`(estado & (1 << n)) !== 0`.

Otro detalle de bits en el código: el kernel del desenfoque tiene que ser impar, y `k | 1` lo
garantiza porque enciende el bit 0 (`4 | 1 = 5`, `5 | 1 = 5`).

---

## 7. Benchmark: ¿cuánto aporta?

`python -m homeguard.preproceso.benchmark` mide la capa 1 del detector de fuego ("% de la zona con
color fuego que además se movió") con 5 implementaciones y escribe los tiempos reales de la máquina
en [`BENCHMARK.md`](BENCHMARK.md) y `benchmark.csv`.

| Variante | Qué hace |
|---|---|
| A | El mismo algoritmo de bits que C/D, píxel a píxel en Python (línea base) |
| B | Enfoque clásico de OpenCV en todo el frame: HSV + `inRange` + `absdiff` |
| B2 | Igual que B pero solo en el recorte de la zona |
| C | Bits vectorizados (AND, XOR, >>, OR, LUT) en todo el frame |
| D | Bits vectorizados solo en el recorte de la zona + AND con la ROI (lo que usa HomeGuard) |

Resultados medidos en la laptop de desarrollo (frame de 640x480, zona del 39 % del frame; tus números
van a ser otros):

- **Vectorizar es lo que más aporta.** A tarda ~125–135 ms por frame y D ~0,5–0,7 ms: unas
  **200 veces más rápido**, con el mismo resultado exacto (A, C y D dan el mismo porcentaje). Con el
  bucle Python, solo el preprocesamiento limitaría el sistema a ~8 FPS.
- **La ROI con AND ahorra en proporción al área descartada:** de C a D (y de B a B2) el tiempo baja
  ~3 veces, porque la zona es un 39 % del frame.
- **A igual área, el HSV nativo de OpenCV es un poco más rápido que la LUT RGB332** (B2 ≈ 0,3–0,4 ms
  contra D ≈ 0,5–0,7 ms en esta máquina). La conversión HSV de OpenCV está muy optimizada, y armar el
  índice RGB332 necesita separar canales y hacer desplazamientos en NumPy. Se dejó la LUT porque
  permite cualquier regla de color al mismo costo y porque es el ejercicio de bits que pide la
  materia. Igual, la diferencia (~0,3 ms) es mínima frente a lo que tarda un YOLO (30–100 ms por
  frame).

Conclusión para la defensa: el impacto grande lo dan **vectorizar** las operaciones de bits (~200x)
y **recortar con AND a la región de interés** (~3x). El AND/XOR también permite **saltear los
modelos pesados**: el YOLO de fuego solo corre cuando la capa 1 (color AND movimiento AND zona)
supera el umbral.

## 8. Fase 7: SIMD en C

NumPy y OpenCV ya usan instrucciones SIMD por dentro, pero ahí no se ven. En `nativo/bitwise_simd.c` el XOR
y el AND de dos imágenes están escritos "a mano" en tres niveles, para mostrar qué instrucciones ejecuta la CPU:

| Nivel | Bytes por instrucción | Registro | Vueltas para un gris 640x480 (307 200 bytes) |
|---|---:|---|---:|
| Escalar | 1 | 8 bits (`al`) | 307 200 |
| SSE2 | 16 | XMM de 128 bits | 19 200 |
| AVX2 | 32 | YMM de 256 bits | 9 600 |

Funciones exportadas (las carga `homeguard/preproceso/nativo.py` con `ctypes`):
`hg_xor` (s = a XOR b), `hg_and` (s = a AND b), `hg_xor_and` (s = (a XOR b) AND máscara), y
`hg_nivel` / `hg_nivel_detectado` / `hg_forzar_nivel` para ver o limitar el nivel usado.

**Cómo elige el nivel.** Al primer uso pregunta a la CPU con la instrucción `cpuid` (`__builtin_cpu_supports`
en gcc/clang, `__cpuidex` + `_xgetbv` en MSVC) si soporta AVX2 y si el sistema operativo habilita los
registros YMM. Las funciones AVX2 se compilan con `__attribute__((target("avx2")))`, no con `-mavx2` para todo
el archivo, así la misma DLL carga en una CPU sin AVX2 y usa SSE2 (que tiene toda CPU x86-64). Cuando
`n` no es múltiplo de 16 o 32, los bytes que sobran ("la cola") los procesa el bucle escalar.

**Correspondencia intrínseco → instrucción:**

| Intrínseco en C | Instrucción x86 | Qué hace |
|---|---|---|
| `_mm_loadu_si128` | `movdqu xmm, [mem]` | carga 16 bytes (sin exigir alineación) |
| `_mm_xor_si128` | `pxor xmm, xmm` | XOR de 16 bytes a la vez |
| `_mm_and_si128` | `pand xmm, xmm` | AND de 16 bytes a la vez |
| `_mm_storeu_si128` | `movdqu [mem], xmm` | guarda 16 bytes |
| `_mm256_loadu_si256` | `vmovdqu ymm, [mem]` | carga 32 bytes |
| `_mm256_xor_si256` | `vpxor ymm, ymm, ymm` | XOR de 32 bytes (3 operandos: no pisa las entradas) |
| `_mm256_and_si256` | `vpand ymm, ymm, ymm` | AND de 32 bytes |
| `_mm256_storeu_si256` | `vmovdqu [mem], ymm` | guarda 32 bytes |

**Cómo compilar** (no hace falta para que el sistema funcione: sin la librería, el benchmark omite la fila E):

```bash
nativo\compilar.bat        # Windows: MinGW gcc (MSYS2) o, si no está, MSVC cl
sh nativo/compilar.sh      # Linux/macOS: gcc o clang
.venv/Scripts/python -m pytest tests/test_nativo.py -q    # compara contra cv2.bitwise_* en 3 niveles
.venv/Scripts/python -m homeguard.preproceso.benchmark    # agrega la fila E a docs/BENCHMARK.md
```

El script también genera el ensamblador: `gcc -O2 -S -masm=intel` → `nativo/bitwise_simd.s` (con MSVC,
`/FA` → `nativo/bitwise_simd.asm`). En la PC de desarrollo no había compilador, así que el fragmento y la
medición todavía no están: los completa el grupo.

**Fragmento del bucle vectorizado** (buscar `xor_avx2` en `nativo/bitwise_simd.s` y pegar el bucle; tiene que
verse `vmovdqu`, `vpxor` y el salto que vuelve al inicio del bucle):

```asm
; PEGAR AQUÍ el bucle de xor_avx2 (y, si entra, el de xor_sse2 con movdqu/pxor) de nativo/bitwise_simd.s
```

**Fila medida** (copiarla de `docs/BENCHMARK.md` después de compilar y correr el benchmark):

| Variante | Descripción | ms/frame (mediana) | FPS equivalentes | Aceleración vs A | Resultado (% zona) |
|---|---|---:|---:|---:|---:|
| E | C con SIMD (XOR + AND nativos) + ROI | _pendiente_ | _pendiente_ | _pendiente_ | _pendiente_ |

Qué esperar al explicarlo: E debe dar **exactamente el mismo resultado** que D (el test lo verifica). La
diferencia de tiempo con D probablemente sea chica, porque OpenCV ya usa SIMD para `bitwise_*` y la mayor parte del
tiempo se va en la conversión a gris y en la LUT, no en el XOR/AND. El valor de esta fase es **ver** las
instrucciones `pxor`/`pand`/`vpxor` que antes quedaban escondidas dentro de OpenCV.
