from imports import *
from weather_utils import *
from config import *

async def random_send(app, chat_id):
    while True:
        delay = random.randint(1, 10)
        await asyncio.sleep(delay)

        text = "тест"
        try:
            await bot.send_message(chat_id=chat_id, text=random_send)
        except Exception as e:
            print(e)