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

STOP_ID = int(os.getenv("CITYBUS_STOP_ID", "2336782"))

# routeId -> человекочитаемое название.
# В ответе длинные routeId НЕ показываем.
ROUTES = [
    {"route_id": 162891, "label": "🚌 98 автобус"},
    {"route_id": 239309, "label": "🚎 1 троллейбус"},
    {"route_id": 166913, "label": "🚌 30 автобус"},
    {"route_id": 203111, "label": "🚌 31 автобус"},
    {"route_id": 219199, "label": "🚌 81 автобус"},
    {"route_id": 20465947, "label": "🚌 116 автобус"},
    {"route_id": 21161753, "label": "🚌 64 автобус"},
]

CITYBUS_HEADLESS = os.getenv("CITYBUS_HEADLESS", "1").strip() not in {"0", "false", "False", "no"}
CITYBUS_DEBUG = os.getenv("CITYBUS_DEBUG", "0").strip() in {"1", "true", "True", "yes"}

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


async def _try_post_with_headers(context, page, headers: dict) -> list[dict] | None:
    url = f"{CITYBUS_API_BASE}/arrival-board/stop/{STOP_ID}"

    # 1) httpx с реальными headers фронта
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, headers=headers, content="[]")

        log("httpx POST", r.status_code)

        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        log("httpx POST failed", repr(e))

    # 2) Playwright APIRequestContext
    try:
        r = await context.request.post(url, headers=headers, data="[]")
        body = await r.text()

        log("context.request POST", r.status)

        if r.status == 200:
            data = json.loads(body)
            if isinstance(data, list):
                return data
    except Exception as e:
        log("context.request POST failed", repr(e))

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

            log("page.fetch POST", res)

            if int(res.get("status", 0)) == 200:
                data = json.loads(res.get("text", "[]"))
                if isinstance(data, list):
                    return data
    except Exception as e:
        log("page.fetch POST failed", repr(e))

    return None


async def _fetch_arrival_rows() -> list[dict]:
    target_url_part = f"/arrival-board/stop/{STOP_ID}"

    rows_result: dict[str, list[dict]] = {}
    captured_headers: dict[str, str] = {}

    got_arrival = asyncio.Event()
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
                seen[:] = seen[-20:]

                req_headers = response.request.headers or {}

                auth = req_headers.get("x-auth-token") or req_headers.get("X-Auth-Token")
                visitor = req_headers.get("x-visitor-id") or req_headers.get("X-Visitor-Id")

                log("frontend", status, path, "auth=", bool(auth), "visitor=", bool(visitor))

                # Берём headers только из реально успешных запросов фронта.
                if status == 200 and auth and visitor and path in {"/route/list", "/stop/list"}:
                    captured_headers.clear()
                    captured_headers.update(_headers_from_frontend(req_headers))
                    got_headers.set()

                # Если сам фронт получил arrival-board нужной остановки — сразу победа.
                if target_url_part in url and status == 200:
                    text = await response.text()
                    data = json.loads(text)

                    if isinstance(data, list):
                        rows_result["rows"] = data
                        got_arrival.set()

            except Exception as e:
                log("on_response error", repr(e))

        page.on("response", lambda response: asyncio.create_task(on_response(response)))

        # Несколько прогревов. CityBus иногда сначала плюёт 401,
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
                await asyncio.wait_for(got_arrival.wait(), timeout=2.5)
            except asyncio.TimeoutError:
                pass

            if "rows" in rows_result:
                await context.close()
                await browser.close()
                return rows_result["rows"]

            try:
                await asyncio.wait_for(got_headers.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

            if captured_headers:
                rows = await _try_post_with_headers(context, page, captured_headers)

                if rows is not None:
                    await context.close()
                    await browser.close()
                    return rows

            await page.wait_for_timeout(1000)

        await context.close()
        await browser.close()

    raise RuntimeError("не смог получить arrival; seen=" + ", ".join(seen[-10:]))


def _format_routes(rows: list[dict]) -> str:
    by_route = {}

    for row in rows:
        try:
            by_route[int(row.get("routeId"))] = row
        except Exception:
            pass

    lines = ["🚌 <b>Остановка Школа №146</b>"]

    for route in ROUTES:
        route_id = route["route_id"]
        label = route["label"]
        row = by_route.get(route_id)

        if not row:
            lines.append(f"{html.escape(label)}: нет на табло")
            continue

        ru = _extract_ru(row)
        lines.append(f"{html.escape(label)}: <b>{html.escape(ru)}</b>")

    return "\n".join(lines)


async def bus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /bus

    stop_id = 2336782
    выводит data["ru"] для заданных маршрутов, но без длинных routeId.
    """
    message = update.effective_message

    try:
        rows = await _fetch_arrival_rows()

        await message.reply_text(
            _format_routes(rows),
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        await message.reply_text(
            "🚌 <b>Не смог получить автобусы</b>\n\n"
            f"<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
