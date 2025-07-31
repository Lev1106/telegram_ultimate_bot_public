if True: # vibecoded
	def time_before(target):
		from datetime import datetime, timedelta
		now = datetime.now(timezone(timedelta(hours=5)))
		delta = target - now

		if delta.total_seconds() > 0:
			days = delta.days
			hours, remainder = divmod(delta.seconds, 3600)
			minutes, seconds = divmod(remainder, 60)
			return (f"{days}:{hours:02}:{minutes:02}:{seconds:02}")
		else:
			return ("0:00:00:00")

	def days_passed_since(target):
		from datetime import datetime

		now = datetime.now(timezone(timedelta(hours=5)))
		delta = now - target
		days = delta.days
		if days < 0:
			days = 0

		def get_day_word(n):
			if 11 <= n % 100 <= 14:
				return "дней"
			last_digit = n % 10
			if last_digit == 1:
				return "день"
			if 2 <= last_digit <= 4:
				return "дня"
			return "дней"

		return f"{days} {get_day_word(days)}"

	def days_before(target):
		from datetime import datetime

		now = datetime.now(timezone(timedelta(hours=5)))
		delta = target - now
		days = delta.days + 1
		if days < 0:
			days = 0

		def get_day_word(n):
			if 11 <= n % 100 <= 14:
				return "дней"
			last_digit = n % 10
			if last_digit == 1:
				return "день"
			if 2 <= last_digit <= 4:
				return "дня"
			return "дней"

		return f"{days} {get_day_word(days)}"



import asyncio
import os
import json
from datetime import datetime, timedelta, timezone, time
from dotenv import load_dotenv
load_dotenv()
import requests
from telegram import Update
from telegram.ext import (
	Application, CommandHandler, MessageHandler,
	ContextTypes, filters
)
from PIL import Image
import pytesseract
from io import BytesIO


set_sleeping_reactions = True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	message_id = update.message.message_id
	chat_id = update.message.chat_id
	# print("Message ID:", message_id)
	result = f"Привет, {update.message.from_user.name}!\n"
	result += "/start: отправляет это сообщение\n"
	result += "/weather: текущая погода и прогноз на 7 дней\n"
	result += "/toggle_sleep: переключить режим установки спящей реакции до конца ночи. По умолчанию включен\n"
	result += "/ocr: считывает текст с изображения, если возможно\n\n"
	result += f"message_id: {message_id}, chat_id: {chat_id}"
	await update.message.reply_text(result)

def code_to_weather(x):
	if x == 0:
		return "Ясно ☀️"
	elif x == 1:
		return "Преимущественно ясно 🌤"
	elif x == 2:
		return "Переменная облачность ⛅️"
	elif x == 3:
		return "Пасмурно ☁️"
	elif x == 45:
		return "Туман 🌫"
	elif x == 48:
		return "Туман с изморозью 🌫"
	elif 51 <= x <= 55:
		return "Небольшой дождь 🌦"
	elif 56 <= x <= 57:
		return "Небольшой ледяной дождь 🌦"
	elif 61 <= x <= 65:
		return "Дождь 🌧"
	elif 66 <= x <= 67:
		return "Ледяной дождь 🌧"
	elif 71 <= x <= 75:
		return "Снег 🌨"
	elif x == 77:
		return "Снежные зёрна 🌨"
	elif 80 <= x <= 82:
		return "Ливни 🌧"
	elif 85 <= x <= 86:
		return "Дождь со снегом 🌨"
	elif x == 95:
		return "Гроза 🌩"
	else:
		return "Гроза с градом ⛈"

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
	result = ""
	
	for coord in [("Алматы", 43.202273, 76.900151), ("Свети-Влас", 42.713552, 27.763397)]:
		lat, lon = coord[1], coord[2]
		url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_min,temperature_2m_max,precipitation_sum&current=weather_code,temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,precipitation,cloudcover,&timezone=auto"
		data = requests.get(url).json()
		current_data = data['current']
		result += f"<b>{coord[0]}</b>\n"
		result += f"• {code_to_weather(current_data['weather_code'])}\n"
		result += f"• Температура: <u>{current_data['temperature_2m']}°C</u> (ощущается как <u>{current_data['apparent_temperature']}°C</u>)\n"
		result += f"• Влажность: <u>{current_data['relative_humidity_2m']}%</u>\n"
		result += f"• Ветер: <u>{current_data['wind_speed_10m']} км/ч</u>\n"
		result += f"• Осадки: <u>{current_data['precipitation']} мм/ч</u>\n"
		result += f"• Облачность: <u>{current_data['cloudcover']}%</u>\n"
		
		forecast_data = data['daily']
		result += "<blockquote expandable>"
		for day in range(len(forecast_data['time'])):
			result += ""
			date = forecast_data['time'][day]
			date_dd_mm = date[8] + date[9] + '.' + date[5] + date[6]
			result += date_dd_mm
			if day == 0:
				result += " (сегодня)"
			elif day == 1:
				result += " (завтра)"
			elif day == 2:
				result += " (послезавтра)"
			result += f": <u>{forecast_data['temperature_2m_min'][day]}°C</u> — <u>{forecast_data['temperature_2m_max'][day]}°C</u>, "
			result += f"осадки <u>{forecast_data['precipitation_sum'][day]} мм</u>\n"
		result += "</blockquote>\n"

	await update.message.reply_text(result, parse_mode='HTML')


