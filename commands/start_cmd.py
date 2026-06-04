from imports import *

async def start(update: Update, context):
    message_id = update.message.message_id
    chat_id = update.message.chat_id
    result = f"Привет, {update.message.from_user.name}!\n"

    result += "/start: Отправляет это сообщение\n"
    result += "/weather: Отправляет текущую погоду и прогноз на 7 дней\n"
    result += "/ocr: Считывает текст с картинки\n"
    result += "/news: Отправляет актуальные новости с Tengrinews.kz\n"
    # result += f"\nmessage_id: {message_id}, chat_id: {chat_id}"
    await update.message.reply_text(result)
