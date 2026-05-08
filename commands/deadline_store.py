import re

from imports import *
from datetime_utils import time_before

import json
import hashlib
import html
from pathlib import Path
from datetime import datetime, timedelta, timezone, time as dt_time

ALM = timezone(timedelta(hours=5))
SPB = timezone(timedelta(hours=3))

# Telegram text message hard-limit. Держим запас, чтобы не упереться в 4096.
TELEGRAM_TEXT_LIMIT = int(os.getenv("TELEGRAM_TEXT_LIMIT", "4096"))


def safe_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"[\ud800-\udfff]", "", s)
    return s.encode("utf-8", "ignore").decode("utf-8", "ignore")


PENDING_FILE = Path(os.getenv("DEADLINE_PENDING_FILE", "deadline_pending.json"))

# Старый accepted-файл оставлен только для совместимости/отладки.
# Истина теперь — сообщение-источник с Python-кодом в CHAT_ID_ORIG / MSG_ID_ORIG.
ACCEPTED_FILE = Path(os.getenv("DEADLINE_EVENTS_FILE", "deadline_events.json"))

# Куда бот кидает предложения "Добавить...?"
# Если не задано — используем CHAT_ID_TARGET.
SUGGESTIONS_CHAT_ID = int(os.getenv("DEADLINE_SUGGESTIONS_CHAT_ID", os.getenv("CHAT_ID_TARGET", "0")))


def _parse_id_set(raw: str) -> set[int]:
    out = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            pass
    return out


WATCH_CHAT_IDS = _parse_id_set(os.getenv("DEADLINE_WATCH_CHAT_IDS", ""))

MONTHS = {
    "января": 1, "январь": 1,
    "февраля": 2, "февраль": 2,
    "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7,
    "августа": 8, "август": 8,
    "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10,
    "ноября": 11, "ноябрь": 11,
    "декабря": 12, "декабрь": 12,
}

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

WEEKDAYS = {
    "понедельник": 0, "понедельника": 0, "пн": 0,
    "вторник": 1, "вторника": 1, "вт": 1,
    "среду": 2, "среда": 2, "ср": 2,
    "четверг": 3, "четверга": 3, "чт": 3,
    "пятницу": 4, "пятница": 4, "пт": 4,
    "субботу": 5, "суббота": 5, "сб": 5,
    "воскресенье": 6, "воскресенья": 6, "вс": 6,
}

KEYWORDS = re.compile(
    r"\b(дедлайн|deadline|сдать|сда[чт]а|д[зс]|дз|лаба|лаб[ауеы]?|лр|отч[её]т|"
    r"проект|защит[ауы]?|экзамен|контрольн|коллок|принести|отправить|скинуть|залить|"
    r"доделать|сделать|до\s+\d|к\s+(понедельник|вторник|сред|четверг|пятниц|суббот|воскрес))\b",
    re.I,
)


# ============================================================
# JSON для pending-предложений
# ============================================================


def _load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending() -> dict:
    data = _load_json(PENDING_FILE, {})
    return data if isinstance(data, dict) else {}


def save_pending(data: dict) -> None:
    _save_json(PENDING_FILE, data)


# ============================================================
# Старый accepted-файл: оставлен, чтобы проект не падал от старых импортов.
# Новые дедлайны теперь пишутся прямо в исходный пост с кодом.
# ============================================================


def load_accepted_events() -> list[dict]:
    data = _load_json(ACCEPTED_FILE, [])
    if isinstance(data, dict):
        data = data.get("events", [])
    return data if isinstance(data, list) else []


def save_accepted_events(events: list[dict]) -> None:
    events = sorted(events, key=lambda x: x.get("datetime_iso", ""))
    _save_json(ACCEPTED_FILE, events)


def _event_key(event: dict) -> str:
    return f"{event.get('datetime_iso')}::{event.get('description')}"


def add_accepted_event(item: dict) -> bool:
    """
    Старый способ через JSON. Сейчас не используется для вставки в основное сообщение.
    Оставлен на случай, если где-то ещё в коде его дернут.
    """
    events = load_accepted_events()
    keys = {_event_key(e) for e in events}

    if _event_key(item) in keys:
        return False

    events.append({
        "datetime_iso": item["datetime_iso"],
        "description": item["description"],
        "source_text": item.get("source_text", ""),
        "created_at": datetime.now(ALM).isoformat(),
    })
    save_accepted_events(events)
    return True