# async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
	# await update.message.reply_text(update.message.text)
	


async def toggle_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
	message = update.message
	global set_sleeping_reactions
	set_sleeping_reactions = not set_sleeping_reactions
	try:
		await context.bot.set_message_reaction(
			chat_id=update.message.chat_id,
			message_id=update.message.message_id,
			reaction=["👌"],
			is_big=False
		)
	except Exception as e:
		print(f"{e}")


async def sleep_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
	global set_sleeping_reactions
	if not set_sleeping_reactions:
		return
	now = datetime.now(timezone(timedelta(hours=5))).time()

	if now < time(8, 30):
		try:
			await context.bot.set_message_reaction(
				chat_id=update.message.chat_id,
				message_id=update.message.message_id,
				reaction=["😴"],
				is_big=False
			)
			set_sleeping_reactions = False
		except Exception as e:
			print(f"{e}")
	else:
		set_sleeping_reactions = True

async def ocr(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
		# image = Image.open(BytesIO(file_bytes))
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


# async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	# with open("events.json", "r") as f:
		# event_list = json.load(f)

	# cmd = update.message.text
	# chat_msg_id = str(update.message.chat_id) + ' ' + str(update.message.message_id)
	# lst = cmd.split()
	# # only DD.MM.YYYY HH:MM <name>
	# date = lst[1].split('.')
	# year = int(date[2])
	# month = int(date[1])
	# day = int(date[0])
	# time = lst[2].split(':')
	# hours = int(time[0])
	# minutes = int(time[1])
	
	# dt = datetime(year, month, day, hours, minutes)
	# idx = cmd[4:].index(lst[3])
	# descr = cmd[idx+4:]
	# if chat_msg_id not in dfdfgevent_list:
		# event_list[chat_msg_id] = []
	# event_list[chat_msg_id].append({"datetime": datetime.strftime(dt, "%d.%m.%Y %H:%M"), "description": descr})
	
	# for events in event_list.values():
		# events.sort(key=lambda e: datetime.strptime(e["datetime"], "%d.%m.%Y %H:%M"))
	
	# with open("events.json", "w") as f:
		# json.dump(event_list, f, indent=4)
	# await update.message.reply_text(f"аоаоао {year} {month} {day} {hours} {minutes}\n{descr}!")




def command_parsing(chat_id, cmd):
	lst = cmd.split()
	if lst[0][1:].lower() == 'add' or lst[0][1:].lower() == 'фвв':
		date = lst[1].split('.')
		year = int(date[2])
		month = int(date[1])
		day = int(date[0])
		time = lst[2].split(':')
		minutes = int(time[1])
		hours = int(time[0])
		
		add_event(chat_id, datetime(year, month, day, hours, minutes))
	else:
		print("sad")
   
async def edit_target_message(context: ContextTypes.DEFAULT_TYPE):
	bot = context.bot
	chat_id_target = int(os.getenv("CHAT_ID_TARGET"))
	msg_id_target = int(os.getenv("MSG_ID_TARGET"))
	chat_id_orig = int(os.getenv("CHAT_ID_ORIG"))
	msg_id_orig = int(os.getenv("MSG_ID_ORIG"))
	temp_chat_id = int(os.getenv("TEMP_CHAT_ID"))
	
	msg = await bot.forward_message(
		chat_id=temp_chat_id,
		from_chat_id=chat_id_orig,
		message_id=msg_id_orig
	)
	txt = msg.text
	await bot.delete_message(
		chat_id=temp_chat_id,
		message_id=msg.message_id
	)

	result = ""
	local_vars = {
		"datetime": datetime,
		"time": time,
		"timezone": timezone,
		"timedelta": timedelta,
		"time_before": time_before,
		"days_passed_since": days_passed_since,
		"days_before": days_before,
		"str": str,
		"int": int,
		"float": float,
		"len": len,
	}
	exec(txt, local_vars)

	txt = local_vars["result"]

	try:
		await bot.edit_message_text(
			chat_id=chat_id_target,
			message_id=msg_id_target,
			text=txt,
			parse_mode="HTML",
		)
	except Exception as e:
		print(e)

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

async def run_jobs(application: Application):
	application.job_queue.run_repeating(
		edit_target_message,
		interval=10,
		first=0,
		name="edit_target_message"
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

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("weather", weather))
telegram_app.add_handler(CommandHandler("toggle_sleep", toggle_sleep))
telegram_app.add_handler(CommandHandler("ocr", ocr))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_reaction))
# telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ocr))

@fastapi_app.get("/")
async def keep_alive():
	return {"status": "ok"}

@fastapi_app.post(f"/{os.environ['BOT_TOKEN']}")
async def telegram_webhook(req: Request):
	data = await req.json()
	update = Update.de_json(data, telegram_app.bot)
	await telegram_app.update_queue.put(update)
	return {"ok": True}


if __name__ == "__main__":
	import uvicorn
	uvicorn.run(fastapi_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8443)))
