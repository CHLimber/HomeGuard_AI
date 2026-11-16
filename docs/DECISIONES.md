# Decisiones técnicas

Cada decisión que no venía fijada en el pedido, con su porqué. Criterio general: **la opción más simple que
funcione en una demo en vivo**.

## Entorno y dependencias

1. **Python 3.12 en lugar de 3.11.** En la laptop de desarrollo no había 3.11 y sí 3.12, que ultralytics y torch
   soportan. No se usa mediapipe, que era la dependencia más delicada con las versiones. El código funciona en
   3.11 y en 3.12.
2. **`supervision>=0.25,<0.31`.** `sv.ByteTrack` (pedido explícitamente) está deprecado desde la 0.28 y se elimina en
   la 0.31. Se fija la versión y se silencia el aviso.
3. **OpenCV 5.0.** Es lo que instaló `opencv-python>=4.10`. `FaceDetectorYN` y `FaceRecognizerSF` funcionan igual.
   Su nuevo motor DNN imprime "Targets are not supported by the new graph engine", que es inofensivo, así que se
   baja el nivel de log de OpenCV a ERROR.
4. **torch CPU.** En Windows, pip instala la versión CPU por defecto. No se fuerza CUDA.
5. **psutil** para CPU y RAM del dashboard: ya es dependencia de ultralytics, así que no agrega nada.
6. **Nombre local del modelo de fuego:** `best.pt` de `rabahdev/fire-smoke-yolov8n` se guarda como
   `models/fire_smoke_yolov8n.pt`, para que no se confunda con otros `best.pt`. Los nombres de los demás archivos
   se verificaron en Hugging Face y coinciden con los pedidos.

## Configuración

7. **Configuración en capas: `config.yaml` + overrides en la BD.** `config.yaml` queda comentado como referencia
   única de umbrales. El dashboard guarda sus cambios en la tabla `config` como claves con puntos
   (`detectores.puerta.porcentaje_min = 30`) y se aplican encima del YAML sin perder sus comentarios. "Restaurar
   config.yaml" borra la tabla. Si un override deja la configuración inválida, se ignora con un error en el log y
   el sistema arranca igual.
8. **Validación estricta con pydantic (`extra="forbid"`).** Una clave mal escrita en `config.yaml` hace fallar el
   arranque con un mensaje claro, en lugar de ignorarse en silencio.
9. **Las descripciones de los umbrales en el dashboard salen de los comentarios de `config.yaml`**
   (`leer_comentarios`). Así no hay que mantener la documentación en dos lugares.
10. **Las cámaras son un diccionario (`camaras: {laptop: {...}}`)**, no una lista, para que los overrides
    (`camaras.laptop.fuente`) funcionen. La tabla `camara` de la BD es un espejo de la config.
11. **El modo demo usa otra base de datos** (`data/homeguard_demo.db`) y las cámaras de `demo.camaras`, para no
    mezclar eventos de prueba con el historial real.
12. **Puerta: `horarios_permitidos: []` por defecto (vigilar siempre).** Si no, en una feria de día la puerta nunca
    dispararía. El grupo puede poner por ejemplo `["07:00-22:00"]`.

## Detectores y motor de reglas

13. **Los detectores emiten observaciones positivas y negativas** (`PosibleEvento.activo`). La votación N de M
    necesita saber cuántos frames se evaluaron, no solo los positivos.
14. **"K frames consecutivos" (intrusión) y "3 de 5" (fuego) los resuelve el mismo motor**: K consecutivos es N = M = K.
15. **Las reglas temporales propias de cada anomalía (2 s de puerta abierta, 3 s de inmovilidad en caídas)
    viven en el detector**, y el motor usa 1 de 1 para esas anomalías. Las reglas de "cuántos frames" viven en el
    motor. Así cada regla está en un solo lugar.
16. **Tiempo inyectado (`ctx.t`).** Los detectores nunca llaman a `time.time()`, lo que permite testear con videos
    a máxima velocidad y evaluar videos más rápido que el tiempo real.
