from commands.bus_cmd import bus_cmd
from telegram.ext import CallbackQueryHandler
from imports import *
from commands import *
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from lab_handlers import lab_conversation

@asynccontextmanager
async def lifespan(app: FastAPI):
	await telegram_app.initialize()
	await telegram_app.start()
	webhook_url = f"{os.environ['WEBHOOK_URL']}/{os.environ['BOT_TOKEN']}"
	await telegram_app.bot.set_webhook(webhook_url)
	yield

fastapi_app = FastAPI(lifespan=lifespan)
token = os.environ["BOT_TOKEN"]
telegram_app = Application.builder().token(token).concurrent_updates(False).build()

telegram_app.add_handler(lab_conversation)


telegram_app.add_handler(
	MessageHandler(filters.TEXT & ~filters.COMMAND, currency),
	group=0
)

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("weather", weather))
telegram_app.add_handler(CommandHandler("ocr", ocr))
telegram_app.add_handler(CommandHandler("news", news))
telegram_app.add_handler(CommandHandler("bus", bus_cmd))
telegram_app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/content\d+$"), new_content))
telegram_app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/comments\d+$"), new_comments))

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

if __name__ == "__main__":
	start()
