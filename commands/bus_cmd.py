import os
import json
import html
import asyncio

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes


CITYBUS_SITE_URL = "https://citybus.tha.kz/"
CITYBUS_API_BASE = "https://cdu-rest-api.tha.kz"

CITYBUS_HEADLESS = os.getenv("CITYBUS_HEADLESS", "1").strip() not in {"0", "false", "False", "no"}
CITYBUS_DEBUG = os.getenv("CITYBUS_DEBUG", "0").strip() in {"1", "true", "True", "yes"}

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# stop_id -> список нужных маршрутов.
# В ответе длинные routeId НЕ показываем.
STOP_GROUPS = [
    {
        "stop_id": 2336782,
        "name": "Школа №146",
        "routes": [
            {"route_id": 162891, "label": "🚌 98 автобус"},
            {"route_id": 239309, "label": "🚎 1 троллейбус"},
            {"route_id": 166913, "label": "🚌 30 автобус"},
            {"route_id": 203111, "label": "🚌 31 автобус"},
            {"route_id": 219199, "label": "🚌 81 автобус"},
            {"route_id": 20465947, "label": "🚌 116 автобус"},
            {"route_id": 21161753, "label": "🚌 64 автобус"},
        ],
    },
    {
        "stop_id": 2387057,
        "name": 'Магазин "Детский мир"',
        "routes": [
            {"route_id": 162891, "label": "🚌 98 автобус"},
            {"route_id": 233276, "label": "🚎 5 троллейбус"},
            {"route_id": 237298, "label": "🚎 6 троллейбус"},
        ],
    },
    {
        "stop_id": 15615415,
        "name": "Желтоксан/Толе би",
        "routes": [
            {"route_id": 26143, "label": "🚌 92 автобус"},
        ],
    },
    {
        "stop_id": 2757081,
        "name": "Пр. Абылай хана",
        "routes": [
            {"route_id": 241320, "label": "🚎 9 троллейбус"},
        ],
    },
    {
        "stop_id": 1904417,
        "name": "Ул. Байкадамова",
        "routes": [
            {"route_id": 20154242, "label": "🚌 19 автобус"},
            {"route_id": 96528, "label": "🚌 56 автобус"},
        ],
    },
]


def log(*args):
    if CITYBUS_DEBUG:
        print("[BUS]", *args)


def safe_text(value) -> str:
    if value is None:
        return ""
    return str(value).encode("utf-8", "ignore").decode("utf-8", "ignore")


def _extract_ru(row: dict) -> str:
    data = row.get("data") or {}
    ru = safe_text(data.get("ru") or "").strip()

    if ru:
        return ru

    minutes = row.get("time")
    distance = row.get("distance")

    parts = []

    if isinstance(minutes, (int, float)):
        parts.append(f"~{round(minutes)} мин")

    if isinstance(distance, (int, float)):
        if distance >= 1000:
            parts.append(f"~{distance / 1000:.1f} км")
        else:
            parts.append(f"~{round(distance)} м")

    return ", ".join(parts) if parts else "нет данных"


def _headers_from_frontend(req_headers: dict) -> dict:
    out = {}

    for k, v in (req_headers or {}).items():
        key = safe_text(k)
        val = safe_text(v)

        if not key:
            continue

        lk = key.lower()

        if lk in {
            "host",
            "content-length",
            "connection",
            "accept-encoding",
        }:
            continue

        # sec-* из Playwright/httpx лучше не тащить руками.
        if lk.startswith("sec-"):
            continue

        out[key] = val

    out["Accept"] = "application/json, text/plain, */*"
    out["Content-Type"] = "application/json;charset=utf-8"
    out["Origin"] = "https://citybus.tha.kz"
    out["Referer"] = "https://citybus.tha.kz/"

    return out


async def _try_post_with_headers(context, page, headers: dict, stop_id: int) -> list[dict] | None:
    url = f"{CITYBUS_API_BASE}/arrival-board/stop/{stop_id}"

    # 1) httpx с реальными headers фронта
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, headers=headers, content="[]")

        log("httpx POST", stop_id, r.status_code)

        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        log("httpx POST failed", stop_id, repr(e))

    # 2) Playwright APIRequestContext
    try:
        r = await context.request.post(url, headers=headers, data="[]")
        body = await r.text()

        log("context.request POST", stop_id, r.status)

        if r.status == 200:
            data = json.loads(body)
            if isinstance(data, list):
                return data
    except Exception as e:
        log("context.request POST failed", stop_id, repr(e))

    # 3) fetch прямо из origin citybus.tha.kz
    try:
        auth = headers.get("X-Auth-Token") or headers.get("x-auth-token")
        visitor = headers.get("X-Visitor-Id") or headers.get("x-visitor-id")

        if auth and visitor:
            res = await page.evaluate(
                """
                async ({ url, auth, visitor }) => {
                    try {
                        const r = await fetch(url, {
                            method: "POST",
                            headers: {
                                "Accept": "application/json, text/plain, */*",
                                "Content-Type": "application/json;charset=utf-8",
                                "X-Auth-Token": auth,
                                "X-Visitor-Id": visitor
                            },
                            body: "[]",
                            credentials: "include",
                            mode: "cors"
                        });

                        const text = await r.text();

                        return {
                            ok: true,
                            status: r.status,
                            text
                        };
                    } catch (e) {
                        return {
                            ok: false,
                            status: 0,
                            text: String(e)
                        };
                    }
                }
                """,
                {
                    "url": url,
                    "auth": auth,
                    "visitor": visitor,
                },
            )

            log("page.fetch POST", stop_id, res)

            if int(res.get("status", 0)) == 200:
                data = json.loads(res.get("text", "[]"))
                if isinstance(data, list):
                    return data
    except Exception as e:
        log("page.fetch POST failed", stop_id, repr(e))

    return None