17. **Cooldown por (tipo, cámara, zona)** y no solo por (tipo, zona): dos cámaras pueden tener zonas con el mismo
    nombre.
18. **El estado queda enclavado hasta "SILENCIAR".** Una alarma de seguridad no se apaga sola. `motor.auto_limpiar_s`
    permite cambiarlo. Silenciar no reinicia el cooldown, así no vuelve a sonar al instante.
19. **Puerta:** si no se capturó una referencia desde el dashboard, se usa el primer frame
    (`referencia_automatica`). El desenfoque previo usa `k | 1` para asegurar un kernel impar.
20. **Fuego:** sin zonas de tipo "fuego" se analiza la imagen completa. La capa 2 corre una sola vez por frame sobre
    la imagen completa, y sus detecciones se asocian a la zona cuyo recuadro contiene su centro.
21. **Piscina (anomalía quitada, ver nº 54; se conserva como registro de lo que se decidió):** el "supervisor" tiene que ser una persona (las mascotas no supervisan). La regla (a) exige
    `tiempo_sin_supervisor_s` (2 s) para no disparar si alguien cruza la piscina un instante; esto se agregó porque
    el pedido no fija ese tiempo. La pertenencia a la zona usa el punto inferior central del bbox (los pies), que es
    lo habitual con `PolygonZone`.
22. **Caídas:** la persona caída se asocia con la que estaba de pie **por cercanía, no por `tracker_id`**. Cuando el
    cuerpo pasa de vertical a horizontal el bbox cambia tanto que los trackers suelen perder la identidad justo en la
    caída. Si los keypoints del torso no son confiables, no se considera "acostado" (criterio conservador). Si una
    persona de pie aparece pegada a la caída (alguien que ayuda), el seguimiento de esa caída se descarta (ver nº 52
    para el criterio actual).
23. **Rostros:** YuNet corre sobre el recorte de la zona "acceso" a **resolución original** (mejor a distancia) y solo
    si YOLO ve una persona dentro de la zona. Un rostro cuya caja cae dentro del recorte pero fuera del polígono se
    ignora. Si no hay residentes registrados, cualquier rostro es desconocido.
24. **Alta de residentes:** de cada foto se toma el rostro más grande. Las fotos se procesan en memoria y se
    descartan: solo se guardan los vectores (privacidad). YuNet y SFace no son thread-safe, así que el alta usa su
    propia instancia con un lock.

## Bitwise

25. **Capa 1 de fuego con el índice de 9 bits del informe (`modo_capa1: lut9`) por defecto.** Es la ecuación del
    índice de color del informe: `((R>>5)<<6)|((G>>5)<<3)|(B>>5)` en uint16 y una tabla de 512 indexada con NumPy.
    Quedan como alternativas configurables RGB332 (8 bits + `cv2.LUT`) y HSV (`cv2.inRange`). Medido en
    640×480: lut9 ≈ 3,2 ms, lut332 ≈ 1,0 ms, hsv ≈ 0,5 ms. Los 3,2 ms entran en el presupuesto por frame, y se
    eligió coincidir con el informe. La tabla se puede generar a partir de muestras con
    `scripts/generar_lut_fuego.py` (`lut_archivo`).
26. **Cuantización con una AND (`x & 0xF0`) en lugar de `(x >> 4) << 4`.** Son equivalentes (lo verifica un test para
    todos los valores de `bits`), y la AND es una sola operación. La versión con desplazamientos queda como función
    didáctica.
27. **Operaciones matriz-con-matriz con `cv2.bitwise_*`** (SIMD, ~10 veces más rápido que NumPy en este equipo) y
    **operaciones con escalar con NumPy**, porque `cv2.bitwise_and(img, escalar)` falla con imágenes muy chicas
    (OpenCV interpreta el escalar como una matriz 4x1).
28. **El benchmark compara 5 variantes y se publica tal cual dio.** El HSV nativo de OpenCV resultó un poco más rápido
    que la LUT a igual área. Se documenta y se explica en BITWISE.md en lugar de esconderlo. El aporte
    medible está en vectorizar (~80x con el índice de 9 bits; ~200x con RGB332) y en el ROI con AND (~2,5–3x).
    El benchmark usa el mismo índice de color que el detector (`modo_capa1`).