# ============================================================
# Парсинг дедлайнов из сообщений
# ============================================================


def _parse_time(text: str, default_hour: int = 0, default_minute: int = 0) -> tuple[int, int]:
    # 23:59 / 9.00 / 9ч30 / в 17:00
    m = re.search(r"(?<!\d)([01]?\d|2[0-3])[:.ч]\s*([0-5]\d)(?!\d)", text)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"\b(?:в|к|до)\s+([01]?\d|2[0-3])\b", text, re.I)
    if m:
        return int(m.group(1)), 0

    return default_hour, default_minute


def _future_date(day: int, month: int, hour: int, minute: int, tz=ALM) -> datetime:
    now = datetime.now(tz)
    year = now.year
    candidate = datetime(year, month, day, hour, minute, tzinfo=tz)

    # Если дата уже явно прошла, считаем следующим годом.
    if candidate < now - timedelta(days=1):
        candidate = datetime(year + 1, month, day, hour, minute, tzinfo=tz)

    return candidate


def parse_deadline_datetime(text: str) -> datetime | None:
    text = safe_text(text).casefold()
    hour, minute = _parse_time(text, 23, 59)
    now = datetime.now(ALM)

    if re.search(r"\bсегодня\b", text):
        return datetime(now.year, now.month, now.day, hour, minute, tzinfo=ALM)

    if re.search(r"\bзавтра\b", text):
        d = now + timedelta(days=1)
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ALM)

    if re.search(r"\bпослезавтра\b", text):
        d = now + timedelta(days=2)
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ALM)

    # 25 мая / 25-го мая
    m = re.search(r"\b(\d{1,2})(?:\s*[-–—]?\s*(?:го|ое|е))?\s+([а-яё]+)\b", text, re.I)
    if m:
        day = int(m.group(1))
        month = MONTHS.get(m.group(2).casefold())
        if month:
            return _future_date(day, month, hour, minute)

    # 25.05 / 25/05 / 25-05
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", text)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year_raw = m.group(3)
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
            return datetime(year, month, day, hour, minute, tzinfo=ALM)
        return _future_date(day, month, hour, minute)

    # к пятнице / до пятницы / в четверг
    for word, weekday in WEEKDAYS.items():
        if re.search(rf"\b(к|до|на|в|во)?\s*{re.escape(word)}\b", text):
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            d = now + timedelta(days=days_ahead)
            return datetime(d.year, d.month, d.day, hour, minute, tzinfo=ALM)

    return None


def cleanup_task_text(text: str) -> str:
    text = safe_text(text).strip()

    patterns = [
        r"\b(дедлайн|deadline)\b[:\-–—]?",
        r"\b(до|к|на|в)\s+(сегодня|завтра|послезавтра)\b",
        r"\b(до|к|на|в)\s+(понедельник[ау]?|вторник[ау]?|сред[ау]?|четверг[ау]?|пятниц[еу]?|суббот[ау]?|воскресень[ея])\b",
        r"\b(до|к|на|в)\s+\d{1,2}\s+[а-яё]+(?:\s+\d{1,2}[:.]\d{2})?\b",
        r"\b(до|к|на|в)\s+\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?(?:\s+\d{1,2}[:.]\d{2})?\b",
        r"\b\d{1,2}[:.]\d{2}\b",
    ]

    for p in patterns:
        text = re.sub(p, " ", text, flags=re.I)

    text = re.sub(r"\s+", " ", text).strip(" -–—:;,。.!?\n\t")

    if len(text) > 180:
        text = text[:177].rstrip() + "..."

    return text or "Задание"


def extract_deadline_candidate(text: str) -> dict | None:
    text = safe_text(text).strip()

    if not text or len(text) > 1200:
        return None

    # Не ловим код, команды и огромные простыни с result = ...
    if text.startswith("/") or "result =" in text or "datetime(" in text:
        return None

    dt = parse_deadline_datetime(text)
    has_keyword = bool(KEYWORDS.search(text))

    if not dt or not has_keyword:
        return None

    task = cleanup_task_text(text)
    if len(task) < 3:
        return None

    return {
        "datetime_iso": dt.isoformat(),
        "description": task,
        "source_text": text,
    }


