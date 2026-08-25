import hashlib
import os
import re
import time
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

FB_PIXEL_ID = os.getenv("FB_PIXEL_ID")  # он же Dataset ID в новой терминологии Meta
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")  # Events Manager → Пиксель → Conversions API → Generate Access Token
FB_TEST_EVENT_CODE = os.getenv("FB_TEST_EVENT_CODE")  # необязательно, только для проверки в Test Events

FB_API_VERSION = "v20.0"
FB_API_URL = f"https://graph.facebook.com/{FB_API_VERSION}/{{pixel_id}}/events"


def _normalize_phone(phone: str) -> str:
    """
    Facebook требует номер в международном формате БЕЗ "+" и без пробелов/скобок,
    только цифры, перед хешированием. Пример: "380671234567".
    """
    return re.sub(r"\D", "", phone or "")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def send_lead_event(phone: str = None, telegram_user_id: int = None, source_label: str = "ads") -> dict | None:
    """
    Отправляет в Facebook Conversions API событие "Lead" — чтобы реклама
    "училась" на реальных заявках и оптимизировалась по конверсиям.

    Данные хешируются (SHA-256) перед отправкой — это требование Facebook,
    сырые персональные данные API не принимает.

    Если телефон не передан (клиент больше не оставляет телефон) — используем
    Telegram ID как external_id (более слабый способ сопоставления с
    пользователем Facebook, но лучше, чем ничего).

    Возвращает None, если FB_PIXEL_ID/FB_ACCESS_TOKEN не заданы (интеграция
    просто не настроена) — это не ошибка, а штатный случай для тех, кому
    отправка в Facebook не нужна.
    """
    if not FB_PIXEL_ID or not FB_ACCESS_TOKEN:
        return None

    user_data = {}
    normalized_phone = _normalize_phone(phone) if phone else None
    if normalized_phone:
        user_data["ph"] = [_sha256(normalized_phone)]
    if telegram_user_id:
        user_data.setdefault("external_id", []).append(_sha256(str(telegram_user_id)))

    if not user_data:
        return None

    event = {
        "event_name": "Lead",
        "event_time": int(time.time()),
        "event_id": str(uuid.uuid4()),
        "action_source": "chat",  # заявка пришла через переписку в Telegram-боте
        "user_data": user_data,
        "custom_data": {
            "lead_source": source_label,
        },
    }

    payload = {
        "data": [event],
        "access_token": FB_ACCESS_TOKEN,
    }
    if FB_TEST_EVENT_CODE:
        payload["test_event_code"] = FB_TEST_EVENT_CODE

    url = FB_API_URL.format(pixel_id=FB_PIXEL_ID)
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()