## Salidas, web y latencia

29. **Orden de `despachar()`: foto a disco → WebSocket → cola de Telegram → BD.** La alerta llega al panel lo antes
    posible. Si el ack llega antes de que la fila exista en la BD, se guarda en memoria y se aplica después.
30. **La latencia al panel se mide con el ack** (detección → ack recibido por el servidor). Incluye el viaje de
    vuelta, así que es una **cota superior** de la latencia real, y evita depender de que los relojes del celular y
    de la laptop estén sincronizados.
31. **Telegram con `requests` en un hilo y `queue.Queue`**, no con asyncio: es más simple, y un envío lento o sin
    internet nunca toca el loop del servidor web. Los errores 400/401/403/404 se consideran permanentes y no se
    reintentan; el 429 respeta `retry_after`.
32. **Sin Tailwind ni CDN: CSS propio.** En una feria puede no haber internet, y el panel tiene que funcionar igual.
    La tipografía es Bahnschrift, que viene con Windows (estilo DIN, de señalética), con alternativas condensadas
    en Android.
33. **El panel recibe el estado cada 0,5 s** (además de las alertas). Eso sirve de latido: si pasan 6 s sin
    mensajes, el panel reconecta solo. También corrige un mensaje perdido.
34. **El stream MJPEG lo produce el pipeline** (frame ya anotado, un JPEG por frame analizado). Si el último frame
    tiene más de 3 s, se muestra "sin señal" en lugar de una imagen congelada.
35. **Un solo hilo de procesamiento para todas las cámaras.** Es simple y suficiente: con 3 cámaras a 10 FPS
    objetivo se midieron ~9 FPS por cámara en la laptop de desarrollo. Si hiciera falta más, el siguiente paso sería
    un hilo por cámara con su propia instancia de los modelos.
36. **SQLite en modo WAL con `busy_timeout`**, porque escriben tres hilos (procesamiento, Telegram y web).

## Pruebas

37. **Videos sintéticos + verdad de terreno (`.json`).** Los videos sintéticos (puerta y fuego) traen en un `.json`
    la verdad de terreno por frame. La pose, los rostros y el YOLO de fuego se prueban con secuencias simuladas a
    partir de ella. Los modelos reales se verificaron aparte sobre una foto de ejemplo (ver PROGRESO.md). (El video
    «zona», con un rectángulo que YOLO no ve como persona, era el de la piscina y se quitó con ella, nº 54.)
38. **El evaluador (`evaluar_detector.py`) analiza los videos al ritmo de `fps_objetivo`** (salteando frames), porque
    las reglas cuentan frames analizados. Usa una hora fija de madrugada e ignora el horario permitido de la puerta:
    mide la detección, no el horario.

## Coherencia con el informe (Anexo C) y agregados del contexto v2

39. **Valores por defecto alineados con el Anexo C** (31/10/2026): cooldown 30 s para todas las anomalías (antes 60 y
    120 en caídas), score de YuNet 0,90 (antes 0,70), umbral de la capa 1 de
    fuego 0,5 % (antes 0,30), confianza de keypoints 0,50 (antes 0,30), umbral de diferencia de la puerta 30 (antes
    35), timeout de Telegram 5 s (antes 10). Se ajustan en la feria con la página Calibración. Si un valor
    calibrado termina distinto del informe, se anota acá.
40. **Diferencias con el Anexo C que se mantienen** (son cambios de forma o de unidad, no de criterio):
    - Votación N/M por anomalía en lugar de un único 3 de 5 (decisiones 14 y 15).
    - Descenso de la caída relativo a la altura de la persona (0,25) en lugar de la altura del frame (0,20):
      no depende de la distancia a la cámara.
    - Porcentaje de la puerta en % (25,0) en lugar de fracción (0,25).
    - Horario de la puerta vacío = vigilar siempre (decisión 12).
    - Telegram reintenta sin límite con espera exponencial y descarta eventos de más de 120 min, en lugar de 5 reintentos.
    - Sin clave `zona_horaria`: los horarios usan la hora local de la laptop. Hay que configurar Windows en
      "La Paz" (UTC−4, sin horario de verano). En Windows, `zoneinfo` necesita el paquete `tzdata`, y no se agregó
      una dependencia solo para esto.
