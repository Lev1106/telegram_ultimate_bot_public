import traceback

from imports import *
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from commands.deadline_store import *
from commands.edit_target_message import edit_target_message


def telegram_author_payload(user) -> dict:
    """
    Данные автора для предложения и для вставки в огромный список.
    В сам список пихаем только @username, если он есть.
    """
    if not user:
        return {
            "from_user": "unknown",
            "from_username": "",
            "author_tag": "",
        }

    username = safe_text(getattr(user, "username", "") or "").strip().lstrip("@")
    full_name = safe_text(getattr(user, "full_name", "") or "unknown").strip()

    return {
        "from_user": full_name,
        "from_username": username,
        "author_tag": f"@{username}" if username else "",
    }


async def maybe_offer_deadline(update: Update, context: CallbackContext):
    if not update.effective_message or not update.effective_message.text:
        return

    message = update.effective_message

    if message.from_user and message.from_user.is_bot:
        return

    if WATCH_CHAT_IDS and message.chat_id not in WATCH_CHAT_IDS:
        return

    item = extract_deadline_candidate(message.text)
    if not item:
        return

    proposal_id = make_proposal_id(message.chat_id, message.message_id, item)
    pending = load_pending()

    if proposal_id in pending:
        return

    author_payload = telegram_author_payload(message.from_user)
    item = item | author_payload

    pending[proposal_id] = item | {
        "chat_id": message.chat_id,
        "message_id": message.message_id,
        "created_at": datetime.now(ALM).isoformat(),
    }
    save_pending(pending)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data=f"dl_yes:{proposal_id}"),
            InlineKeyboardButton("❌ Нет", callback_data=f"dl_no:{proposal_id}"),
        ]
    ])

    await context.bot.send_message(
        chat_id=SUGGESTIONS_CHAT_ID,
        text=render_proposal_text(item),
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def deadline_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    m = re.fullmatch(r"dl_(yes|no):([a-f0-9]{16})", query.data)
    if not m:
        return

    action, proposal_id = m.group(1), m.group(2)
    pending = load_pending()
    item = pending.pop(proposal_id, None)
    save_pending(pending)

    if not item:
        await query.edit_message_text("Уже обработано или протухло, начальник.")
        return

    if action == "no":
        await query.edit_message_text(
            "❌ Не добавляю. Удалили из очереди, живём дальше.",
        )
        return

    # Новый режим: пишем дедлайн прямо в исходный пост с Python-кодом.
    try:
        changed, reason = await add_deadline_to_source_message(context, item)
    except Exception as e:
        traceback.print_exc()
        await query.edit_message_text(
            "❌ Хотел вписать в исходное сообщение, но Telegram/код дал по рукам. "
            f"Ошибка: {type(e).__name__}: {e}"
        )
        return

    if not changed:
        await query.edit_message_text(
            "⚠️ В исходное сообщение не вписал: " + safe_text(reason)
        )
        return

    # Если у тебя всё ещё есть отдельное итоговое сообщение, обновляем и его.
    # Если нет — просто оставь env CHAT_ID_TARGET/MSG_ID_TARGET такими же, или игнорируй ошибки в консоли.
    target_ok = True
    try:
        await edit_target_message(context)
    except Exception as e:
        target_ok = False
        print("[DEADLINES] source edited, but target refresh failed:", repr(e))
        traceback.print_exc()

    if target_ok:
        await query.edit_message_text(
            "✅ Вписал в исходный пост с кодом и обновил итоговое сообщение."
        )
    else:
        await query.edit_message_text(
            "✅ Вписал в исходный пост с кодом. Итоговое сообщение не обновил, смотри консоль."
        )