async def _fetch_all_arrivals() -> tuple[dict[int, list[dict]], dict[int, str]]:
    """
    Получаем табло сразу для всех нужных stop_id.

    Важно: браузер открывается один раз.
    Сначала ловим реальные headers из успешных /route/list или /stop/list,
    потом этими headers пробиваем все нужные /arrival-board/stop/{id}.
    """
    stop_ids = [int(group["stop_id"]) for group in STOP_GROUPS]

    rows_by_stop: dict[int, list[dict]] = {}
    errors_by_stop: dict[int, str] = {}

    captured_headers: dict[str, str] = {}

    got_headers = asyncio.Event()
    seen = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=CITYBUS_HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="ru-RU",
            user_agent=_USER_AGENT,
        )

        page = await context.new_page()

        async def on_response(response):
            try:
                url = response.url or ""

                if "cdu-rest-api.tha.kz" not in url:
                    return

                status = response.status
                path = url.split("cdu-rest-api.tha.kz", 1)[-1].split("?", 1)[0]

                seen.append(f"{status} {path}")
                seen[:] = seen[-25:]

                req_headers = response.request.headers or {}

                auth = req_headers.get("x-auth-token") or req_headers.get("X-Auth-Token")
                visitor = req_headers.get("x-visitor-id") or req_headers.get("X-Visitor-Id")

                log("frontend", status, path, "auth=", bool(auth), "visitor=", bool(visitor))

                # Берём headers только из реально успешных запросов фронта.
                if status == 200 and auth and visitor and path in {"/route/list", "/stop/list"}:
                    captured_headers.clear()
                    captured_headers.update(_headers_from_frontend(req_headers))
                    got_headers.set()

                # Если фронт сам получил arrival-board по одной из нужных остановок — сохраняем.
                for stop_id in stop_ids:
                    if f"/arrival-board/stop/{stop_id}" in path and status == 200:
                        text = await response.text()
                        data = json.loads(text)

                        if isinstance(data, list):
                            rows_by_stop[stop_id] = data

            except Exception as e:
                log("on_response error", repr(e))

        page.on("response", lambda response: asyncio.create_task(on_response(response)))

        # Прогрев. CityBus иногда сначала плюёт 401,
        # а потом на reload отдаёт 200 с нормальными headers.
        for attempt in range(1, 6):
            log("warm attempt", attempt)

            try:
                if attempt == 1:
                    await page.goto(CITYBUS_SITE_URL, wait_until="domcontentloaded", timeout=30000)
                else:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
            except PlaywrightTimeoutError:
                pass
            except Exception as e:
                log("goto/reload failed", repr(e))

            try:
                await asyncio.wait_for(got_headers.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

            if captured_headers:
                break

            await page.wait_for_timeout(1000)

        if not captured_headers and not rows_by_stop:
            await context.close()
            await browser.close()
            raise RuntimeError("не смог получить headers; seen=" + ", ".join(seen[-10:]))

        # Добираем все остановки, которых сам фронт не получил.
        for stop_id in stop_ids:
            if stop_id in rows_by_stop:
                continue

            if not captured_headers:
                errors_by_stop[stop_id] = "нет headers"
                continue

            rows = await _try_post_with_headers(context, page, captured_headers, stop_id)

            if rows is None:
                errors_by_stop[stop_id] = "не получил arrival-board"
            else:
                rows_by_stop[stop_id] = rows

        await context.close()
        await browser.close()

    return rows_by_stop, errors_by_stop


def _format_stop_group(group: dict, rows: list[dict] | None, error: str | None) -> str:
    stop_name = safe_text(group["name"])
    stop_id = int(group["stop_id"])

    lines = [
        f'<b>{html.escape(stop_name)}</b>',
    ]

    if rows is None:
        lines.append(f"⚠️ Не получил табло: <code>{html.escape(error or 'ошибка')}</code>")
        return "\n".join(lines)

    by_route = {}

    for row in rows:
        try:
            by_route[int(row.get("routeId"))] = row
        except Exception:
            pass

    for route in group["routes"]:
        route_id = int(route["route_id"])
        label = safe_text(route["label"])
        row = by_route.get(route_id)

        if not row:
            lines.append(f"{html.escape(label)}: нет на табло")
            continue

        ru = _extract_ru(row)
        lines.append(f"{html.escape(label)}: <b>{html.escape(ru)}</b>")

    return "\n".join(lines)


def _format_all(rows_by_stop: dict[int, list[dict]], errors_by_stop: dict[int, str]) -> str:
    blocks = ["🚌 <b>CityBus</b>"]

    for group in STOP_GROUPS:
        stop_id = int(group["stop_id"])
        rows = rows_by_stop.get(stop_id)
        error = errors_by_stop.get(stop_id)

        blocks.append(_format_stop_group(group, rows, error))

    return "\n\n".join(blocks)


async def bus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bus

    Выводит data["ru"] по нескольким остановкам и маршрутам.
    """
    message = update.effective_message

    try:
        rows_by_stop, errors_by_stop = await _fetch_all_arrivals()

        await message.reply_text(
            _format_all(rows_by_stop, errors_by_stop),
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        await message.reply_text(
            "🚌 <b>Не смог получить автобусы</b>\n\n"
            f"<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