41. **Desarmar el sistema** (sección 6.3 del contexto): el motor ignora las observaciones y el estado queda en 0,
    pero los detectores siguen corriendo para que el video y Calibración funcionen. Al armar o desarmar se vacían
    las ventanas de votación. Se persiste como `_sistema.armado` en la tabla `config`. Las claves que empiezan con
    `_` son internas: no se validan contra `Config` y "Restaurar config.yaml" no las borra.
42. **P(falsa alarma) N de M** (`probabilidad_falsa_alarma` en `reglas/motor.py`): se calcula en el servidor
    (`/api/falsa-alarma`) y no se replica en JS. El `p` por defecto es 0,05 y se edita en Calibración.
43. **Tablas del informe** (`scripts/generar_tablas_informe.py`): P/R/F1 se leen de la fila de resumen que
    `evaluar_detector.py` escribe en PRUEBAS.md, porque no hay otra fuente estructurada. El % de latencias cuenta
    los eventos ≤ objetivo, igual que `reporte_latencias.py`. Sin datos escribe "Por medir".
44. **Fase 7: SIMD en C opcional, cargado con ctypes.** AVX2 se compila con `__attribute__((target("avx2")))` y la
    CPU se detecta al ejecutar, así una sola DLL sirve en cualquier x86-64 (con SSE2 como mínimo). El bucle
    escalar se compila sin autovectorizar para que sirva de línea base. La variante E del benchmark solo aparece si
    la librería está compilada, y su resultado tiene que ser idéntico al de D. En la PC de desarrollo no había
    compilador: no se publican tiempos ni ensamblador hasta que el grupo compile (GUIA_GRUPO, sección 11).
45. **Cada fórmula del informe lleva un comentario `# Informe, ecuación de …`** en el código: similitud coseno,
    ángulo del torso, proporción de píxeles, byte de estado, regla de fuego, binomial N de M, P/R/F1, latencias,
    tamaño de fotograma, índice de color e instrucciones SIMD. Así el jurado puede ir del Word al código. La IoU
    no aparece en el código propio porque la calcula ByteTrack internamente.

## Modo exposición

46. **«Prueba con video» = cámaras virtuales.** Cada video o serie de fotos subido se guarda en
    `general.carpeta_pruebas/<id>/`, se registra en la tabla `medio_prueba` y el Sistema lo agrega a la config como
    la cámara `prueba_<id>`. Así pasa por exactamente el mismo camino que una cámara real (captura → analizador →
    motor → panel/Telegram/BD) y no hay un "modo demo" con lógica aparte que el jurado pueda objetar. Se reproduce
    una a la vez. No se mezclan con las cámaras de config.yaml: no aparecen en Configuración y no se pueden editar
    como overrides.
47. **Fotos como presentación** (fuente = carpeta de imágenes, cada una `segundos_por_imagen`). Con una sola foto,
    fuego, caída y puerta no pueden disparar: fuego exige movimiento, caída un descenso y puerta un cambio contra
    la referencia. Una serie (cerrada → abierta, de pie → en el suelo) sí. Para el fuego, una cámara de imágenes
    marca `fuente_estatica` y la capa 1 usa solo el color (sin el AND con el movimiento XOR); la capa 2 YOLO
    confirma igual. Se verificó con modelos reales: foto de fogata → capa 1 57,8 %, YOLO 0,64 → alarma.
48. **«Reproducir» borra votos y cooldown de esa cámara** (`MotorReglas.reiniciar_camara`), para poder repetir la
    demostración en cada visita. No toca las demás cámaras.
