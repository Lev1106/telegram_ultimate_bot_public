import traceback

from imports import *
from datetime_utils import *


async def edit_target_message(context):
    """
    Читает исходный пост с Python-кодом из CHAT_ID_ORIG / MSG_ID_ORIG,
    исполняет его, берёт переменную result и редактирует итоговое сообщение
    CHAT_ID_TARGET / MSG_ID_TARGET.

    ВАЖНО: дедлайны теперь вставляются прямо в исходный пост.
    Поэтому никаких merge_auto_events_into_text здесь больше нет, иначе будут дубли.
    """
    bot = context.bot
    chat_id_target = int(os.getenv("CHAT_ID_TARGET"))
    msg_id_target = int(os.getenv("MSG_ID_TARGET"))
    chat_id_orig = int(os.getenv("CHAT_ID_ORIG"))
    msg_id_orig = int(os.getenv("MSG_ID_ORIG"))
    temp_chat_id = int(os.getenv("TEMP_CHAT_ID"))

    msg = await bot.forward_message(
        chat_id=temp_chat_id,
        from_chat_id=chat_id_orig,
        message_id=msg_id_orig,
    )

    txt = msg.text or msg.caption or ""

    await bot.delete_message(
        chat_id=temp_chat_id,
        message_id=msg.message_id,
    )

    if not txt.strip():
        print("[EDIT_TARGET] source message is empty")
        return False

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

    try:
        exec(txt, local_vars)
    except Exception as e:
        print("[EDIT_TARGET EXEC ERROR]", repr(e))
        traceback.print_exc()
        return False

    if "result" not in local_vars:
        print("[EDIT_TARGET] variable 'result' not found")
        return False

    result_text = str(local_vars["result"])

    try:
        await bot.edit_message_text(
            chat_id=chat_id_target,
            message_id=msg_id_target,
            text=result_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        print("[EDIT_TARGET TELEGRAM ERROR]", repr(e))
        traceback.print_exc()
        return False
