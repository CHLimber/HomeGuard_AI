# Guía del grupo: lo que hay que hacer a mano

El software está instalado, probado y documentado. Esta es la lista de lo que **no se puede hacer con código**:
configurar los celulares, crear el bot de Telegram, grabar los videos de prueba y calibrar. Seguila en orden.
Cada paso dice cómo comprobar que quedó bien.

---

## 0. Si van a usar otra laptop en la feria

Instalación completa en [README.md](../README.md#instalación) (unos 10 minutos con buena conexión). Después:

```bash
python scripts/verificar_entorno.py --cargar-modelos
```

✅ Tiene que terminar con **0 errores**. Los avisos de `.env` y de los celulares se resuelven en los pasos 1 y 2.

## 1. Bot de Telegram (≈ 5 min)

1. En Telegram, abrí **@BotFather** → `/newbot` → elegí un nombre (ej. `HomeGuard Feria`) y un usuario terminado
   en `bot` (ej. `homeguard_feria_uagrm_bot`). Te da un **token** del tipo `123456789:AA...`.
2. En la carpeta del proyecto, copiá `.env.example` como `.env` y pegá el token: `TELEGRAM_TOKEN=123456789:AA...`
3. Desde el celular del "dueño", abrí tu bot y mandale cualquier mensaje (ej. "hola").
4. Ejecutá `python scripts/probar_telegram.py --obtener-chat-id` y copiá el número en `.env`:
   `TELEGRAM_CHAT_ID=987654321`
5. Ejecutá `python scripts/probar_telegram.py`.

✅ Llegan al celular un mensaje y una foto de prueba. **El archivo `.env` no se sube a git** (ya está en
`.gitignore`). No compartan el token.

## 2. Celulares como cámaras (≈ 10 min por celular)

1. Instalá **IP Webcam** (Android, recomendada) o **DroidCam** (Android/iPhone).
2. Conectá el celular y la laptop **a la misma red Wi-Fi**. En la feria, lo más confiable es el **hotspot de un
   celular que no sea cámara** (las redes de la universidad suelen aislar los dispositivos entre sí).
3. IP Webcam: abajo de todo → **Iniciar servidor**. La app muestra la IP, por ejemplo `http://192.168.43.120:8080`.
   La URL del video es **`http://192.168.43.120:8080/video`**.
   DroidCam: la URL es `http://IP:4747/video` (DroidCam acepta **un solo cliente**: cerrá la app de escritorio).
4. Probala: `python scripts/probar_camara.py http://192.168.43.120:8080/video`. Tienen que aparecer el video y los
   FPS.
5. Cargala en el sistema, de una de estas dos formas:
   - en `config.yaml` → `camaras: celular1: fuente: ...` y `activa: true`, o
   - con el sistema corriendo: Dashboard → **Configuración → Cámaras**: pegar la URL, marcar "activa" y **Aplicar**.
6. En IP Webcam conviene bajar la resolución a **640x480 o 800x600** (Preferencias de video): menos latencia y menos
   batería. Dejá los celulares **enchufados** y con el ahorro de energía y el bloqueo de pantalla desactivados.

✅ En Dashboard → En vivo, cada cámara aparece como "conectada" con su video.

> **Windows Firewall:** la primera vez que corre `run.py`, Windows pregunta si permite a Python en la red. Marcá
> **Redes privadas** y aceptá. Si la red quedó como "pública", cambiala a privada en Configuración de Windows → Red.

## 3. Panel de alarma en otro celular o tablet (≈ 3 min)

1. Con `python run.py` corriendo, la consola muestra `Panel (celular): http://192.168.x.x:8000/alarma`. Abrí esa
   dirección en **Chrome** en la tablet o el celular del panel.
2. Subí el volumen **multimedia** al máximo y tocá **ARMAR ALARMA**. Se escucha un pitido corto. Tocá
   **Probar sirena**.
3. Desactivá el apagado automático de la pantalla (Ajustes → Pantalla → Tiempo de espera → el máximo, o "nunca").
4. Hay que **volver a tocar ARMAR cada vez que se recarga la página**: los navegadores no dejan sonar audio sin que
   alguien toque la pantalla.

✅ Arriba a la derecha dice **Conectado**.

> **Vibración y pantalla siempre encendida en Android:** la página se abre por `http://IP` (sin HTTPS), y algunos
> navegadores bloquean `navigator.vibrate` o el *wake lock* en páginas que no son seguras. Si no vibra, no es un
> error del sistema. Solución opcional para la demo: en Chrome de Android, abrí `chrome://flags`, buscá
> **"Insecure origins treated as secure"**, agregá `http://IP-DE-LA-LAPTOP:8000`, activalo y reiniciá Chrome.

## 4. Dibujar las zonas (≈ 10 min)

Dashboard → **Zonas** → elegí la cámara → **Congelar imagen actual** → hacé clic en los vértices del polígono → tipo
y nombre → **Guardar zona**.

| Tipo | Dónde dibujarla | La necesita |
|---|---|---|
| `acceso` | donde se para alguien que entra (frente a la puerta, a la altura de la cara) | intrusión |
| `piscina` | el agua (o lo que la represente en la maqueta) | piscina |
| `borde_piscina` | donde se para el adulto que supervisa | piscina |
| `puerta` | **solo la hoja de la puerta**, ajustado | puerta |
| `fuego` (opcional) | dónde puede haber fuego (cocina). Sin esta zona se mira la imagen completa | fuego |

En la zona `puerta`: con la puerta **cerrada** y sin nadie delante, tocá **Capturar referencia (puerta cerrada)**.
Repetilo si cambia mucho la iluminación del lugar.

Las zonas se dibujan sobre los pies de las personas (el sistema usa el punto inferior central de cada persona): la
zona de la piscina tiene que incluir el piso o el agua donde estaría la persona, no solo su cabeza.

✅ En Dashboard → En vivo se ven los polígonos de colores sobre el video.

## 5. Registrar a los residentes (≈ 2 min por persona)

Dashboard → **Residentes**: nombre y **3 a 5 fotos** de frente, con buena luz, una sola cara por foto (o que la
persona sea la cara más grande). Sirven fotos sacadas con el celular en el momento. Registren a todos los
integrantes del grupo que van a "vivir" en la casa de la demo.

✅ Al pasar un residente por la zona de acceso, en **Calibración → Rostros** aparece su nombre con una similitud
mayor a 0,363. Una persona no registrada aparece como desconocida.

## 6. Grabar los videos de prueba y medir (≈ 2–3 h en total)

Seguí el protocolo de [PRUEBAS.md](PRUEBAS.md#2-protocolo-para-los-videos-de-prueba): al menos 10 positivos y
10 negativos por anomalía, grabados con la cámara y el encuadre de la feria. Con IP Webcam se puede grabar desde la
app, o con la cámara normal del celular apuntando igual.

Copialos en `data/videos_prueba/<anomalía>/positivos|negativos/` y ejecutá para cada detector:

```bash
python scripts/evaluar_detector.py --detector fuego --carpeta data/videos_prueba/fuego
```

Los resultados (VP, FP, VN, FN, precisión, recall) se escriben solos en `docs/PRUEBAS.md`. Después de una sesión de
prueba en vivo con el panel abierto y Telegram configurado:

```bash
python scripts/reporte_latencias.py
```

**Seguridad:** el fuego, con una vela o un encendedor sobre una superficie no inflamable y con agua cerca, o con
un video de fuego real reproducido en una pantalla frente a la cámara. Las caídas, sobre colchoneta.

## 7. Calibrar (en la casa de prueba y otra vez en la feria) (≈ 30 min)

Abrí Dashboard → **Calibración** al lado de la cámara y provocá cada situación. Los valores que superan su umbral
se ven en **rojo**. Ajustá en **Configuración** (se aplica al instante):

| Problema | Qué mirar en Calibración | Qué ajustar |
|---|---|---|
| La puerta suena con gente pasando delante | `porcentaje cambiado` con la puerta cerrada | subir `detectores.puerta.porcentaje_min` o achicar la zona |
| La puerta no suena al abrirla | `porcentaje cambiado` con la puerta abierta | bajar `porcentaje_min` o `umbral_diferencia`; recapturar la referencia |
| Un residente sale "desconocido" | `rostros → similitud` | registrar más fotos con la luz de la feria; bajar un poco `umbral_similitud` (no menos de ~0,30) |
| Fuego: la capa 2 nunca corre | `capa1 pct color y movimiento` | bajar `umbral_capa1_pct` o ampliar `hue_max` / bajar `sat_min` |
| Fuego: falsas alarmas con luces | `capa2 confianza` | subir `confianza_capa2` o `alarmas.fuego.votos_n` |
| Caídas no detectadas | `ratio`, `angulo torso`, `descenso relativo` | bajar `ratio_min` o `descenso_min_relativo`; cámara más alta y lateral |
| Piscina suena con un adulto presente | `supervisores en borde` = 0 | ampliar la zona `borde_piscina` (tiene que contener los pies del adulto) |
| Va lento (FPS bajos) | En vivo → FPS, ms/frame | bajar `procesamiento.imgsz_yolo` (ej. 416 o 320) o `fps_objetivo`; subir `caidas.cada_n_frames` |

Para la demo, quizás quieran **bajar los tiempos** para que el público no espere tanto: por ejemplo
`detectores.piscina.inmovil_tiempo_s` de 10 a 5, o `detectores.caidas.inmovil_tiempo_s` de 5 a 3. Anótenlo en la
defensa.

Si se rompe algo de la configuración: **Configuración → Restaurar config.yaml**.

## 8. Benchmark bitwise en la laptop de la feria (≈ 1 min)

```bash
python -m homeguard.preproceso.benchmark
```

Actualiza `docs/BENCHMARK.md` con los tiempos de esa laptop. Úsenlo en la defensa junto con
[BITWISE.md](BITWISE.md).

## 9. Tablas para el informe Word (sección 6.2) (≈ 5 min)

La sección 6.2 "Resultados esperados" del informe hoy dice "Por medir". Cuando ya corrieron el benchmark (paso 8),
`evaluar_detector.py` para cada detector y una sesión en vivo con el panel y Telegram (paso 6):

```bash
python scripts/generar_tablas_informe.py                      # eventos reales
python scripts/generar_tablas_informe.py --desde 2026-11-20   # solo los eventos de la sesión de pruebas
```

Escribe `docs/informe/tablas_informe.md` con tres tablas listas para pegar (benchmark, precisión/recall/F1 por
detector y latencias: media, P95, máximo y % bajo 2 s) y un CSV por tabla, que se puede abrir con Excel y copiar al
Word. Lo que todavía no se midió sale como **"Por medir"**: el script no inventa números. Usen `--desde` para no
mezclar eventos de pruebas viejas, y no usen `--demo` para el informe (son eventos sintéticos).

## 10. Capturas de pantalla para el Anexo J (≈ 20 min)

Sáquenlas con el sistema corriendo con cámaras reales y la maqueta, no en `--demo`. En Windows: `Win + Shift + S`;
en el celular, la captura normal. Guárdenlas en PNG con el nombre indicado.

| Archivo | Qué tiene que verse | Cómo obtenerla |
|---|---|---|
| `J1_panel_alarma.png` | Panel `/alarma` en rojo con el indicador de la anomalía encendido, la foto, el tipo, la zona y la hora del evento | Celular/tablet del panel, después de **ARMAR ALARMA**, mientras suena una alarma (por ejemplo, abrir la puerta fuera de horario). Captura desde el propio celular |
| `J2_en_vivo.png` | En vivo con las cajas de YOLO, las zonas dibujadas, las etiquetas, el semáforo de las 5 anomalías y FPS/CPU | Dashboard → **En vivo** con una persona en la maqueta. Si se puede, que se vea un semáforo en rojo |
| `J3_editor_zonas.png` | Editor de zonas con el frame congelado y los polígonos de las zonas (acceso, piscina, borde, puerta, fuego) | Dashboard → **Zonas** → elegir la cámara → congelar el frame. Para la puerta, que se vea también la vista previa de la referencia |
| `J4_calibracion.png` | Valores crudos de cada detector junto a su umbral, alguno en rojo, y la probabilidad de falsa alarma N de M | Dashboard → **Calibración** mientras provocan una situación (abrir la puerta, mostrar la llama) |
| `J5_historial.png` | Tabla del historial con miniaturas, confianza y latencias (verdes si son < 2 s) | Dashboard → **Historial** después de la sesión de pruebas, con eventos de varios tipos |
| `J6_telegram.png` | Mensaje del bot con la foto del evento, el tipo, la zona y la hora | Celular del dueño (o del grupo de Telegram) al recibir una alarma |

Para el informe, recorten las barras del navegador y tapen nombres o caras de personas que no firmaron el
consentimiento (Anexo I).

## 11. (Opcional) Fase 7: compilar el SIMD en C (≈ 20 min)

Sin compilar, el sistema funciona igual. Compilarlo suma la fila E del benchmark y el ensamblador real para la defensa.

1. Instalar MSYS2 desde https://www.msys2.org (instalación por defecto en `C:\msys64`).
2. Abrir la terminal "MSYS2 UCRT64" y ejecutar `pacman -S mingw-w64-ucrt-x86_64-gcc`.
3. Agregar `C:\msys64\ucrt64\bin` al PATH de Windows y abrir una terminal nueva. `gcc --version` tiene que responder.
   Alternativa: Visual Studio Build Tools con "Desarrollo para el escritorio con C++", y ejecutar desde la
   "x64 Native Tools Command Prompt".
4. Desde la carpeta del proyecto: `nativo\compilar.bat`. En Linux/macOS: `sh nativo/compilar.sh`.
5. `.venv\Scripts\python -m pytest tests\test_nativo.py -q`: ya no tienen que aparecer tests saltados.
6. `.venv\Scripts\python -m homeguard.preproceso.benchmark`: aparece la fila E en `docs/BENCHMARK.md`.
7. Pegar en la sección 8 de `docs/BITWISE.md` el bucle de `xor_avx2` de `nativo/bitwise_simd.s` y la fila E medida.

La DLL tiene que ser de 64 bits, igual que Python.

## 12. Modo exposición: «Prueba con video» (≈ 1 h para preparar los videos)

En la feria no se puede prender fuego ni tirarse al piso de verdad. Para eso está la página **Prueba con video** del
dashboard: se sube un video o unas fotos, y el sistema los analiza **como si fueran una cámara más**. Pasan por los
mismos modelos (YOLO, YuNet/SFace, pose), el mismo motor de reglas y las mismas salidas: suena el panel, llega el
Telegram y queda en el Historial con sus latencias.

**Preparar antes de la feria** (un video o fotos por anomalía, y probar que cada uno dispare):

| Anomalía | Qué conseguir | Notas |
|---|---|---|
| Intrusión | Video o foto de una persona de frente, con la cara grande y visible | Que **no** esté registrada en Residentes |
| Piscina | Video o foto de alguien dentro de una piscina | Con «todo el cuadro» como zona alcanza con que aparezca una persona 2 s |
| Fuego | Video de una llama real (vela, fogata, hornalla) o una foto de fuego | Un dibujo o una luz naranja no dispara: lo confirma el YOLO de fuego |
| Caída | **Video** de alguien de pie que cae al piso y queda quieto 5 s | Con fotos: 1 de pie y 2 en el suelo, en el mismo lugar del cuadro. Una foto rotada no sirve |
| Puerta | Video con cámara fija: puerta cerrada al principio, después se abre 2 s o más | Fotos: 1 cerrada y 2 abierta. **Dibujar la zona sobre la puerta** |

Los mejores videos son los propios, grabados con la maqueta: muestran que funciona con lo que está en la mesa.
Videos MP4 de 10–30 s y 720p o menos. Las fotos se muestran en orden alfabético (nómbrenlas `1.jpg`, `2.jpg`…).

**Paso a paso:**
1. Dashboard → **Prueba con video** → nombre (es lo que se lee en el panel y en Telegram), archivo y anomalía →
   **Subir y analizar**. Se crea la zona de todo el cuadro y empieza a reproducirse.
2. Si es una puerta, o si la anomalía tiene que pasar en una parte del cuadro: **Zonas** (botón de la fila) →
   dibujar → volver y tocar **Reiniciar**.
3. Con el panel abierto en la tablet: **Reproducir**. A los pocos segundos suena la sirena.
4. Cada **Reproducir/Reiniciar** empieza el video de cero y borra el cooldown de esa prueba, así se puede repetir la
   demostración para cada visitante.

Se reproduce una prueba a la vez. Las cámaras reales siguen funcionando al mismo tiempo. Las pruebas quedan
guardadas (`data/pruebas/`) entre reinicios; los eventos que generan aparecen en el Historial como
«Prueba: <nombre>». Para el informe, usen `--desde` en `generar_tablas_informe.py` o filtren por cámara, así no se
mezclan con las mediciones con cámaras reales.

## 13. Checklist del día de la feria

- [ ] Laptop enchufada; en Windows: plan de energía "Alto rendimiento" y suspensión desactivada.
- [ ] Hotspot encendido; laptop, celulares cámara y tablet del panel conectados a él.
- [ ] Celulares cámara enchufados, IP Webcam iniciado, pantalla sin bloqueo.
- [ ] `python scripts/verificar_entorno.py` → 0 errores y cámaras "entregan frames".
- [ ] `python run.py` (o `python run.py --sin-telegram` si no hay internet: el panel funciona igual).
- [ ] Sistema **armado** (si el dashboard muestra el aviso ámbar "Sistema desarmado", tocar **Armar sistema**).
- [ ] Windows con la zona horaria de La Paz (los horarios de la puerta usan la hora de la laptop).
- [ ] Panel abierto en la tablet → **ARMAR ALARMA** → Probar sirena.
- [ ] Recapturar la referencia de la puerta con la luz del lugar.
- [ ] Pasada rápida por Calibración: cada anomalía dispara una vez.
- [ ] Historial limpio para la demo: si quieren empezar de cero, cerrar el programa y borrar `data/homeguard.db` y
      `data/eventos/*.jpg`. **Ojo: esto borra también residentes y zonas**; para conservarlos, solo filtrá el
      historial por fecha.
- [ ] **Prueba con video**: cada prueba guardada dispara su alarma (tocar Reproducir en cada una).
- [ ] Plan B sin cámaras: `python run.py --demo` (la puerta sintética dispara la alarma cada vuelta pasado el
      cooldown de 30 s).

## Lo que NO hace falta hacer

- Entrenar modelos: todos son preentrenados y ya están en `models/`.
- Comprar hardware, contratar servicios o configurar la nube: todo corre en la laptop.
