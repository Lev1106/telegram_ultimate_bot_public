from currency_utils import *
from imports import *
from datetime_utils import *

async def currency(update: Update, context):
    message = update.message
    try:
        if not message or not message.text:
            return
        text = message.text
        curr = check_for_currency(text)
        if curr:
            await update.message.reply_text(curr)
    except Exception as e:
        print(f"Error in currency handler: {e}")