from imports import *
from datetime_utils import *

async def edit_target_message(context):
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