def make_proposal_id(chat_id: int, message_id: int, item: dict) -> str:
    base = f"{chat_id}:{message_id}:{item.get('datetime_iso')}:{item.get('description')}"
    return hashlib.sha256(base.encode("utf-8", errors="ignore")).hexdigest()[:16]


def format_ru_datetime(dt: datetime) -> str:
    if dt.hour == 0 and dt.minute == 0:
        return f"{dt.day} {MONTHS_RU[dt.month]}"
    return f"{dt.day} {MONTHS_RU[dt.month]}, {dt.hour}:{dt.minute:02d}"


def render_proposal_text(item: dict) -> str:
    dt = datetime.fromisoformat(item["datetime_iso"])
    return (
        "🧠 <b>Добавить в список?</b>\n\n"
        f"<b>{html.escape(format_ru_datetime(dt))}</b>\n"
        f"• {html.escape(item['description'])}\n\n"
        f"<i>Источник:</i> {html.escape(item.get('source_text', ''))[:800]}"
    )


# ============================================================
# Редактирование исходного сообщения с Python-кодом
# ============================================================


SOURCE_HEADER_RE = re.compile(
    r"<b>[^\n<]*?\{time_before\(datetime\(\s*"
    r"(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*"
    r"(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*,\s*"
    r"tzinfo\s*=\s*(alm|spb)\s*\)\)\}[^\n<]*?</b>",
    re.I,
)

TIMELINE_END_MARKERS = [
    "\n\n<b>ChatGPT</b>",
    "\n\n<b>Google</b>",
    "\n\n<b>СВО",
    "\n\nОбновлено",
]


def _dt_from_source_header(match: re.Match) -> datetime:
    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    second = int(match.group(6))
    tz_name = match.group(7).casefold()
    tz = ALM if tz_name == "alm" else SPB
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


def _tz_name_for_dt(dt: datetime) -> str:
    # Все распарсенные дедлайны сейчас ALM. Но оставим аккуратность.
    offset = dt.utcoffset()
    if offset == timedelta(hours=3):
        return "spb"
    return "alm"


def _source_code_event_block(item: dict) -> str:
    dt = datetime.fromisoformat(item["datetime_iso"])
    dt = dt.astimezone(ALM) if dt.tzinfo else dt.replace(tzinfo=ALM)
    desc = safe_text(item.get("description", "Задание")).strip() or "Задание"
    tz_name = _tz_name_for_dt(dt)

    header_date = format_ru_datetime(dt)
    return (
        f"<b>{header_date} ({{time_before(datetime({dt.year}, {dt.month}, {dt.day}, "
        f"{dt.hour}, {dt.minute}, 0, tzinfo={tz_name}))}})</b>\n"
        f"• {desc}\n"
    )


def _timeline_end_index(source_text: str) -> int:
    candidates = []
    for marker in TIMELINE_END_MARKERS:
        idx = source_text.find(marker)
        if idx != -1:
            candidates.append(idx)
    return min(candidates) if candidates else len(source_text)


