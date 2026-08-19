"""
Небольшой веб-сервер, который принимает вебхук от KeyCRM (событие
"lead.change_lead_status") и отправляет уведомление в отдельный Telegram-чат
о новой карточке в воронке.

Как это работает:
1. В KeyCRM настраивается автоматизация (Настройки → Додатково → Автоматизація)
   для каждой воронки: событие "Зміна статусу воронки" со значением = первый
   статус этой воронки (в него всегда попадает новая карточка), действие —
   "Відправити Webhook" на URL этого сервера.
2. KeyCRM шлёт сюда POST-запрос с данными карточки при каждом попадании
   карточки в первый статус — то есть фактически при её создании.
3. Сервер дозапрашивает полные данные карточки (включая контакт — имя,
   телефон) через KeyCRM API и отправляет готовое сообщение в Telegram-чат.

Работает как отдельный процесс (отдельный Railway-сервис) — не связан
с основным ботом (bot.py), но может использовать тот же BOT_TOKEN, чтобы
слать сообщения от имени того же бота.
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID")  # ID нового Telegram-чата для уведомлений
KEYCRM_API_TOKEN = os.getenv("KEYCRM_API_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")  # произвольная строка-пароль в URL вебхука
PORT = int(os.getenv("PORT", "8080"))

KEYCRM_CARD_URL = "https://openapi.keycrm.app/v1/pipelines/cards/{card_id}"
TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_card_contact(card_id: int) -> dict:
    """Дозапрашивает карточку с контактом (имя, телефон) через KeyCRM API."""
    if not KEYCRM_API_TOKEN:
        return {}
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {KEYCRM_API_TOKEN}",
    }
    url = KEYCRM_CARD_URL.format(card_id=card_id)
    try:
        resp = requests.get(url, headers=headers, params={"include": "contact"}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Не вдалося отримати картку %s з KeyCRM: %s", card_id, e)
        return {}


def build_message(context: dict) -> str:
    card_id = context.get("id")
    title = context.get("title") or "Без назви"
    pipeline_id = context.get("pipeline_id")
    source_id = context.get("source_id")
    utm_source = context.get("utm_source")
    utm_campaign = context.get("utm_campaign")

    card_data = fetch_card_contact(card_id) if card_id else {}
    contact = card_data.get("contact") or {}
    name = contact.get("full_name") or "—"
    phone = contact.get("phone") or "—"

    lines = [
        "🆕 *Нова картка у воронці!*",
        "",
        f"Назва: {title}",
        f"Ім'я: {name}",
        f"Телефон: {phone}",
        f"ID картки: {card_id}",
        f"ID воронки: {pipeline_id}",
        f"ID джерела: {source_id}",
    ]
    if utm_source:
        lines.append(f"UTM джерело: {utm_source}")
    if utm_campaign:
        lines.append(f"UTM кампанія: {utm_campaign}")

    return "\n".join(lines)


def send_telegram_message(text: str) -> None:
    if not BOT_TOKEN or not NOTIFY_CHAT_ID:
        logger.error("BOT_TOKEN або NOTIFY_CHAT_ID не задані — повідомлення не відправлено")
        return
    url = TELEGRAM_SEND_URL.format(token=BOT_TOKEN)
    payload = {"chat_id": NOTIFY_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self):
        # Простой health-check для Railway
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        provided_secret = query.get("secret", [None])[0]

        if WEBHOOK_SECRET and provided_secret != WEBHOOK_SECRET:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b"{}"

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"bad json")
            return

        event = payload.get("event")
        context = payload.get("context", {})
        logger.info("Отримано вебхук: подія=%s, card_id=%s", event, context.get("id"))

        if event == "lead.change_lead_status":
            try:
                message = build_message(context)
                send_telegram_message(message)
            except Exception as e:
                logger.error("Помилка обробки вебхука: %s", e)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"error")
                return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")
    if not NOTIFY_CHAT_ID:
        raise RuntimeError("NOTIFY_CHAT_ID не задан в .env")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), WebhookHandler)
    logger.info("Webhook-сервер запущено на порту %s", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