49. **Zona de cuadro completo por defecto.** Sirve para intrusión y fuego. Para la puerta casi nunca:
    tiene que cambiar el 25 % de la zona, y una puerta que ocupa una franja del cuadro cambia ~10 %. La página lo
    avisa y lleva a Zonas para dibujarla.
50. **Precarga de modelos al arrancar** (`procesamiento.precargar_modelos`). Cargar y hacer la primera inferencia
    de los tres YOLO tarda ~5 s; sin precarga, la primera alarma del día se demoraba eso. El análisis empieza
    cuando los modelos están listos (el servidor y las cámaras arrancan antes).
51. **Prueba con video desde un enlace.** En vez de subir el archivo se puede pegar un enlace: un link directo a un
    video (se descarga con `requests`, con el mismo tope `general.max_mb_prueba`) o uno de YouTube (se descarga con
    `yt-dlp`, MP4 de 720p o menos). Siempre se guarda en disco como un medio subido, así que la reproducción no
    depende de internet ni de que el link siga vivo en la feria. `yt-dlp` es opcional: sin él, solo falla el alta
    desde YouTube, con un aviso. No se reproduce el enlace en vivo porque YouTube no entrega un stream que OpenCV lea.
52. **Caídas más tolerantes para la demostración.** Se probó el detector con pose real sobre videos de caídas de
    internet (cámara fija) y no detectaba ninguna: la pose pierde o «endereza» a la persona acostada y las reglas
    reiniciaban la cuenta. Cambios (todos en `config.yaml`, sección `detectores.caidas`):
    - `confianza` 0,40 → **0,25** e `imgsz` propio de **640** (la pose de una persona acostada sale con poca confianza).
    - La caída solo se descarta si alguien cercano está **más arriba** que ella en al menos `levantarse_relativo`
      (0,25) × su altura. Antes cualquier recuadro «de pie» cercano la cancelaba, aunque fuera ruido de la pose.
    - Tolerancia de movimiento = máx(`inmovil_desplazamiento_px`, `inmovil_desplazamiento_relativo` (0,15) × largo
      del cuerpo): con 20 px fijos el temblor del centro de un cuerpo grande reiniciaba la inmovilidad.
    - `inmovil_tiempo_s` 5 → **3** y `olvidar_tras_s` 3 → **6**: si la pose deja de ver a la persona acostada, la
      caída sigue contando hasta que alguien se levante o pasen 6 s. Los valores del Anexo C eran 0,40 / 5 / 3.
    Con 7 videos recortados (2 caídas reales y 5 tramos sin caída) pasó de 0/2 a 2/2 sin falsos positivos; es una
    muestra chica, así que midan con sus propios videos (`scripts/evaluar_detector.py --detector caidas`).
    Se mantiene el criterio conservador de la nº 22 (sin keypoints confiables no es «acostado»).
53. **Informe Word actualizado al código (06/11/2026).** El Anexo C y la Tabla 2 pasan a los valores de la nº 52
    (inmovilidad de caídas 3 s, confianza 0,25, tolerancia relativa), y el texto describe lo que hace el código: el
    movimiento es XOR de grises cuantizados a 4 bits (no de imágenes binarizadas), YOLO general no se limita a las
    regiones con movimiento y el benchmark reporta la mediana sin medir CPU. Se agregó la Tabla 8 con las cinco
    variantes, incluido que a igual área HSV de OpenCV es más rápido que la tabla de bits, y el Anexo J con capturas
    en `--demo`. El dato del Atlas se cita por prensa (Opinión, 2024) porque no se halló la fuente oficial.
