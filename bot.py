import logging
import re

from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from config import ADMIN_IDS, BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CHOOSING_TOPIC_SOURCE, WAITING_CUSTOM_TOPIC, CHOOSING_MY_TOPIC, COLLECTING_ITEMS = range(4)
WAITING_NEW_TOPIC = 10

ITEMS_NEEDED = 10


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["🎯 Начать упражнение"],
            ["📋 Мои темы", "➕ Добавить тему"],
            ["📊 Статистика", "❓ Помощь"],
        ],
        resize_keyboard=True,
    )


def topic_source_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="topic:random")],
        [InlineKeyboardButton("✏️ Своя тема", callback_data="topic:custom")],
        [InlineKeyboardButton("📋 Из моих тем", callback_data="topic:mine")],
    ])


def _strip_leading_number(text: str) -> str:
    return re.sub(r"^\s*\d+[\.\)]\s*", "", text).strip()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я помогу тебе тренировать *креативное мышление* с упражнением *«Список 10»*.\n\n"
        "Суть: тебе даётся тема, ты пишешь *10 идей*. "
        "Не фильтруй — пиши всё подряд, даже абсурдное. "
        "Это тренирует мозг находить решения даже когда идеи «закончились».\n\n"
        "Нажми *«Начать упражнение»*, чтобы попробовать 🚀",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*Упражнение «Список 10»*\n\n"
        "Тебе даётся тема — напиши ровно 10 идей/способов/вариантов.\n"
        "Отправляй по одной или несколько сразу (каждую с новой строки).\n\n"
        "*Откуда берётся тема:*\n"
        "• Случайная из системного списка\n"
        "• Придуманная тобой прямо сейчас\n"
        "• Из твоего личного списка тем\n\n"
        "*Мета-упражнение:* сделай «10 тем для будущих упражнений Список 10» "
        "→ сохрани результат → темы появятся в твоём списке!\n\n"
        "/exercise — начать упражнение\n"
        "/addtopic — добавить личную тему\n"
        "/mytopics — мои темы\n"
        "/stats — статистика\n"
        "/cancel — отменить текущее действие",
        parse_mode="Markdown",
    )


async def exercise_entry_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Откуда берём тему?", reply_markup=topic_source_kb())
    return CHOOSING_TOPIC_SOURCE


async def exercise_entry_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("Откуда берём тему?", reply_markup=topic_source_kb())
    return CHOOSING_TOPIC_SOURCE


async def _launch_exercise(
    source: Update | CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    topic_text: str,
    topic_id: int | None = None,
) -> int:
    if isinstance(source, CallbackQuery):
        user_id = source.from_user.id
    else:
        user_id = source.effective_user.id

    exercise_id = db.start_exercise(user_id, topic_text, topic_id)
    context.user_data["exercise_id"] = exercise_id
    context.user_data["items"] = []
    context.user_data["topic"] = topic_text

    prompt = (
        f"🎯 *Тема:* {topic_text}\n\n"
        f"Напиши *{ITEMS_NEEDED} идей* по этой теме!\n\n"
        "Отправляй по одной или несколько сразу (каждую с новой строки). "
        "Не останавливайся — пиши всё что приходит в голову!"
    )
    if isinstance(source, CallbackQuery):
        await source.edit_message_text(prompt, parse_mode="Markdown")
    else:
        await source.message.reply_text(prompt, parse_mode="Markdown")
    return COLLECTING_ITEMS


async def cb_topic_random(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    topic = db.get_random_topic(q.from_user.id)
    if not topic:
        await q.edit_message_text("😔 Все темы использованы. Добавь свои через /addtopic!")
        return ConversationHandler.END
    return await _launch_exercise(q, context, topic["text"], topic["id"])


async def cb_topic_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Введи свою тему для упражнения:")
    return WAITING_CUSTOM_TOPIC


async def cb_topic_mine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    topics = db.get_user_topics(q.from_user.id)
    if not topics:
        await q.edit_message_text(
            "У тебя пока нет личных тем.\nДобавь через /addtopic или выбери другой вариант:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 Случайная", callback_data="topic:random")],
                [InlineKeyboardButton("✏️ Своя", callback_data="topic:custom")],
            ]),
        )
        return CHOOSING_TOPIC_SOURCE
    buttons = [
        [InlineKeyboardButton(
            t["text"][:55] + ("…" if len(t["text"]) > 55 else ""),
            callback_data=f"mytopic:{t['id']}",
        )]
        for t in topics[:20]
    ]
    await q.edit_message_text("Выбери тему:", reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSING_MY_TOPIC


async def cb_my_topic_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    topic_id = int(q.data.split(":")[1])
    topic = db.get_topic_by_id(topic_id)
    if not topic:
        await q.edit_message_text("Тема не найдена.")
        return ConversationHandler.END
    return await _launch_exercise(q, context, topic["text"], topic_id)


async def msg_custom_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    topic_text = update.message.text.strip()
    if not topic_text:
        await update.message.reply_text("Тема не может быть пустой. Попробуй ещё раз:")
        return WAITING_CUSTOM_TOPIC
    return await _launch_exercise(update, context, topic_text)


async def msg_collect_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    items: list[str] = context.user_data.get("items", [])
    exercise_id: int = context.user_data["exercise_id"]
    topic: str = context.user_data.get("topic", "")

    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    new_items = [_strip_leading_number(line) or line for line in raw_lines]

    slots_left = ITEMS_NEEDED - len(items)
    to_add = new_items[:slots_left]

    for i, item_text in enumerate(to_add, start=len(items) + 1):
        db.add_exercise_item(exercise_id, i, item_text)
        items.append(item_text)

    context.user_data["items"] = items
    total = len(items)

    if total >= ITEMS_NEEDED:
        db.complete_exercise(exercise_id)
        numbered = "\n".join(f"{i + 1}. {it}" for i, it in enumerate(items))
        await update.message.reply_text(
            f"🎉 *Упражнение завершено!*\n\n"
            f"Тема: _{topic}_\n\n"
            f"{numbered}\n\n"
            "Отлично! Регулярная практика сделает тебя настоящим генератором идей 💡",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💾 Сохранить идеи как мои темы", callback_data=f"save_topics:{exercise_id}")],
                [InlineKeyboardButton("🎯 Ещё одно упражнение", callback_data="new_exercise")],
            ]),
        )
        context.user_data.clear()
        return ConversationHandler.END

    remaining = ITEMS_NEEDED - total
    if len(to_add) == 1:
        reply = f"✅ {to_add[0]}\n\n_{remaining} {'идея' if remaining == 1 else 'идей'} осталось_"
    else:
        lines = "\n".join(f"✅ {it}" for it in to_add)
        reply = f"{lines}\n\n_Итого: {total}/{ITEMS_NEEDED}, осталось {remaining}_"

    if remaining == 3:
        reply += "\n\nПочти готово! Последний рывок 💪"
    elif remaining == 1:
        reply += "\n\nПоследняя идея — самая смелая! 🔥"

    await update.message.reply_text(reply, parse_mode="Markdown")
    return COLLECTING_ITEMS


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Отменено.", reply_markup=main_menu_kb())
    return ConversationHandler.END


