import asyncio
import json
import shutil
import uuid
from pathlib import Path

from telegram import Update, ReactionTypeEmoji
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from lab_factory.main import generate_lab_report_from_dirs

COLLECTING = 1
LAB_ROOT = Path("lab_sessions")
_generation_lock = asyncio.Lock()


def default_meta() -> dict:
    return {
        "university": "Университет ИТМО",
        "faculty": "",
        "subject": "",
        "student_name": "",
        "group": "",
        "teacher": "",
        "city": "Санкт-Петербург",
        "year": "2026"
    }


async def put_like(message):
    try:
        await message.get_bot().set_message_reaction(
            chat_id=message.chat_id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji("👍")],
            is_big=False,
        )
    except Exception:
        pass


async def lab_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session_id = uuid.uuid4().hex

    work_dir = LAB_ROOT / str(user_id) / session_id
    input_dir = work_dir / "input"
    output_dir = work_dir / "output"

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    context.user_data["lab_work_dir"] = str(work_dir)
    context.user_data["lab_input_dir"] = str(input_dir)
    context.user_data["lab_output_dir"] = str(output_dir)

    with open(input_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(default_meta(), f, ensure_ascii=False, indent=2)

    await update.message.reply_text(
        "Скинь всё, что нужно сделать. Как угодно: текстом, .txt, .docx, код .py, картинки если нужны.\n\n"
        "Когда всё отправишь — /lab_done.\n"
        "Отменить — /lab_cancel."
    )

    return COLLECTING


async def lab_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    input_dir_raw = context.user_data.get("lab_input_dir")

    if not input_dir_raw:
        await update.message.reply_text("/lab пропиши")
        return ConversationHandler.END

    input_dir = Path(input_dir_raw)
    msg = update.message

    if msg.document:
        doc = msg.document
        filename = doc.file_name or f"file_{doc.file_unique_id}"
        ext = Path(filename).suffix.lower()

        if ext == ".py":
            save_path = input_dir / "code.py"
        elif filename == "meta.json":
            save_path = input_dir / "meta.json"
        else:
            save_path = input_dir / filename

        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(save_path))
        await put_like(msg)
        return COLLECTING

    if msg.photo:
        photo = msg.photo[-1]
        tg_file = await photo.get_file()

        save_path = input_dir / f"image_{photo.file_unique_id}.jpg"
        await tg_file.download_to_drive(custom_path=str(save_path))
        await put_like(msg)
        return COLLECTING

    if msg.text:
        assignment_path = input_dir / "assignment.txt"

        with open(assignment_path, "a", encoding="utf-8") as f:
            f.write("\n\n")
            f.write(msg.text.strip())

        await put_like(msg)
        return COLLECTING

    await msg.reply_text("ЭТО ЧЁ? СКИНЬ ЧЁ-ТО ДРУГОЕ")
    return COLLECTING


async def lab_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    input_dir_raw = context.user_data.get("lab_input_dir")

    if not input_dir_raw:
        await update.message.reply_text("Сначала начни режим лабораторной через /lab.")
        return ConversationHandler.END

    text = update.message.text.replace("/lab_edit", "", 1).strip()

    if not text:
        await update.message.reply_text(
            "А чё изменить-то?\n"
            "Например: /lab_edit Сделай вывод подробнее"
        )
        return COLLECTING

    input_dir = Path(input_dir_raw)
    notes_path = input_dir / "notes.txt"

    with open(notes_path, "a", encoding="utf-8") as f:
        f.write("\n\n[ПРАВКА ДЛЯ ПОВТОРНОЙ ГЕНЕРАЦИИ]\n")
        f.write(text)

    await put_like(update.message)
    return COLLECTING


async def lab_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    input_dir_raw = context.user_data.get("lab_input_dir")
    output_dir_raw = context.user_data.get("lab_output_dir")

    if not input_dir_raw or not output_dir_raw:
        await update.message.reply_text("/lab снова пропиши")
        return ConversationHandler.END

    input_dir = Path(input_dir_raw)
    output_dir = Path(output_dir_raw)

    command_text = update.message.text.replace("/lab_done", "", 1).strip()
    if command_text:
        notes_path = input_dir / "notes.txt"
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write("\n\n[ПРАВКА ДЛЯ ПОВТОРНОЙ ГЕНЕРАЦИИ]\n")
            f.write(command_text)

    await update.message.reply_text("ЩА БУДЕТ ЛАБА, ЖДИ")

    try:
        async with _generation_lock:
            output_docx = await asyncio.to_thread(
                generate_lab_report_from_dirs,
                input_dir,
                output_dir
            )

        with open(output_docx, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="lab_report.docx",
                caption=(
                    "Готово. Можешь написать:\n"
                    "/lab_edit <что изменить>\n"
                    "и снова вызвать /lab_done."
                )
            )

    except Exception as e:
        await update.message.reply_text(
            f"Пингуй срочно @Lev_1106. Ну либо спамь /lab_done:\n{e}"
        )

    return COLLECTING


async def lab_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    work_dir = context.user_data.get("lab_work_dir")

    if work_dir:
        shutil.rmtree(Path(work_dir), ignore_errors=True)

    context.user_data.pop("lab_work_dir", None)
    context.user_data.pop("lab_input_dir", None)
    context.user_data.pop("lab_output_dir", None)

    await update.message.reply_text("ОТМЕНИЛ")
    return ConversationHandler.END


lab_conversation = ConversationHandler(
    entry_points=[CommandHandler("lab", lab_start)],
    states={
        COLLECTING: [
            CommandHandler("lab_done", lab_done),
            CommandHandler("lab_edit", lab_edit),
            CommandHandler("lab_cancel", lab_cancel),
            MessageHandler(
                filters.TEXT | filters.Document.ALL | filters.PHOTO,
                lab_collect
            ),
        ],
    },
    fallbacks=[CommandHandler("lab_cancel", lab_cancel)],
)
