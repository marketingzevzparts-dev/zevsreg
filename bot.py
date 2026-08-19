import logging
import os

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from keycrm import create_lead_card
from fb_capi import send_lead_event

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
COMPANY_NAME = os.getenv("COMPANY_NAME", "ZEVS PARTS")

# Ссылка на группу Telegram (вместо кнопок менеджеров)
GROUP_URL = os.getenv("GROUP_URL", "https://t.me/+NoAgrHxYygA0Y2Ey")

ASK_CONTACT, ASK_DETAILS = range(2)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_WELCOME = (
    "Вас вітає *ZEVS PARTS* — склад запчастин BYD, Leopard, Denza\n\n"
    "Наш менеджер готовий допомогти Вам з підбором запчастин, розхідників, "
    "аксесуарів.\n\n"
    "Залишите своє звернення та наш менеджер зв'яжеться з Вами."
)

# Индивидуальные приветствия под конкретные ссылки (код после ?start=).
# Ключ — тот же код, что вы используете в ссылке: t.me/zeus_partsreg_bot?start=КОД
# Если для кода приветствия нет в словаре — используется DEFAULT_WELCOME.
WELCOME_MESSAGES = {
    "leopard3": (
        "*LEOPARD 3 (Bao 3)*\n\n"
        "Привіт! Шукаєш запчастини чи аксесуари для Leopard 3?\n"
        "Наш партнер ZEVS PARTS підбере будь-яку деталь напряму з Китаю — від "
        "розхідників до кузовщини.\n\n"
        "Натисни «Поділитися контактом» нижче, щоб менеджер розрахував вартість "
        "та наявність під твоє авто."
    ),
    "sealion05": (
        "*BYD SEA LION 05*\n\n"
        "Вітаємо в чаті Sea Lion 05!\n"
        "Потрібні оригінальні деталі, фільтри чи допи? ZEVS PARTS привезе все "
        "за VIN-кодом.\n\n"
        "Натискай кнопку «Надіслати номер», і менеджер зв'яжеться для точного "
        "підбору та консультації."
    ),
    "sealion06": (
        "*BYD SEA LION 06*\n\n"
        "Привіт! Шукаєш комплектуючі на Sea Lion 06?\n"
        "ZEVS PARTS допомагає швидко знайти потрібні запчастини в наявності "
        "та під замовлення.\n\n"
        "Тисни «Поділитися контактом» — менеджер одразу напише в особисті "
        "та зорієнтує по цінах і термінах."
    ),
    "sealion07ev": (
        "*BYD SEA LION 07 EV*\n\n"
        "Вітаємо у спільноті Sea Lion 07 EV!\n"
        "Нужні запчастини, тюнінг або ТО? Партнер клубу ZEVS PARTS закриє "
        "будь-який запит.\n\n"
        "Натисни «Запросити дзвінок / Підбір» (кнопка нижче), щоб передати "
        "номер менеджеру."
    ),
    "songl": (
        "*BYD SONG L*\n\n"
        "Привіт! Потрібні запчастини чи аксесуари на Song L?\n"
        "ZEVS PARTS підбере оригінальні комплектуючі без зайвих переплат.\n\n"
        "Натискай «Поділитися контактом», щоб менеджер зв'язався з тобою "
        "та уточнив деталі."
    ),
}

# Сопоставление кода ссылки (?start=КОД) → ID источника в KeyCRM.
# Источники созданы в KeyCRM: Настройки → Джерела (ID видно по наведению на "ⓘ").
SOURCE_IDS = {
    "leopard3": 15,
    "sealion05": 16,
    "sealion06": 17,
    "sealion07ev": 18,
    "songl": 19,
    "ads": 20,  # реклама Facebook/Telegram Ads — t.me/zeus_partsreg_bot?start=ads
}


def group_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("👥 Наша група в Telegram", url=GROUP_URL)]]
    return InlineKeyboardMarkup(buttons)


