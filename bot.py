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

# 4 кнопки — Telegram и Viber для двух менеджеров.
# Значения по умолчанию уже подставлены под реальных менеджеров Zeus Parts,
# при желании поменяйте через .env
MANAGERS = [
    {
        "name": "✈️ Володимир (Telegram)",
        "url": os.getenv("MANAGER_1_TELEGRAM_URL", "https://t.me/volodymyr_zevsparts"),
    },
    {
        "name": "🟣 Володимир (Viber)",
        "url": os.getenv("MANAGER_1_VIBER_URL", "viber://chat?number=%2B380676455443"),
    },
    {
        "name": "✈️ Олександр (Telegram)",
        "url": os.getenv("MANAGER_2_TELEGRAM_URL", "https://t.me/alexandro_zevs_parts"),
    },
    {
        "name": "🟣 Олександр (Viber)",
        "url": os.getenv("MANAGER_2_VIBER_URL", "viber://chat?number=%2B380675262752"),
    },
]

ASK_NEED, ASK_CONTACT = range(2)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def managers_keyboard() -> InlineKeyboardMarkup:
    # По 2 кнопки в ряд: [Telegram, Viber] для каждого менеджера
    buttons = [
        [InlineKeyboardButton(MANAGERS[0]["name"], url=MANAGERS[0]["url"]),
         InlineKeyboardButton(MANAGERS[1]["name"], url=MANAGERS[1]["url"])],
        [InlineKeyboardButton(MANAGERS[2]["name"], url=MANAGERS[2]["url"]),
         InlineKeyboardButton(MANAGERS[3]["name"], url=MANAGERS[3]["url"])],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Deep-link source: t.me/zeus_partsreg_bot?start=group1 -> context.args = ["group1"]
    source = context.args[0] if context.args else "direct"
    context.user_data["source"] = source
    logger.info("Новый /start от %s, источник: %s", update.effective_user.id, source)

    text = (
        f"👋 Добро пожаловать в *{COMPANY_NAME}*!\n\n"
        "🚗 Автозапчасти на китайские авто — Chery, Geely, Haval, Great Wall, "
        "Changan, Exeed, JAC, Omoda, Jaecoo и др.\n\n"
        "Оставьте заявку — напишите, какая деталь нужна и на какой автомобиль, "
        "а затем поделитесь контактом. Наш менеджер свяжется с вами в ближайшее время."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    await update.message.reply_text(
        "Напишите, пожалуйста, какая деталь нужна и марка/модель/год авто:"
    )
    return ASK_NEED


async def ask_need(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["need"] = update.message.text

    contact_button = KeyboardButton("📱 Отправить мой контакт", request_contact=True)
    keyboard = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "Отлично! Теперь поделитесь контактом, чтобы менеджер мог вам перезвонить:",
        reply_markup=keyboard,
    )
    return ASK_CONTACT


async def ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    user = update.effective_user

    if contact is None:
        await update.message.reply_text(
            "Пожалуйста, нажмите кнопку «📱 Отправить мой контакт», чтобы продолжить."
        )
        return ASK_CONTACT

    phone = contact.phone_number
    full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else "-"
    need = context.user_data.get("need", "-")
    source = context.user_data.get("source", "direct")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        append_lead([timestamp, full_name, phone, username, need, str(user.id), source])
    except Exception as e:
        logger.error("Ошибка записи в Google Sheets: %s", e)

    await update.message.reply_text(
        "✅ Заявка принята! Наш менеджер свяжется с вами в ближайшее время.\n\n"
        "Если не хотите ждать — напишите менеджеру напрямую:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        f"{COMPANY_NAME} — свяжитесь с менеджером:",
        reply_markup=managers_keyboard(),
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Заявка отменена. Введите /start, чтобы начать заново.",
                                     reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


async def fallback_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with manager buttons if user writes something outside the flow."""
    await update.message.reply_text(
        "Чтобы оставить заявку — введите /start.\n\nИли напишите менеджеру напрямую:",
        reply_markup=managers_keyboard(),
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_need)],
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
