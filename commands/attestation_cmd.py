import asyncio
import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


URL = "https://wsp.kbtu.kz/AttestationView"
TERM_TITLE = os.getenv("WSP_TERM_TITLE", "2025-2026 (Көктем)")

# Если файл лежит в commands/attestation_command.py,
# то BASE_DIR будет корнем проекта.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "attestation"
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "wsp_state.json"
SNAPSHOT_FILE = DATA_DIR / "attestation_snapshot.json"
CHAT_FILE = DATA_DIR / "attestation_chat_id.txt"

FETCH_LOCK = threading.Lock()

GRADE_FIELDS = {
    "attestation_1": "A1",
    "attestation_2": "A2",
    "final": "Final",
    "letter_grade": "Grade",
}


def wait_vaadin(page, timeout=15000):
    """
    Vaadin любит показывать loading indicator.
    Ждём, пока страница хотя бы примерно успокоится.
    """
    page.wait_for_load_state("domcontentloaded", timeout=timeout)

    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PlaywrightTimeoutError:
        pass

    for selector in [
        ".v-loading-indicator",
        ".v-loading-indicator-delay",
        ".v-loading-indicator-wait",
    ]:
        try:
            page.locator(selector).wait_for(state="hidden", timeout=3000)
        except PlaywrightTimeoutError:
            pass


def login_if_needed(page, login, password):
    """
    Универсальный логин:
    - если видим password input — значит нас кинуло на форму логина
    - вводим логин в ближайший обычный input
    - пароль в password input
    - жмём кнопку входа или Enter
    """
    password_input = page.locator("input[type='password']").first

    try:
        password_input.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        print("[ATT] Уже залогинены.")
        return

    print("[ATT] Найдена форма логина, захожу...")

    text_inputs = page.locator(
        "input:not([type='hidden']):not([type='password']):not([type='submit'])"
    )

    if text_inputs.count() == 0:
        raise RuntimeError("Не нашёл поле логина. Vaadin спрятал форму.")

    text_inputs.first.fill(login)
    password_input.fill(password)

    button_selectors = [
        "button:has-text('Войти')",
        "button:has-text('Login')",
        "button:has-text('Log in')",
        "button:has-text('Sign in')",
        "input[type='submit']",
        ".v-button:has-text('Войти')",
        ".v-button:has-text('Login')",
        ".v-button:has-text('Log in')",
        ".v-button:has-text('Sign in')",
    ]

    clicked = False

    for selector in button_selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0 and locator.is_visible():
                locator.click()
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        password_input.press("Enter")

    wait_vaadin(page, timeout=20000)


def open_attestation(page):
    """
    После логина иногда остаёшься не там, где хотел.
    Поэтому ещё раз открываем нужную страницу.
    """
    page.goto(URL, wait_until="domcontentloaded")
    wait_vaadin(page, timeout=20000)

    try:
        page.get_by_text(TERM_TITLE, exact=True).wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError:
        debug_html = DATA_DIR / "debug_attestation.html"
        debug_png = DATA_DIR / "debug_attestation.png"

        debug_html.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(debug_png), full_page=True)

        raise RuntimeError(
            f"Не нашёл блок '{TERM_TITLE}'. "
            f"Сохранил {debug_html} и {debug_png}"
        )