54. **Se quita la anomalía «piscina» (07/11/2026).** Era la más débil de las cinco: en la feria no hay piscina, así
    que había que simularla con una maqueta; YOLO no reconoce de forma confiable un muñeco como persona; en `--demo`
    nunca disparaba (solo se ejercitaba en los tests); y sumaba reglas (supervisor en el borde, inmovilidad) sin
    mediciones. Quedan 4 anomalías: intrusión, fuego, caída y puerta. Qué se eliminó: el detector, las zonas
    `piscina` y `borde_piscina`, `alarmas.piscina` y `detectores.piscina` de `config.yaml`, la cámara y el video
    sintético `zona.mp4` de la demo, y sus tests. Consecuencias:
    - **El byte de estado se renumeró** (en vez de dejar el bit 1 vacío): INTRUSION=1, FUEGO=2, CAIDA=4, PUERTA=8,
      `TODAS`=15. El panel decodifica por posición en `ANOMALIAS` (`comun.js`), que cambió igual. Un byte guardado
      con el esquema viejo ya no significa lo mismo, pero el byte no se persiste (solo viaja por WebSocket).
    - **El YOLO general ya no corre para la piscina**: lo usa solo rostros, y solo si hay zona `acceso`.
    - **Una BD anterior sigue funcionando**: `consultas.leer_overrides` descarta los overrides `detectores.piscina.*`
      y `alarmas.piscina.*` y quita «piscina» de las listas `camaras.<id>.detectores` (con `extra="forbid"` bastaría
      una clave para invalidar todos los overrides); `zonas_de_camara` ignora las zonas de tipos que ya no existen;
      y los medios de «Prueba con video» guardados con piscina pierden ese detector. Los eventos de piscina que ya
      estén en el historial se conservan y se siguen mostrando con «Todas».
    - El informe Word se actualizó en consecuencia (de 5 a 4 anomalías).
55. **Caídas: criterio de «desplome» además del «horizontal» (16/11/2026).** El grupo reportó que la caída era lo
    que menos se captaba. Medido con pose real sobre dos compilaciones de caídas de cámaras de timbre/seguridad
    (ver `docs/PRUEBAS.md`, sección 7): el detector reconocía 1 de 12 caídas. Causa: «acostado» exigía bbox ancho
    (ratio > 1,4) **y** torso a menos de 45°, y eso solo pasa con la cámara de costado; con la cámara alta o si la
    persona cae hacia la cámara, el bbox queda casi cuadrado (ratio 0,9–1,3) y el torso a 30–90°. Además la pose
    pierde a la persona hasta 1 s mientras cae. Cambios (umbrales en `config.yaml`, `detectores.caidas`):
    - **Desplome** (criterio b): en el suelo si alto / alto de pie ≤ `colapso_alto_max` (0,60), la cabeza bajó
      ≥ `descenso_min_relativo` × alto de pie y ancho/alto ≥ `colapso_ratio_min` (0,80; en cuclillas el bbox queda
      angosto). `colapso_alto_max: 0` lo desactiva y deja solo el criterio del informe.
    - No es desplome si **quien estaba de pie sigue de pie** (la persona baja es otra: un niño, alguien lejos), si
      la referencia **ya venía bajando** (mide menos de 0,6 del alto máximo de los últimos 3 × `ventana_descenso_s`:
      sentarse y después recostarse) o si esa persona baja **ya estaba ahí** antes.
    - `radio_asociacion_relativo` (0,50 × altura): con la persona cerca de la cámara, al caer de costado el centro
      se corre más que los 120 px fijos. `ventana_descenso_s` 1,0 → **1,5**.
    - **Un acompañante de pie ya no cancela la caída**: «se levantó» solo si aparecen más personas de pie sobre la
      caída que las que ya estaban a su lado cuando ocurrió.
    - Una detección «no acostada» junto a la caída y de su mismo tamaño se sigue como la persona caída (si se
      arrastra reinicia la inmovilidad).
    Resultado: 1/12 → 11/12 caídas reconocidas, sin alarmas en el tramo sin caída. Limitaciones: quien se dobla por
    la cintura y queda quieto 3 s puede disparar; los cortes de escena de una compilación crean desplomes falsos
    (no pasa con una cámara fija); las constantes `FRACCION_ERGUIDA`, `VENTANAS_ERGUIDA` y `MARGEN_CUERPO_CAIDO`
    están en `caidas.py` y no en `config.yaml` porque no son umbrales para calibrar. Pasado al informe Word (nº 59).
