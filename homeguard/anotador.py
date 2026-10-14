"""Dibuja zonas, detecciones y etiquetas sobre el frame del stream (anotadores de supervision)."""
from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np
import supervision as sv

from homeguard.detectores.base import Contexto, Zona

COLOR_ZONA = {
    "acceso": sv.Color.from_hex("#3b82f6"),
    "piscina": sv.Color.from_hex("#06b6d4"),
    "borde_piscina": sv.Color.from_hex("#22c55e"),
    "puerta": sv.Color.from_hex("#eab308"),
    "fuego": sv.Color.from_hex("#f97316"),
}
NOMBRES_COCO = {0: "persona", 15: "gato", 16: "perro"}

# paleta de 2 colores: índice 0 = normal (verde), 1 = alerta (rojo)
_PALETA = sv.ColorPalette([sv.Color.from_hex("#22c55e"), sv.Color.from_hex("#ef4444")])
_cajas = sv.BoxAnnotator(color=_PALETA, thickness=2, color_lookup=sv.ColorLookup.CLASS)
_etiquetas = sv.LabelAnnotator(color=_PALETA, text_scale=0.45, text_padding=4, color_lookup=sv.ColorLookup.CLASS,
                               text_position=sv.Position.TOP_LEFT)
_cajas_obj = sv.BoxAnnotator(thickness=2)
_etiquetas_obj = sv.LabelAnnotator(text_scale=0.45, text_padding=4)


def anotar(frame: np.ndarray, ctx: Contexto | None, zonas: list[Zona], titulo: str, fps: float = 0.0) -> np.ndarray:
    img = frame.copy()
    alto, ancho = img.shape[:2]

    for z in zonas:
        pts = z.puntos_px(ancho, alto)
        color = COLOR_ZONA.get(z.tipo, sv.Color.WHITE)
        img = sv.draw_polygon(img, pts, color=color, thickness=2)
        x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
        img = sv.draw_text(img, f"{z.nombre} [{z.tipo}]", sv.Point(x + 4, max(y - 10, 10)), text_color=sv.Color.BLACK,
                           text_scale=0.4, text_padding=3, background_color=color)

    if ctx is not None:
        # personas/mascotas del YOLO general (solo si algún detector lo pidió en este frame)
        if ctx.detecciones_calculadas:
            det = ctx.detecciones_generales()
            if len(det):
                labels = []
                for i in range(len(det)):
                    nombre = NOMBRES_COCO.get(int(det.class_id[i]), str(det.class_id[i]))
                    tid = "" if det.tracker_id is None else f" #{det.tracker_id[i]}"
                    labels.append(f"{nombre}{tid} {det.confidence[i]:.2f}")
                img = _cajas_obj.annotate(img, det)
                img = _etiquetas_obj.annotate(img, det, labels)
        # cajas y textos que pidieron los detectores
        if ctx.anotaciones:
            xyxy = np.array([a.bbox for a in ctx.anotaciones], dtype=np.float32)
            clases = np.array([1 if a.alerta else 0 for a in ctx.anotaciones], dtype=int)
            det = sv.Detections(xyxy=xyxy, class_id=clases)
            img = _cajas.annotate(img, det)
            img = _etiquetas.annotate(img, det, [a.texto for a in ctx.anotaciones])

    texto = f"{titulo}  {datetime.now():%H:%M:%S}  {fps:.1f} FPS"
    cv2.rectangle(img, (0, alto - 22), (ancho, alto), (0, 0, 0), -1)
    cv2.putText(img, texto, (6, alto - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img
