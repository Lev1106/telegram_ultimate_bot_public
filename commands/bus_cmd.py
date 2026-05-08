import os
import json
import html
import asyncio
import time
from urllib.parse import urlparse

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes


CITYBUS_SITE_URL = "https://citybus.tha.kz/"
CITYBUS_API_BASE = "https://cdu-rest-api.tha.kz"

CITYBUS_HEADLESS = os.getenv("CITYBUS_HEADLESS", "1").strip() not in {"0", "false", "False", "no"}
CITYBUS_DEBUG = os.getenv("CITYBUS_DEBUG", "0").strip() in {"1", "true", "True", "yes"}

# На Render фронт может грузиться медленнее.
CITYBUS_WARM_TIMEOUT = float(os.getenv("CITYBUS_WARM_TIMEOUT", "25"))
CITYBUS_ATTEMPTS = int(os.getenv("CITYBUS_ATTEMPTS", "5"))

# Очень желательно на Render вынести в persistent disk:
# CITYBUS_BROWSER_DIR=/app/data/.citybus_browser
CITYBUS_BROWSER_DIR = os.getenv("CITYBUS_BROWSER_DIR", ".citybus_browser")

# Если CityBus режет Render/datacenter IP, ставь KZ/Almaty proxy:
# CITYBUS_PROXY=http://user:pass@host:port
# CITYBUS_PROXY=socks5://user:pass@host:port
CITYBUS_PROXY = os.getenv("CITYBUS_PROXY", "").strip()

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


def _playwright_proxy():
    if not CITYBUS_PROXY:
        return None

    parsed = urlparse(CITYBUS_PROXY)

    if not parsed.scheme or not parsed.hostname:
        return {"server": CITYBUS_PROXY}

    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"

    cfg = {"server": server}

    if parsed.username:
        cfg["username"] = parsed.username

    if parsed.password:
        cfg["password"] = parsed.password

    return cfg


def _httpx_proxy():
    return CITYBUS_PROXY or None


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

    try:
        async with httpx.AsyncClient(timeout=25.0, proxy=_httpx_proxy()) as client:
            r = await client.post(url, headers=headers, content="[]")

        log("httpx POST", stop_id, r.status_code)

        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        log("httpx POST failed", stop_id, repr(e))

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
    stop_ids = [int(group["stop_id"]) for group in STOP_GROUPS]

    rows_by_stop: dict[int, list[dict]] = {}
    errors_by_stop: dict[int, str] = {}

    captured_headers: dict[str, str] = {}

    got_headers = asyncio.Event()
    seen = []

    async with async_playwright() as p:
        launch_kwargs = {
            "user_data_dir": CITYBUS_BROWSER_DIR,
            "headless": CITYBUS_HEADLESS,
            "viewport": {"width": 1280, "height": 720},
            "locale": "ru-RU",
            "user_agent": _USER_AGENT,
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-dev-tools",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ],
        }

        proxy_cfg = _playwright_proxy()
        if proxy_cfg:
            launch_kwargs["proxy"] = proxy_cfg

        # Persistent context важен на Render: куки/сессия живут между /bus.
        context = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.pages[0] if context.pages else await context.new_page()

        if CITYBUS_DEBUG:
            page.on("console", lambda msg: print("[BUS][console]", msg.type, safe_text(msg.text)[:300]))

            async def on_failed(request):
                try:
                    print("[BUS][failed]", request.method, request.url, request.failure)
                except Exception:
                    pass

            page.on("requestfailed", lambda request: asyncio.create_task(on_failed(request)))

        async def on_response(response):
            try:
                url = response.url or ""

                if "cdu-rest-api.tha.kz" not in url:
                    return

                status = response.status
                path = url.split("cdu-rest-api.tha.kz", 1)[-1].split("?", 1)[0]

                seen.append(f"{status} {path}")
                seen[:] = seen[-35:]

                req_headers = response.request.headers or {}

                auth = req_headers.get("x-auth-token") or req_headers.get("X-Auth-Token")
                visitor = req_headers.get("x-visitor-id") or req_headers.get("X-Visitor-Id")

                auth_len = len(auth) if auth else 0

                log("frontend", status, path, "auth=", bool(auth), "auth_len=", auth_len, "visitor=", bool(visitor))

                if status == 200 and auth and visitor and path in {"/route/list", "/stop/list"}:
                    captured_headers.clear()
                    captured_headers.update(_headers_from_frontend(req_headers))
                    got_headers.set()

                for stop_id in stop_ids:
                    if f"/arrival-board/stop/{stop_id}" in path and status == 200:
                        text = await response.text()
                        data = json.loads(text)

                        if isinstance(data, list):
                            rows_by_stop[stop_id] = data

            except Exception as e:
                log("on_response error", repr(e))

        page.on("response", lambda response: asyncio.create_task(on_response(response)))

        last_page_state = ""

        for attempt in range(1, CITYBUS_ATTEMPTS + 1):
            log("warm attempt", attempt)

            try:
                if attempt == 1:
                    response = await page.goto(CITYBUS_SITE_URL, wait_until="domcontentloaded", timeout=45000)
                else:
                    response = await page.reload(wait_until="domcontentloaded", timeout=45000)

                if response:
                    log("page status", response.status)
            except PlaywrightTimeoutError:
                log("goto/reload timeout")
            except Exception as e:
                log("goto/reload failed", repr(e))

            started = time.monotonic()

            while time.monotonic() - started < CITYBUS_WARM_TIMEOUT:
                if got_headers.is_set():
                    break

                await page.wait_for_timeout(500)

            try:
                last_page_state = f"url={page.url}; title={await page.title()}"
                log("page state", last_page_state)
            except Exception:
                pass

            if captured_headers:
                break

            await page.wait_for_timeout(1500)

        if not captured_headers and not rows_by_stop:
            await context.close()

            debug_tail = ", ".join(seen[-12:])
            if not debug_tail:
                debug_tail = "EMPTY; " + last_page_state

            extra = ""
            if not CITYBUS_PROXY:
                extra = (
                    " | На Render это почти всегда значит, что CityBus режет datacenter IP. "
                    "Нужен CITYBUS_PROXY или VPS/KZ."
                )

            raise RuntimeError("не смог получить headers; seen=" + debug_tail + extra)

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

    return rows_by_stop, errors_by_stop


def _format_stop_group(group: dict, rows: list[dict] | None, error: str | None) -> str:
    stop_name = safe_text(group["name"])

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