def parse_attestation(page):
    """
    Ищем именно внешнюю Vaadin-панель нужного семестра,
    а не captionwrap, который тоже содержит 'v-panel' в class.
    """
    panel = page.locator(
        f"xpath=//span[normalize-space()='{TERM_TITLE}']"
        "/ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' v-panel ')][1]"
    ).first

    try:
        panel.locator("table.v-table-table tbody tr").first.wait_for(
            state="attached",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        debug_panel = DATA_DIR / "debug_panel.html"
        debug_panel.write_text(panel.inner_html(), encoding="utf-8")
        raise RuntimeError(f"Панель нашёл, но строк внутри неё нет. Сохранил {debug_panel}")

    rows = panel.locator("table.v-table-table tbody tr")
    result = []

    for i in range(rows.count()):
        row = rows.nth(i)

        cells = row.locator("td.v-table-cell-content .v-table-cell-wrapper")
        values = [
            cells.nth(j).inner_text().replace("\xa0", " ").strip()
            for j in range(cells.count())
        ]

        if len(values) >= 3 and values[0].strip():
            result.append({
                "code": values[0],
                "course": values[1],
                "attestation_1": values[2] if len(values) > 2 else "",
                "attestation_2": values[3] if len(values) > 3 else "",
                "final": values[4] if len(values) > 4 else "",
                "letter_grade": values[5] if len(values) > 5 else "",
                "extra": values[6] if len(values) > 6 else "",
                "raw": values,
            })

    return result


def fetch_attestation():
    """
    Синхронно лезет в WSP и возвращает список предметов.
    В async-коде запускается через asyncio.to_thread().
    """
    with FETCH_LOCK:
        load_dotenv()

        login = os.getenv("WSP_LOGIN")
        password = os.getenv("WSP_PASSWORD")

        if not login or not password:
            raise RuntimeError("Нет WSP_LOGIN/WSP_PASSWORD. Создай .env рядом со скриптом.")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                slow_mo=0,
            )

            context = None

            if STATE_FILE.exists():
                try:
                    context = browser.new_context(storage_state=str(STATE_FILE))
                except Exception as e:
                    print(f"[ATT] storage_state сломан, логинюсь заново: {e}")
                    try:
                        STATE_FILE.unlink()
                    except FileNotFoundError:
                        pass

            if context is None:
                context = browser.new_context()

            page = context.new_page()

            try:
                page.goto(URL, wait_until="domcontentloaded")
                wait_vaadin(page)

                login_if_needed(page, login, password)
                open_attestation(page)

                data = parse_attestation(page)

                if not data:
                    debug_empty_html = DATA_DIR / "debug_empty.html"
                    debug_empty_png = DATA_DIR / "debug_empty.png"

                    debug_empty_html.write_text(page.content(), encoding="utf-8")
                    page.screenshot(path=str(debug_empty_png), full_page=True)

                    raise RuntimeError(
                        "Таблицу нашёл, но строки не распарсил. "
                        f"Сохранил {debug_empty_html} и {debug_empty_png}"
                    )

                context.storage_state(path=str(STATE_FILE))
                return data

            finally:
                browser.close()

def parse_score(value):
    value = normalize_value(value)

    if not value or value == "-":
        return None

    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def calc_total(item):
    scores = [
        parse_score(item.get("attestation_1")),
        parse_score(item.get("attestation_2")),
        parse_score(item.get("final")),
    ]

    scores = [score for score in scores if score is not None]

    if not scores:
        return "-"

    return f"{sum(scores):.2f}"

def format_attestation(data):
    lines = [f"📊 Аттестация {TERM_TITLE}"]

    for item in data:
        total = calc_total(item)

        lines.append(
            f"📚 {item['course']}\n"
            f"├ A1: {item['attestation_1'] or '-'}\n"
            f"├ A2: {item['attestation_2'] or '-'}\n"
            f"├ Final: {item['final'] or '-'}\n"
            f"├ Total: {total}\n"
            f"└ Grade: {item['letter_grade'] or '-'}"
        )

    return "\n\n".join(lines)


def normalize_value(value):
    if value is None:
        return ""

    return str(value).replace("\xa0", " ").strip()


def make_item_key(item):
    code = normalize_value(item.get("code"))
    course = normalize_value(item.get("course"))

    return code or course


def load_snapshot():
    if not SNAPSHOT_FILE.exists():
        return {}

    try:
        data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ATT] Не смог прочитать snapshot: {e}")
        return {}

    return {
        make_item_key(item): item
        for item in data
        if make_item_key(item)
    }


def save_snapshot(data):
    SNAPSHOT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_attestation_chat_id(chat_id: int):
    CHAT_FILE.write_text(str(chat_id), encoding="utf-8")


def load_attestation_chat_id():
    env_chat_id = os.getenv("TG_NOTIFY_CHAT_ID")

    if env_chat_id:
        return int(env_chat_id)

    if CHAT_FILE.exists():
        text = CHAT_FILE.read_text(encoding="utf-8").strip()
        if text:
            return int(text)

    return None


def short_course_name(course):
    course_lower = course.lower()

    if "объект" in course_lower or "object" in course_lower:
        return "ООП"

    if "web" in course_lower or "веб" in course_lower:
        return "Web"

    if "қазақ" in course_lower or "казах" in course_lower:
        return "казахскому"

    if "машинамен" in course_lower or "machine" in course_lower:
        return "IML"

    if "операциялық" in course_lower or "операцион" in course_lower:
        return "ОС"

    if "дене" in course_lower:
        return "физре"

    return course


