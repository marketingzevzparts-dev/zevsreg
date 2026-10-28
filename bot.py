import logging
import os
import re

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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

# Ссылка на группу Telegram
GROUP_URL = os.getenv("GROUP_URL", "https://t.me/+NoAgrHxYygA0Y2Ey")

ASK_REQUEST = range(1)[0]

MAX_PHONE_ASKS = 2  # скільки разів перепитуємо телефон, потім створюємо картку без нього
REMINDER_DELAY_SECONDS = 30 * 60       # напоминание "Ви тут?" через 30 хв
BUTTONS_REFRESH_DELAY_SECONDS = 60 * 60  # перемалёвка тех же кнопок через 1 годину

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_WELCOME = (
    "Вас вітає *ZEVS PARTS* — склад запчастин BYD, Leopard, Denza\n\n"
    "Наш менеджер готовий допомогти Вам з підбором запчастин, розхідників, "
    "аксесуарів.\n\n"
    "Натисніть «Відправити запит», щоб залишити звернення, або приєднуйтесь "
    "до нашої групи."
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
        "Натисни «Відправити запит» нижче, щоб менеджер розрахував вартість "
        "та наявність під твоє авто."
    ),
    "sealion05": (
        "*BYD SEA LION 05*\n\n"
        "Вітаємо в чаті Sea Lion 05!\n"
        "Потрібні оригінальні деталі, фільтри чи допи? ZEVS PARTS привезе все "
        "за VIN-кодом.\n\n"
        "Натискай кнопку «Відправити запит», і менеджер зв'яжеться для точного "
        "підбору та консультації."
    ),
    "sealion06": (
        "*BYD SEA LION 06*\n\n"
        "Привіт! Шукаєш комплектуючі на Sea Lion 06?\n"
        "ZEVS PARTS допомагає швидко знайти потрібні запчастини в наявності "
        "та під замовлення.\n\n"
        "Тисни «Відправити запит» — менеджер одразу напише в особисті "
        "та зорієнтує по цінах і термінах."
    ),
    "sealion07ev": (
        "*BYD SEA LION 07 EV*\n\n"
        "Вітаємо у спільноті Sea Lion 07 EV!\n"
        "Нужні запчастини, тюнінг або ТО? Партнер клубу ZEVS PARTS закриє "
        "будь-який запит.\n\n"
        "Натисни «Відправити запит» (кнопка нижче), щоб передати звернення "
        "менеджеру."
    ),
    "songl": (
        "*BYD SONG L*\n\n"
        "Привіт! Потрібні запчастини чи аксесуари на Song L?\n"
        "ZEVS PARTS підбере оригінальні комплектуючі без зайвих переплат.\n\n"
        "Натискай «Відправити запит», щоб менеджер зв'язався з тобою "
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
    "org": 21,  # органика из своей ТГ-групи (розділи/марки) — t.me/zeus_partsreg_bot?start=org
}


def welcome_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📝 Відправити запит", callback_data="send_request")],
        [InlineKeyboardButton("👥 Підписатися на групу", url=GROUP_URL)],
    ]
    return InlineKeyboardMarkup(buttons)


def final_keyboard() -> InlineKeyboardMarkup:
    """Кнопки после завершения заявки — те же 2 кнопки, но с другой подписью
    на первой (чтобы было понятно, что это уже НОВЫЙ запрос)."""
    buttons = [
        [InlineKeyboardButton("🆕 Новий запит", callback_data="send_request")],
        [InlineKeyboardButton("👥 Підписатися на групу", url=GROUP_URL)],
    ]
    return InlineKeyboardMarkup(buttons)