def insert_event_into_source_code(source_text: str, item: dict) -> tuple[str, bool, str]:
    """
    Вставляет событие прямо в исходный Python-код сообщения.
    Возвращает: (new_source, changed, reason)
    """
    source_text = safe_text(source_text)
    desc = safe_text(item.get("description", "Задание")).strip() or "Задание"
    bullet = f"• {desc}"

    try:
        event_dt = datetime.fromisoformat(item["datetime_iso"])
    except Exception as e:
        return source_text, False, f"bad datetime_iso: {e}"

    event_dt = event_dt.astimezone(ALM) if event_dt.tzinfo else event_dt.replace(tzinfo=ALM)
    event_key = event_dt.isoformat(timespec="minutes")

    # Чтобы не плодить один и тот же bullet, если кнопку нажали дважды или pending протух.
    if bullet in source_text:
        return source_text, False, "duplicate bullet already exists in source message"

    matches = list(SOURCE_HEADER_RE.finditer(source_text))
    block = _source_code_event_block({**item, "description": desc})

    if not matches:
        insert_at = _timeline_end_index(source_text)
        new_text = source_text[:insert_at].rstrip() + "\n\n" + block + "\n" + source_text[insert_at:].lstrip("\n")
        return new_text, True, "inserted without existing headers"

    timeline_end = _timeline_end_index(source_text)

    # Если есть точный заголовок с таким же datetime — добавляем bullet внутрь существующего блока.
    for i, match in enumerate(matches):
        header_dt = _dt_from_source_header(match).astimezone(ALM)
        header_key = header_dt.isoformat(timespec="minutes")

        if header_key != event_key:
            continue

        next_header_start = matches[i + 1].start() if i + 1 < len(matches) else timeline_end
        section = source_text[match.start():next_header_start]

        if bullet in section:
            return source_text, False, "duplicate bullet already exists in section"

        # Вставляем в конец секции перед следующим датированным заголовком / ChatGPT / Google / СВО.
        insert_at = next_header_start
        prefix = source_text[:insert_at].rstrip()
        suffix = source_text[insert_at:].lstrip("\n")
        new_text = prefix + "\n" + bullet + "\n\n" + suffix
        return new_text, True, "added bullet to existing datetime section"

    # Иначе создаём новый блок перед первым более поздним заголовком.
    for match in matches:
        header_dt = _dt_from_source_header(match).astimezone(ALM)
        if event_dt < header_dt:
            insert_at = match.start()
            prefix = source_text[:insert_at].rstrip()
            suffix = source_text[insert_at:].lstrip("\n")
            new_text = prefix + "\n\n" + block + "\n" + suffix
            return new_text, True, "inserted before later datetime section"

    # Если событие позже всех датированных блоков — вставляем перед служебным хвостом.
    insert_at = timeline_end
    prefix = source_text[:insert_at].rstrip()
    suffix = source_text[insert_at:].lstrip("\n")
    new_text = prefix + "\n\n" + block + "\n" + suffix
    return new_text, True, "inserted before timeline tail"


async def fetch_source_code_message_text(bot) -> str:
    """
    Bot API не даёт обычный getMessage, поэтому используем старый трюк:
    forward в TEMP_CHAT_ID -> читаем текст -> удаляем копию.
    """
    chat_id_orig = int(os.getenv("CHAT_ID_ORIG"))
    msg_id_orig = int(os.getenv("MSG_ID_ORIG"))
    temp_chat_id = int(os.getenv("TEMP_CHAT_ID"))

    msg = await bot.forward_message(
        chat_id=temp_chat_id,
        from_chat_id=chat_id_orig,
        message_id=msg_id_orig,
    )

    try:
        return safe_text(msg.text or msg.caption or "")
    finally:
        await bot.delete_message(
            chat_id=temp_chat_id,
            message_id=msg.message_id,
        )


async def edit_source_code_message(bot, new_text: str) -> None:
    """Редактирует именно исходное сообщение с Python-кодом."""
    chat_id_orig = int(os.getenv("CHAT_ID_ORIG"))
    msg_id_orig = int(os.getenv("MSG_ID_ORIG"))

    if len(new_text) > TELEGRAM_TEXT_LIMIT:
        raise ValueError(
            f"Source message became too long: {len(new_text)} chars > {TELEGRAM_TEXT_LIMIT}. "
            "Telegram не даст отредактировать такой кирпич."
        )

    await bot.edit_message_text(
        chat_id=chat_id_orig,
        message_id=msg_id_orig,
        text=new_text,
        parse_mode=None,
        disable_web_page_preview=True,
    )


async def add_deadline_to_source_message(context, item: dict) -> tuple[bool, str]:
    """
    Главная функция для кнопки ✅ Да:
    1) читает исходный пост с Python-кодом,
    2) вставляет дедлайн в нужное место,
    3) редактирует этот же исходный пост.
    """
    bot = context.bot
    source_text = await fetch_source_code_message_text(bot)

    if not source_text.strip():
        return False, "source message is empty"

    new_text, changed, reason = insert_event_into_source_code(source_text, item)

    if not changed:
        return False, reason

    await edit_source_code_message(bot, new_text)
    return True, reason


# ============================================================
# Старый merge для совместимости. Теперь возвращает base_text как есть,
# чтобы не было дублей: события уже физически записываются в source-code message.
# ============================================================


def merge_auto_events_into_text(base_text: str) -> str:
    return base_text