def compare_attestation(old_snapshot, new_data):
    changes = []

    for item in new_data:
        key = make_item_key(item)

        if not key:
            continue

        old_item = old_snapshot.get(key, {})
        course = normalize_value(item.get("course"))
        short_course = short_course_name(course)

        for field, label in GRADE_FIELDS.items():
            old_value = normalize_value(old_item.get(field))
            new_value = normalize_value(item.get(field))

            if not old_value and new_value:
                changes.append({
                    "type": "added",
                    "course": course,
                    "short_course": short_course,
                    "field": field,
                    "label": label,
                    "old": old_value,
                    "new": new_value,
                })

            elif old_value and new_value and old_value != new_value:
                changes.append({
                    "type": "changed",
                    "course": course,
                    "short_course": short_course,
                    "field": field,
                    "label": label,
                    "old": old_value,
                    "new": new_value,
                })

    return changes


def format_changes(changes):
    lines = ["🚨 Новые изменения в WSP"]

    for change in changes:
        if change["type"] == "added":
            lines.append(
                f"\n✅ Добавилась оценка по {change['short_course']}\n"
                f"{change['label']}: {change['new']}\n"
                f"Предмет: {change['course']}"
            )
        else:
            lines.append(
                f"\n♻️ Изменилась оценка по {change['short_course']}\n"
                f"{change['label']}: {change['old']} → {change['new']}\n"
                f"Предмет: {change['course']}"
            )

    return "\n".join(lines)


async def send_long_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    if len(text) <= 4000:
        await context.bot.send_message(chat_id=chat_id, text=text)
        return

    for i in range(0, len(text), 4000):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i + 4000])


async def reply_long_message(update: Update, text: str):
    if len(text) <= 4000:
        await update.effective_message.reply_text(text)
        return

    for i in range(0, len(text), 4000):
        await update.effective_message.reply_text(text[i:i + 4000])


async def attestation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_attestation_chat_id(chat_id)

    await update.effective_message.reply_text("Секунду, лезу в WSP... 🫡")

    try:
        data = await asyncio.to_thread(fetch_attestation)
        save_snapshot(data)

        text = format_attestation(data)
        await reply_long_message(update, text)

    except Exception as e:
        await update.effective_message.reply_text(f"Упал с ошибкой:\n{e}")


async def check_attestation_updates_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Раз в 10 минут:
    - парсим WSP
    - сравниваем с предыдущим snapshot
    - если появилось новое значение или изменилось старое — шлём уведомление
    """
    load_dotenv()

    chat_id = load_attestation_chat_id()

    if not chat_id:
        print("[ATT] Нет chat_id для уведомлений. Сначала напиши /att или задай TG_NOTIFY_CHAT_ID.")
        return

    try:
        old_snapshot = load_snapshot()
        new_data = await asyncio.to_thread(fetch_attestation)

        if not old_snapshot:
            save_snapshot(new_data)
            print("[ATT] Первый snapshot сохранён, уведомления пока не отправляю.")
            return

        changes = compare_attestation(old_snapshot, new_data)

        save_snapshot(new_data)

        if not changes:
            print("[ATT] Новых оценок нет.")
            return

        text = format_changes(changes)
        await send_long_message(context, chat_id, text)

    except Exception as e:
        print(f"[ATT] Watcher упал: {e}")

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ WSP watcher упал:\n{e}",
            )
        except Exception as send_error:
            print(f"[ATT] Не смог отправить сообщение об ошибке: {send_error}")


async def attestation_full_report_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Раз в 3 часа:
    - просто отправляет полный отчёт, как /att
    - заодно обновляет snapshot
    """
    load_dotenv()

    chat_id = load_attestation_chat_id()

    if not chat_id:
        print("[ATT] Нет chat_id для полного отчёта. Сначала напиши /att или задай TG_NOTIFY_CHAT_ID.")
        return

    try:
        data = await asyncio.to_thread(fetch_attestation)
        save_snapshot(data)

        text = "🧯 Плановая проверка WSP раз в 3 часа\n\n" + format_attestation(data)
        await send_long_message(context, chat_id, text)

    except Exception as e:
        print(f"[ATT] Full report job упал: {e}")

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Плановый /att упал:\n{e}",
            )
        except Exception as send_error:
            print(f"[ATT] Не смог отправить сообщение об ошибке: {send_error}")