async def send_and_track(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
    """Отправляет сообщение и запоминает его ID, чтобы потом можно было удалить."""
    msg = await update.effective_chat.send_message(*args, **kwargs)
    context.user_data.setdefault("bot_message_ids", []).append(msg.message_id)
    return msg


async def clear_old_bot_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Удаляет сообщения, которые бот отправлял этому клиенту в предыдущем цикле
    (приветствие, вопросы, подтверждение и т.д.), чтобы при повторном /start
    переписка не копилась и выглядела чисто.

    Ограничение Telegram: бот может удалять только СВОИ СОБСТВЕННЫЕ сообщения —
    сообщения, отправленные самим клиентом, удалить программно нельзя, это
    ограничение самого Telegram Bot API.
    """
    message_ids = context.user_data.get("bot_message_ids", [])
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception:
            pass  # сообщение могло быть уже удалено или старше 48 часов — пропускаем
    context.user_data["bot_message_ids"] = []


def _cancel_job(context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    for job in context.job_queue.get_jobs_by_name(name):
        job.schedule_removal()


# UTM-метки в ссылке (реклама Facebook/Telegram Ads, а также органика из
# своей ТГ-групи — оба типа ссылок используют один и тот же принцип).
# Telegram разрешает в ?start= только буквы/цифры/подчёркивание/дефис —
# без "=", "&", пробелов. Поэтому UTM кодируем компактно прямо в коде ссылки:
#   ads__cmp-НАЗВАНИЕ_КАМПАНИИ__src-facebook__med-cpc__cnt-креатив1__trm-ключ
#   org__cnt-leopard__trm-запчастини   (пример для органіки з розділу "Leopard")
UTM_PREFIXES = ("ads", "org")  # источники, у которых можно разбирать UTM-хвост
UTM_FIELD_CODES = {
    "cmp": "utm_campaign",
    "src": "utm_source",
    "med": "utm_medium",
    "cnt": "utm_content",
    "trm": "utm_term",
}


def parse_ads_payload(payload: str):
    """
    Если payload начинается с одного из UTM_PREFIXES ("ads" или "org") —
    возвращаем (source_key=этот_префикс, utm_dict). Иначе (payload, {}).
    """
    for prefix in UTM_PREFIXES:
        if payload.startswith(prefix):
            utm = {}
            for part in payload.split("__")[1:]:
                for code, field in UTM_FIELD_CODES.items():
                    if part.startswith(code + "-"):
                        utm[field] = part[len(code) + 1:]
            return prefix, utm
    return payload, {}


# Ищем номер телефона прямо в тексте запроса (клиент пишет и телефон,
# и что нужно, одним сообщением). Ловим украинские/международные форматы:
# +380671234567, 380671234567, 0671234567, с пробелами/дефисами/скобками.
PHONE_PATTERN = re.compile(r"(?:\+?38)?0\d{2}[\s\-\(\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")


def extract_phone(text: str) -> str | None:
    if not text:
        return None
    match = PHONE_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group())
    return digits or None


async def refresh_buttons_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Через 1 годину просто перемальовує ті самі кнопки в тому ж повідомленні."""
    data = context.job.data
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
            reply_markup=welcome_keyboard(),
        )
    except Exception as e:
        logger.info("Не вдалося оновити кнопки (можливо, повідомлення вже видалене): %s", e)