56. **Fuego: umbral propio para la clase humo (16/11/2026).** Con 4 videos de incendios y 3 sin fuego, 2 de los 3
    negativos daban falsa alarma. Todas venían de la clase «humo» con confianza 0,5–0,7 en pocos frames (pared clara
    con luz cálida, cielo nublado); en los incendios reales el humo y el fuego pasan de 0,7 en cientos de frames.
    Se agrega `detectores.fuego.confianza_humo` (0,70); la clase fuego sigue con `confianza_capa2` (0,50), así una
    llama chica se detecta igual de rápido. Subir `confianza_capa2` a 0,70 para todo también eliminaba las falsas
    alarmas, pero atrasaba 27 s la alarma del video de la cocina. Resultado: FP 2 → 0, VP 3 → 3. Pasado
    al informe Word (nº 59). El incendio que no detecta (`living_canada`) es una llama blanca/azulada detrás de humo: la capa 1
    de color nunca se activa, así que el YOLO ni corre.
57. **Puerta: compensación de iluminación (16/11/2026).** Medido con un banco sintético de 15 escenarios
    (`docs/PRUEBAS.md`, sección 7): apagar una luz (toda la imagen 45 niveles más oscura) contaba como puerta
    abierta, con `absdiff` y con `xor`. Ahora el detector guarda, junto con la referencia, el gris medio del resto
    de la imagen (todo menos el rectángulo de la zona) y antes de comparar le resta a la zona lo que cambió ese
    valor. Se desactiva con `detectores.puerta.compensar_iluminacion: false`. Es una corrección aditiva y global:
    no arregla una sombra que caiga solo sobre la puerta. Resultado en el banco: FP 2 → 1, VP 5 → 5. Lo que sigue
    fallando (puerta abierta que se parece a la cerrada, alguien parado delante más de 2 s) es propio de comparar
    con una referencia y queda como limitación. Pasado al informe Word (nº 59).
58. **Intrusión: la persona cuenta si su caja pisa la zona, y YuNet con confianza 0,80 (16/11/2026).** Medido con
    YuNet y SFace reales (`docs/PRUEBAS.md`, sección 7). Dos cambios:
    - **Bug:** para decidir si había una persona en la zona «acceso» se usaba el punto inferior central de su caja
      (los pies, el ancla por defecto de `sv.PolygonZone`). Frente a la cámara la persona se ve de la cintura para
      arriba y su caja llega al borde inferior de la imagen; con una zona que no llegue a ese borde nunca se le
      buscaba el rostro (0 a 1 % de los frames con una zona hasta el 75 % de la altura). Ahora cuenta la persona
      cuya caja se superpone con la máscara de la zona. El rostro sigue teniendo que estar dentro del polígono.
    - `detectores.rostros.confianza_rostro` 0,90 → **0,80**: con 0,90 YuNet encontraba el rostro en el 10 % de los
      frames de un desconocido de costado y en el 1 % de otro; con 0,80, en el 30 % y el 17 %, y dieron alarma los 4
      desconocidos en vez de 3. No aparecieron rostros falsos ni alarmas con el residente. Con 0,70 el resultado es
      el mismo que con 0,80.
    El residente tuvo algunos frames sueltos por debajo del umbral de similitud (mínimo 0,21), pero nunca 5 seguidos:
    la votación 5 de 5 es la que lo protege, así que no conviene bajarla.
59. **Informe Word actualizado (16/11/2026).** `HomeGuard AI Proyecto Investigacion.docx` (renombrado, antes con
    guiones bajos) recoge las decisiones 55 a 58: Tabla 2 (reglas de fuego, caídas y puerta), apartados 5.1.5
    (desplome), 5.1.8 (la persona cuenta si su caja pisa la zona) y 5.1.10 (compensación de luz), Tabla 7 con los
    resultados preliminares y un párrafo que los explica, limitaciones 6.3 y Tabla C1 del Anexo C (confianza de
    YuNet 0,8, humo 0,7, ventana de 1,5 s y tres filas nuevas). Se editó el XML del documento directamente; no se
    tocaron las ecuaciones numeradas, así que el desplome está descrito en el texto y no como ecuación aparte.
