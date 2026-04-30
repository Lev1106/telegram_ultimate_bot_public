from commands.attestation_cmd import attestation_command
from commands.fizhma import fizhma
from imports import *
from commands import *
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from lab_handlers import lab_conversation
from commands.attestation_cmd import (
    attestation_command,
    check_attestation_updates_job,
    attestation_full_report_job,
)

async def run_jobs(application: Application):
    application.job_queue.run_repeating(
        edit_target_message,
        interval=10,
        first=0,
        name="edit_target_message"
    )
    # schedule_random_say(application.job_queue)  # Функция не определена, закомментировано

async def run_jobs(application: Application):
    application.job_queue.run_repeating(
        edit_target_message,
        interval=10,
        first=0,
        name="edit_target_message"
    )

    application.job_queue.run_repeating(
        check_attestation_updates_job,
        interval=10 * 60,
        first=0,
        name="check_attestation_updates"
    )

    application.job_queue.run_repeating(
        attestation_full_report_job,
        interval=15,
        first=3,
        name="attestation_full_report"
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_app.initialize()
    await telegram_app.start()
    await run_jobs(telegram_app)
    webhook_url = f"{os.environ['WEBHOOK_URL']}/{os.environ['BOT_TOKEN']}"
    await telegram_app.bot.set_webhook(webhook_url)
    yield

fastapi_app = FastAPI(lifespan=lifespan)
token = os.environ["BOT_TOKEN"]
telegram_app = Application.builder().token(token).concurrent_updates(False).build()

telegram_app.add_handler(lab_conversation)

telegram_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, fizhma),
    group=0
)

telegram_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, currency),
    group=1
)
#telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_qwen_messages))

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("weather", weather))
telegram_app.add_handler(CommandHandler("toggle_sleep", toggle_sleep))
telegram_app.add_handler(CommandHandler("toggle_answers", toggle_answers))
telegram_app.add_handler(CommandHandler("ocr", ocr))
telegram_app.add_handler(CommandHandler("news", news))
telegram_app.add_handler(CommandHandler("att67", attestation_command))
telegram_app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/content\d+$"), new_content))
telegram_app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/comments\d+$"), new_comments))

# telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_reaction))

@fastapi_app.get("/")
async def keep_alive():
    return {"status": "ok"}

@fastapi_app.post(f"/{os.environ['BOT_TOKEN']}")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.update_queue.put(update)
    return {"ok": True}

def start():
    uvicorn.run(fastapi_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8443)))