async def remind_are_you_there_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Через 30 хв після 'Відправити запит', якщо клієнт нічого не написав."""
    chat_id = context.job.data["chat_id"]
    await context.bot.send_message(chat_id=chat_id, text="Ви тут? 🙂")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    # Стираем сообщения бота из предыдущего цикла, чтобы переписка не копилась
    await clear_old_bot_messages(update, context)

    # Отменяем "зависшие" таймеры из предыдущего цикла (если были)
    _cancel_job(context, f"reminder_{user.id}")
    _cancel_job(context, f"refresh_{user.id}")

    # Deep-link source: t.me/zeus_partsreg_bot?start=group1 -> context.args = ["group1"]
    raw_payload = context.args[0] if context.args else "direct"
    source, utm = parse_ads_payload(raw_payload)
    context.user_data["source"] = source
    context.user_data["utm"] = utm
    logger.info("Новий /start від %s, джерело: %s, utm: %s", user.id, source, utm)

    text = WELCOME_MESSAGES.get(source, DEFAULT_WELCOME)
    msg = await send_and_track(update, context, text, parse_mode="Markdown", reply_markup=welcome_keyboard())

    # Через 1 годину перемальовуємо ці ж кнопки в цьому ж повідомленні
    context.job_queue.run_once(
        refresh_buttons_job,
        when=BUTTONS_REFRESH_DELAY_SECONDS,
        chat_id=update.effective_chat.id,
        name=f"refresh_{user.id}",
        data={"chat_id": update.effective_chat.id, "message_id": msg.message_id},
    )

    return ConversationHandler.END


async def send_request_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    context.user_data.pop("pending_details", None)
    context.user_data.pop("phone_asks", None)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Напишіть, будь ласка, ваш номер телефону та що саме потрібно "
             "(запчастини, аксесуари, VIN-код тощо) — одним повідомленням:",
    )

    # Через 30 хв, якщо клієнт нічого не написав — одне нагадування "Ви тут?"
    context.job_queue.run_once(
        remind_are_you_there_job,
        when=REMINDER_DELAY_SECONDS,
        chat_id=update.effective_chat.id,
        name=f"reminder_{user.id}",
        data={"chat_id": update.effective_chat.id},
    )

    return ASK_REQUEST


async def ask_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    details = update.message.text
    user = update.effective_user

    # Клиент ответил вовремя — отменяем напоминание "Ви тут?"
    _cancel_job(context, f"reminder_{user.id}")

    # Если в сообщении нет телефона — просим написать его и ждём следующее
    # сообщение. Первый текст запроса сохраняем и склеиваем с ответом.
    phone = extract_phone(details)
    pending = context.user_data.get("pending_details")
    if pending:
        details = f"{pending}\n{details}"
        phone = phone or extract_phone(details)
    if not phone and context.user_data.get("phone_asks", 0) < MAX_PHONE_ASKS:
        context.user_data["pending_details"] = details
        context.user_data["phone_asks"] = context.user_data.get("phone_asks", 0) + 1
        await send_and_track(
            update, context,
            "📞 Напишіть, будь ласка, ваш НОМЕР ТЕЛЕФОНУ (наприклад, 067 123 45 67) — "
            "без нього менеджер не зможе з вами зв'язатися.",
        )
        context.job_queue.run_once(
            remind_are_you_there_job,
            when=REMINDER_DELAY_SECONDS,
            chat_id=update.effective_chat.id,
            name=f"reminder_{user.id}",
            data={"chat_id": update.effective_chat.id},
        )
        return ASK_REQUEST
    context.user_data.pop("pending_details", None)
    context.user_data.pop("phone_asks", None)
    full_name = user.full_name or "Без імені"
    username = f"@{user.username}" if user.username else "-"
    source = context.user_data.get("source", "direct")
    utm = context.user_data.get("utm", {})
    source_id = SOURCE_IDS.get(source)  # None -> используется источник по умолчанию из .env

    try:
        create_lead_card(full_name, phone, username, source, source_id, details, utm)
    except Exception as e:
        logger.error("Помилка створення картки в KeyCRM: %s", e)

    # Заявка пришла именно по РЕКЛАМНОЙ ссылке (?start=ads...) — сообщаем
    # об этом Facebook через Conversions API. Органику (?start=org...) в
    # Facebook не шлём — там нечего оптимизировать, это не платный трафик.
    if source == "ads":
        try:
            send_lead_event(phone=phone, telegram_user_id=user.id, source_label=source)
        except Exception as e:
            logger.error("Помилка відправки Lead-події в Facebook CAPI: %s", e)

    await send_and_track(
        update, context,
        "✅ Запит прийнято! Наш менеджер зв'яжеться з вами найближчим часом."
    )
    await send_and_track(
        update, context,
        f"{COMPANY_NAME}",
        reply_markup=final_keyboard(),
    )

    for key in ("source", "utm"):
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    _cancel_job(context, f"reminder_{user.id}")
    await send_and_track(update, context, "Запит скасовано. Введіть /start, щоб почати знову.")
    context.user_data.pop("source", None)
    context.user_data.pop("utm", None)
    return ConversationHandler.END


async def fallback_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with the same 2 buttons if user writes something outside the flow."""
    await update.message.reply_text(
        "Щоб залишити заявку — натисніть кнопку нижче, або приєднуйтесь до нашої групи:",
        reply_markup=final_keyboard(),
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(send_request_button, pattern="^send_request$"),
        ],
        states={
            ASK_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_request)],
        },
        fallbacks=[
            CommandHandler("start", start),  # /start всегда перезапускает диалог,
            # даже если клиент "застрял" на середине предыдущего сценария
            CallbackQueryHandler(send_request_button, pattern="^send_request$"),
            CommandHandler("cancel", cancel),
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_contacts))
    # ^ подхватывает только сообщения ВНЕ диалога (после его завершения / без /start)

    application.run_polling()


if __name__ == "__main__":
    main()
