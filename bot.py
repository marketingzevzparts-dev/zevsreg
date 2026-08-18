import logging
import os
from datetime import datetime

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

from sheets import append_lead

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Zeus Parts")

# Telegram-кнопки (Viber-ссылки Telegram не пропускает как inline-кнопки —
# схема viber:// не входит в разрешённый список http/https/tg://,
# поэтому номера Viber даём просто текстом ниже).
MANAGERS = [
    {
        "name": "✈️ Володимир (Telegram)",
        "url": os.getenv("MANAGER_1_TELEGRAM_URL", "https://t.me/volodymyr_zevsparts"),
    },
    {
        "name": "✈️ Олександр (Telegram)",
        "url": os.getenv("MANAGER_2_TELEGRAM_URL", "https://t.me/alexandro_zevs_parts"),
    },
]

MANAGER_1_VIBER_PHONE = os.getenv("MANAGER_1_VIBER_PHONE", "+380676455443")
MANAGER_2_VIBER_PHONE = os.getenv("MANAGER_2_VIBER_PHONE", "+380675262752")

ASK_CONTACT = range(1)[0]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def managers_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(m["name"], url=m["url"])] for m in MANAGERS]
    return InlineKeyboardMarkup(buttons)


def managers_text() -> str:
    return (
        f"{COMPANY_NAME} — зв'яжіться з менеджером:\n\n"
        f"✈️ Telegram — кнопки нижче\n\n"
        f"🟣 Viber:\n"
        f"Володимир — {MANAGER_1_VIBER_PHONE}\n"
        f"Олександр — {MANAGER_2_VIBER_PHONE}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Deep-link source: t.me/zeus_partsreg_bot?start=group1 -> context.args = ["group1"]
    source = context.args[0] if context.args else "direct"
    context.user_data["source"] = source
    logger.info("Новий /start від %s, джерело: %s", update.effective_user.id, source)

    text = (
        f"👋 Ласкаво просимо до *{COMPANY_NAME}*!\n\n"
        "Залиште заявку — поділіться контактом, і наш менеджер зв'яжеться з вами "
        "найближчим часом."
    )
    contact_button = KeyboardButton("📱 Надіслати мій контакт", request_contact=True)
    keyboard = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return ASK_CONTACT


async def ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    user = update.effective_user

    if contact is None:
        await update.message.reply_text(
            "Будь ласка, натисніть кнопку «📱 Надіслати мій контакт», щоб продовжити."
        )
        return ASK_CONTACT

    phone = contact.phone_number
    full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else "-"
    source = context.user_data.get("source", "direct")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        append_lead([timestamp, full_name, phone, username, str(user.id), source])
    except Exception as e:
        logger.error("Помилка запису в Google Sheets: %s", e)

    await update.message.reply_text(
        "✅ Заявку прийнято! Наш менеджер зв'яжеться з вами найближчим часом.\n\n"
        "Якщо не хочете чекати — напишіть менеджеру напряму:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        managers_text(),
        reply_markup=managers_keyboard(),
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Заявку скасовано. Введіть /start, щоб почати знову.",
                                     reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


async def fallback_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with manager buttons if user writes something outside the flow."""
    await update.message.reply_text(
        "Щоб залишити заявку — введіть /start.\n\n" + managers_text(),
        reply_markup=managers_keyboard(),
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_CONTACT: [MessageHandler(filters.CONTACT, ask_contact)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_contacts))
    # ^ подхватывает только сообщения ВНЕ диалога (после его завершения / без /start)

    application.run_polling()


if __name__ == "__main__":
    main()