async def cb_save_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    exercise_id = int(q.data.split(":")[1])
    user_id = q.from_user.id

    exercise = db.get_exercise(exercise_id)
    if not exercise or exercise["user_id"] != user_id:
        await q.answer("Ошибка: упражнение не найдено.", show_alert=True)
        return

    items = db.get_exercise_items(exercise_id)
    saved = sum(1 for item in items if db.add_topic(item["text"], "user", user_id))

    await q.edit_message_reply_markup(None)
    await q.message.reply_text(
        f"✅ Сохранено *{saved}* тем в твой список!\n"
        "Используй их через *«Из моих тем»*.",
        parse_mode="Markdown",
    )


async def addtopic_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Введи тему для упражнения «Список 10».\n\n"
        "_Например: «10 способов научиться чему-то быстро»_\n\n"
        "/cancel — отменить",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return WAITING_NEW_TOPIC


async def msg_new_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    topic_text = update.message.text.strip()
    user_id = update.effective_user.id

    is_admin = user_id in ADMIN_IDS
    source = "admin" if is_admin else "user"
    owner_id = None if is_admin else user_id

    topic_id = db.add_topic(topic_text, source, owner_id)
    if topic_id:
        scope = "для всех пользователей" if is_admin else "в твой личный список"
        await update.message.reply_text(
            f"✅ Тема добавлена {scope}!\n\n_{topic_text}_",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
    else:
        await update.message.reply_text("Такая тема уже существует.", reply_markup=main_menu_kb())
    return ConversationHandler.END


async def cmd_my_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = db.get_user_topics(update.effective_user.id)
    if not topics:
        await update.message.reply_text(
            "У тебя пока нет личных тем.\n\n"
            "Добавь через /addtopic или сделай упражнение *«10 тем для будущих упражнений»* "
            "и нажми *«Сохранить идеи как мои темы»* после завершения.",
            parse_mode="Markdown",
        )
        return
    text = "\n".join(f"{i + 1}. {t['text']}" for i, t in enumerate(topics))
    await update.message.reply_text(
        f"📋 *Твои темы ({len(topics)}):*\n\n{text}", parse_mode="Markdown"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    s = db.get_user_stats(user_id)
    personal_topics = len(db.get_user_topics(user_id))
    await update.message.reply_text(
        f"📊 *Твоя статистика:*\n\n"
        f"✅ Завершённых упражнений: *{s['completed']}*\n"
        f"📋 Личных тем: *{personal_topics}*\n"
        f"💡 Всего написано идей: *{s['completed'] * ITEMS_NEEDED}*",
        parse_mode="Markdown",
    )


def main() -> None:
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    exercise_conv = ConversationHandler(
        entry_points=[
            CommandHandler("exercise", exercise_entry_msg),
            MessageHandler(filters.Regex(r"^🎯 Начать упражнение$"), exercise_entry_msg),
            CallbackQueryHandler(exercise_entry_cb, pattern=r"^new_exercise$"),
        ],
        states={
            CHOOSING_TOPIC_SOURCE: [
                CallbackQueryHandler(cb_topic_random, pattern=r"^topic:random$"),
                CallbackQueryHandler(cb_topic_custom, pattern=r"^topic:custom$"),
                CallbackQueryHandler(cb_topic_mine, pattern=r"^topic:mine$"),
            ],
            CHOOSING_MY_TOPIC: [
                CallbackQueryHandler(cb_my_topic_chosen, pattern=r"^mytopic:\d+$"),
            ],
            WAITING_CUSTOM_TOPIC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_custom_topic),
            ],
            COLLECTING_ITEMS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_collect_item),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    addtopic_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addtopic", addtopic_start),
            MessageHandler(filters.Regex(r"^➕ Добавить тему$"), addtopic_start),
        ],
        states={
            WAITING_NEW_TOPIC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_new_topic),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Regex(r"^❓ Помощь$"), cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Статистика$"), cmd_stats))
    app.add_handler(CommandHandler("mytopics", cmd_my_topics))
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Мои темы$"), cmd_my_topics))
    app.add_handler(exercise_conv)
    app.add_handler(addtopic_conv)
    app.add_handler(CallbackQueryHandler(cb_save_topics, pattern=r"^save_topics:\d+$"))

    logger.info("Bot is running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
