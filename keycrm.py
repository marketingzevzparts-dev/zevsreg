import os

import requests
from dotenv import load_dotenv

load_dotenv()

KEYCRM_API_TOKEN = os.getenv("KEYCRM_API_TOKEN")
KEYCRM_PIPELINE_ID = os.getenv("KEYCRM_PIPELINE_ID")  # если не указать — попадёт в первую воронку
KEYCRM_SOURCE_ID = os.getenv("KEYCRM_SOURCE_ID")  # необязательно, но помогает отличить источник
KEYCRM_MANAGER_ID = os.getenv("KEYCRM_MANAGER_ID")  # необязательно — ответственный менеджер

KEYCRM_API_URL = "https://openapi.keycrm.app/v1/pipelines/cards"


def create_lead_card(full_name: str, phone: str, username: str, source: str, source_id: int = None) -> dict:
    """
    Создаёт карточку в воронке KeyCRM для нового лида из Telegram-бота.
    Обязательное поле — "contact" с хотя бы одним заполненным полем
    (full_name, email или phone).

    source_id: если передан — используется он (например, конкретный источник
    под ссылку/группу). Если None — используется KEYCRM_SOURCE_ID из .env
    (общий источник по умолчанию, если задан).
    """
    if not KEYCRM_API_TOKEN:
        raise RuntimeError("KEYCRM_API_TOKEN не задан в .env")

    title = f"Заявка з Telegram-бота ({source})"

    data = {
        "title": title,
        "manager_comment": f"Username: {username}\nДжерело: {source}",
        "contact": {
            "full_name": full_name or "Без імені",
            "phone": phone,
        },
    }

    if KEYCRM_PIPELINE_ID:
        data["pipeline_id"] = int(KEYCRM_PIPELINE_ID)

    effective_source_id = source_id if source_id is not None else KEYCRM_SOURCE_ID
    if effective_source_id:
        data["source_id"] = int(effective_source_id)

    if KEYCRM_MANAGER_ID:
        data["manager_id"] = int(KEYCRM_MANAGER_ID)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {KEYCRM_API_TOKEN}",
    }

    response = requests.post(KEYCRM_API_URL, json=data, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()
