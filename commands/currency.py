from currency_utils import *
from imports import *
from datetime_utils import *

async def currency(update: Update, context):
    message = update.message
    try:
        text = message.text
        curr = check_for_currency(text)
        await update.message.reply_text(curr)
    except Exception as e:
        print(e)