async def send_and_track(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
    """Отправляет сообщение и запоминает его ID, чтобы потом можно было удалить."""
    msg = await update.message.reply_text(*args, **kwargs)
    context.user_data.setdefault("bot_message_ids", []).append(msg.message_id)
    return msg


async def clear_old_bot_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Удаляет сообщения, которые бот отправлял этому клиенту в предыдущем цикле
    (приветствие, вопросы, подтверждение и т.д.), чтобы при повторном /start
    переписка не копилась и выглядела чисто.

    Ограничение Telegram: бот может удалять только СВОИ СОБСТВЕННЫЕ сообщения —
    сообщения, отправленные самим клиентом (его /start, VIN-код и т.д.),
    удалить программно нельзя, это ограничение самого Telegram Bot API.
    """
    message_ids = context.user_data.get("bot_message_ids", [])
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception:
            pass  # сообщение могло быть уже удалено или старше 48 часов — пропускаем
    context.user_data["bot_message_ids"] = []


# UTM-метки в ссылке для рекламы (Facebook/Telegram Ads).
# Telegram разрешает в ?start= только буквы/цифры/подчёркивание/дефис —
# без "=", "&", пробелов. Поэтому UTM кодируем компактно прямо в коде ссылки:
#   ads__cmp-НАЗВАНИЕ_КАМПАНИИ__src-facebook__med-cpc__cnt-креатив1__trm-ключ
# Каждый параметр необязателен, можно указать только нужные. Например:
#   t.me/zeus_partsreg_bot?start=ads__cmp-litni_znizky__src-facebook__med-cpc
UTM_PREFIX = "ads"
UTM_FIELD_CODES = {
    "cmp": "utm_campaign",
    "src": "utm_source",
    "med": "utm_medium",
    "cnt": "utm_content",
    "trm": "utm_term",
}


def parse_ads_payload(payload: str):
    """
    Если payload начинается с "ads" — считаем это рекламной ссылкой,
    возвращаем (source_key="ads", utm_dict). Иначе (payload, {}).
    """
    if not payload.startswith(UTM_PREFIX):
        return payload, {}

    utm = {}
    for part in payload.split("__")[1:]:
        for code, field in UTM_FIELD_CODES.items():
            if part.startswith(code + "-"):
                utm[field] = part[len(code) + 1:]
    return UTM_PREFIX, utm


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    # Стираем сообщения бота из предыдущего цикла, чтобы переписка не копилась
    await clear_old_bot_messages(update, context)

    # Deep-link source: t.me/zeus_partsreg_bot?start=group1 -> context.args = ["group1"]
    raw_payload = context.args[0] if context.args else "direct"
    source, utm = parse_ads_payload(raw_payload)
    context.user_data["source"] = source
    context.user_data["utm"] = utm
    logger.info("Новий /start від %s, джерело: %s, utm: %s", user.id, source, utm)

    text = WELCOME_MESSAGES.get(source, DEFAULT_WELCOME)
    contact_button = KeyboardButton("📱 Надіслати мій контакт", request_contact=True)
    keyboard = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)

    await send_and_track(update, context, text, parse_mode="Markdown", reply_markup=keyboard)
    return ASK_CONTACT


async def ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    user = update.effective_user

    if contact is None:
        await send_and_track(
            update, context,
            "Будь ласка, натисніть кнопку «📱 Надіслати мій контакт», щоб продовжити."
        )
        return ASK_CONTACT

    # Сохраняем контакт, карточку создадим после ответа на следующий вопрос
    context.user_data["phone"] = contact.phone_number
    context.user_data["full_name"] = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
    context.user_data["username"] = f"@{user.username}" if user.username else "-"

    await send_and_track(
        update, context,
        "Дякуємо! Тепер, будь ласка, коротко напишіть VIN-код авто та що саме "
        "потрібно (запчастини, аксесуари, розхідники тощо):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_DETAILS


async def ask_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    details = update.message.text

    phone = context.user_data.get("phone")
    full_name = context.user_data.get("full_name")
    username = context.user_data.get("username")
    source = context.user_data.get("source", "direct")
    utm = context.user_data.get("utm", {})
    source_id = SOURCE_IDS.get(source)  # None -> используется источник по умолчанию из .env

    try:
        create_lead_card(full_name, phone, username, source, source_id, details, utm)
    except Exception as e:
        logger.error("Помилка створення картки в KeyCRM: %s", e)

    # Заявка пришла по рекламной ссылке (?start=ads...) — сообщаем об этом
    # Facebook через Conversions API, чтобы реклама оптимизировалась
    if source == UTM_PREFIX:
        try:
            send_lead_event(phone, source_label=source)
        except Exception as e:
            logger.error("Помилка відправки Lead-події в Facebook CAPI: %s", e)

    await send_and_track(
        update, context,
        "✅ Заявку прийнято! Наш менеджер зв'яжеться з вами найближчим часом.\n\n"
        "Приєднуйтесь до нашої групи, щоб не пропустити новини та акції:"
    )
    await send_and_track(
        update, context,
        f"{COMPANY_NAME}",
        reply_markup=group_keyboard(),
    )

    # Чистим только рабочие данные заявки, но НЕ bot_message_ids —
    # список нужен, чтобы стереть эти же сообщения при следующем /start
    for key in ("phone", "full_name", "username", "source", "utm"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await send_and_track(
        update, context,
        "Заявку скасовано. Введіть /start, щоб почати знову.",
        reply_markup=ReplyKeyboardRemove(),
    )
    for key in ("phone", "full_name", "username", "source", "utm"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def fallback_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with group button if user writes something outside the flow."""
    await update.message.reply_text(
        "Щоб залишити заявку — введіть /start.\n\nАбо приєднуйтесь до нашої групи:",
        reply_markup=group_keyboard(),
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_CONTACT: [MessageHandler(filters.CONTACT, ask_contact)],
            ASK_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_contacts))
    # ^ подхватывает только сообщения ВНЕ диалога (после его завершения / без /start)

    application.run_polling()


if __name__ == "__main__":
    main()

