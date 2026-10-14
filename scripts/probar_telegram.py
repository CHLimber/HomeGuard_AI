"""Prueba el bot de Telegram: envía un mensaje y una foto de prueba.

Uso:
    python scripts/probar_telegram.py                    envía mensaje + foto al TELEGRAM_CHAT_ID de .env
    python scripts/probar_telegram.py --obtener-chat-id  muestra los chats que le escribieron al bot

Para obtener el chat id: abrí tu bot en Telegram, mandale cualquier mensaje
(por ej. "hola") y después ejecutá este script con --obtener-chat-id.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from homeguard.config import cargar_config, cargar_secretos  # noqa: E402
from homeguard.salidas.telegram import EnviadorTelegram, TareaTelegram  # noqa: E402


def obtener_chat_id(token: str) -> int:
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    if not r.ok:
        print(f"Error: {r.text}")
        return 1
    chats = {}
    for u in r.json().get("result", []):
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or chat.get("username")
    if not chats:
        print("No hay mensajes. Escribile algo a tu bot en Telegram y volvé a ejecutar este comando.")
        return 1
    for cid, nombre in chats.items():
        print(f"chat id: {cid}   ({nombre})")
    print("\nCopiá el número en .env como TELEGRAM_CHAT_ID=...")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--obtener-chat-id", action="store_true")
    args = parser.parse_args()
    from homeguard.logs import consola_utf8

    consola_utf8()

    s = cargar_secretos()
    if not s.telegram_token:
        print("Falta TELEGRAM_TOKEN en .env (copiá .env.example como .env). El token lo da @BotFather.")
        return 1
    if args.obtener_chat_id:
        return obtener_chat_id(s.telegram_token)
    if not s.telegram_chat_id:
        print("Falta TELEGRAM_CHAT_ID en .env. Ejecutá: python scripts/probar_telegram.py --obtener-chat-id")
        return 1

    cfg = cargar_config()
    enviador = EnviadorTelegram(s.telegram_token, s.telegram_chat_id, cfg.telegram)
    ok, msg = enviador.probar()
    print(("[ok] " if ok else "[ERROR] ") + msg)
    if not ok:
        return 1

    img = np.full((360, 640, 3), (40, 40, 40), np.uint8)
    cv2.putText(img, "HomeGuard AI - foto de prueba", (40, 190), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 255), 2)
    jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, cfg.telegram.calidad_jpeg])[1].tobytes()
    t0 = time.time()
    try:
        enviador.enviar_ahora(TareaTelegram("prueba", "📷 Foto de prueba de HomeGuard AI", jpeg, t0))
        print(f"[ok] foto enviada en {(time.time() - t0) * 1000:.0f} ms")
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] no se pudo enviar la foto: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
