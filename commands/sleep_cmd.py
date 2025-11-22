from imports import *

async def toggle_sleep(update: Update, context):
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

async def sleep_reaction(update: Update, context):
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