from imports import *

async def ocr(update: Update, context):
    if not update.message.reply_to_message:
        await update.message.reply_text("Отправлять эту команду нужно ответом на сообщение с изображением!")
        return
    if not update.message.reply_to_message.photo:
        await update.message.reply_text(update.message.reply_to_message.text)
        return

    pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'

    result = ""
    for img in update.message.reply_to_message.photo:
        file = await img.get_file()
        file_bytes = await file.download_as_bytearray()
        image = Image.open(BytesIO(file_bytes)).convert('L')
        result += pytesseract.image_to_string(image, lang='rus')
        result += "\n"

    if len(result.strip()) == 0:
        try:
            await context.bot.set_message_reaction(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id,
                reaction=["🤷‍♂️"],
                is_big=False
            )
            set_sleeping_reactions = False
        except Exception as e:
            print(f"{e}")
        return
    await update.message.reply_text(result)