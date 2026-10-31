# Benchmark del preprocesamiento bitwise

Generado automáticamente por `python -m homeguard.preproceso.benchmark` el 31/10/2026 18:23.
Máquina: AMD64 Family 25 Model 68 Stepping 1, AuthenticAMD · Python 3.12.10 · NumPy 2.5.4 · OpenCV 5.0.0.

Tarea: capa 1 del detector de fuego (color fuego AND movimiento dentro de la zona) sobre frames de 640x480 del video sintético `fuego.mp4`. La zona ocupa el 39 % del frame (recorte 385x313). Índice de color de A, C y D: 9 bits del informe (tabla de 512).

| Variante | Descripción | ms/frame (mediana) | FPS equivalentes | Aceleración vs A | Resultado (% zona) |
|---|---|---:|---:|---:|---:|
| A | Bucle Python píxel a píxel (línea base) | 117.132 | 8.5 | 1x | 1.966 |
| B | OpenCV clásico sin ROI (HSV + absdiff) | 0.996 | 1004.0 | 118x | 1.039 |
| B2 | OpenCV clásico con ROI (HSV + absdiff) | 0.276 | 3620.6 | 424x | 1.039 |
| C | Bits sin ROI (AND, XOR, >>, \|, LUT) | 3.594 | 278.2 | 33x | 1.966 |
| D | Bits con ROI (recorte + AND + XOR + LUT) — HomeGuard | 1.459 | 685.3 | 80x | 1.966 |

Lectura (con los números de esta tabla):
- **A vs D** — vectorizar: el mismo algoritmo de bits, píxel a píxel en Python o sobre la matriz completa. Es la diferencia más grande y la razón por la que el sistema puede analizar video en tiempo real.
- **C vs D** y **B vs B2** — ROI: procesar solo el recorte de la zona (y anular el resto con AND) ahorra aproximadamente en proporción al área que se descarta.
- **B2 vs D** — bits vs HSV a igual área: compara la cuantización con AND + índice de color + LUT contra la conversión HSV optimizada de OpenCV. Ver el resultado en la tabla: si la diferencia es chica, la ventaja de la LUT no es la velocidad sino que cualquier regla de color (por compleja que sea) cuesta lo mismo: una búsqueda por píxel.
- A, C y D usan exactamente las mismas operaciones de bits, por eso dan el mismo resultado; B y B2 difieren un poco porque usan HSV exacto y umbral de diferencia en lugar de XOR de cuantizados.

Los números cambian según la computadora: volvé a ejecutar el benchmark en la laptop de la feria.
