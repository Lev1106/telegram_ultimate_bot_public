# import json
# import html
# from typing import Any
#
# import httpx
# from telegram import Update
# from telegram.constants import ParseMode
# from telegram.ext import ContextTypes
#
# from commands.bus_cmd import (
#     CITYBUS_API_BASE,
#     safe_text,
# )
#
# # Эти функции есть в текущем рабочем bus_cmd_clean_citybus.py.
# # Если ты их переименуешь — debug честно упадёт и скажет где.
# try:
#     from commands.bus_cmd import open_citybus_context, attach_capture
# except Exception:
#     open_citybus_context = None
#     attach_capture = None
#
#
# MAX_TG = 3900
#
#
# # ============================================================
# # SMALL UTILS
# # ============================================================
#
# def _clip(text: str, limit: int = MAX_TG) -> str:
#     text = safe_text(text)
#
#     if len(text) <= limit:
#         return text
#
#     return text[: limit - 90] + "\n\n...<обрезано, потому что Telegram не резиновый>"
#
#
# def _json_pretty(obj: Any, limit: int = MAX_TG) -> str:
#     try:
#         text = json.dumps(obj, ensure_ascii=False, indent=2)
#     except Exception:
#         text = repr(obj)
#
#     return _clip(text, limit)
#
#
# def _html_pre(text: str) -> str:
#     return f"<pre>{html.escape(_clip(text))}</pre>"
#
#
# def _normalize_path(path: str) -> str:
#     path = safe_text(path).strip()
#
#     if not path:
#         return ""
#
#     if path.startswith("http://") or path.startswith("https://"):
#         return path
#
#     if not path.startswith("/"):
#         path = "/" + path
#
#     return CITYBUS_API_BASE + path
#
#
# def _loads_or_text(body: str):
#     try:
#         return json.loads(body)
#     except Exception:
#         return body
#
#
# async def _get_tokens() -> dict:
#     tokens = load_tokens()
#
#     if not (tokens.get("auth_token") and tokens.get("visitor_id")):
#         tokens = await refresh_citybus_tokens()
#
#     return tokens
#
#
# def _find_route_in_obj(obj: Any, route_id: int):
#     stack = [obj]
#
#     while stack:
#         cur = stack.pop()
#
#         if isinstance(cur, dict):
#             for key in ("routeId", "id", "route_id"):
#                 try:
#                     if int(cur.get(key)) == route_id:
#                         return cur
#                 except Exception:
#                     pass
#
#             stack.extend(cur.values())
#
#         elif isinstance(cur, list):
#             stack.extend(cur)
#
#     return None
#
#
# def _find_occurrences(obj: Any, needle: str, max_hits: int = 20):
#     hits = []
#     needle = str(needle)
#
#     def walk(x, path):
#         if len(hits) >= max_hits:
#             return
#
#         if isinstance(x, dict):
#             for k, v in x.items():
#                 walk(v, path + [str(k)])
#
#         elif isinstance(x, list):
#             for i, v in enumerate(x):
#                 walk(v, path + [str(i)])
#
#         else:
#             s = safe_text(x)
#             if needle in s:
#                 hits.append({
#                     "path": ".".join(path),
#                     "value": s[:300],
#                 })
#
#     walk(obj, [])
#
#     return hits
#
#
# def _interesting_keys(obj: Any) -> dict:
#     interesting = {}
#
#     needles = [
#         "stop",
#         "stops",
#         "station",
#         "stations",
#         "point",
#         "points",
#         "path",
#         "trace",
#         "direction",
#         "directions",
#         "scheme",
#         "geometry",
#         "polyline",
#         "lat",
#         "lon",
#         "lng",
#     ]
#
#     def walk(x, path):
#         if isinstance(x, dict):
#             for k, v in x.items():
#                 kl = str(k).lower()
#
#                 if any(word in kl for word in needles):
#                     interesting[".".join(path + [str(k)])] = v
#
#                 walk(v, path + [str(k)])
#
#         elif isinstance(x, list):
#             for i, v in enumerate(x[:25]):
#                 walk(v, path + [str(i)])
#
#     walk(obj, [])
#
#     return interesting
#
#
# # ============================================================
# # RAW REQUEST HELPERS
# # ============================================================
#
# async def citybus_httpx_get(path_or_url: str) -> tuple[int, str, str, dict]:
#     tokens = await _get_tokens()
#     url = _normalize_path(path_or_url)
#
#     async with httpx.AsyncClient(timeout=25.0) as client:
#         response = await client.get(
#             url,
#             headers=build_headers(tokens),
#         )
#
#     return (
#         response.status_code,
#         response.headers.get("content-type", ""),
#         response.text,
#         dict(response.headers),
#     )
#
#
# async def citybus_httpx_post(path_or_url: str, payload=None) -> tuple[int, str, str, dict]:
#     tokens = await _get_tokens()
#     url = _normalize_path(path_or_url)
#
#     if payload is None:
#         payload = []
#
#     async with httpx.AsyncClient(timeout=25.0) as client:
#         response = await client.post(
#             url,
#             headers=build_headers(tokens),
#             json=payload,
#         )
#
#     return (
#         response.status_code,
#         response.headers.get("content-type", ""),
#         response.text,
#         dict(response.headers),
#     )
#
#
# async def citybus_browser_get(path_or_url: str) -> tuple[int, str, str, dict]:
#     """
#     GET через Playwright BrowserContext, то есть ближе к рабочей цепочке /bus.
#     Это нужно, потому что голый httpx для /route/list и /stop/list у тебя отдаёт 401.
#     """
#     if open_citybus_context is None:
#         raise RuntimeError("open_citybus_context не импортировался из commands.bus_cmd")
#
#     tokens = await _get_tokens()
#     url = _normalize_path(path_or_url)
#
#     p = None
#     browser_context = None
#
#     try:
#         p, browser_context = await open_citybus_context()
#
#         page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
#
#         if attach_capture is not None:
#             await attach_capture(page, tokens)
#
#         # Открываем сайт, чтобы браузерный контекст получил cookies/session state.
#         try:
#             await page.goto("https://citybus.tha.kz/", wait_until="domcontentloaded", timeout=30000)
#         except Exception:
#             pass
#
#         await page.wait_for_timeout(2000)
#
#         response = await browser_context.request.get(
#             url,
#             headers=build_headers(tokens),
#         )
#
#         body = await response.text()
#
#         return (
#             response.status,
#             response.headers.get("content-type", ""),
#             body,
#             dict(response.headers),
#         )
#
#     finally:
#         if browser_context:
#             await browser_context.close()
#         if p:
#             await p.stop()
#
#
# async def citybus_browser_post(path_or_url: str, payload=None) -> tuple[int, str, str, dict]:
#     if open_citybus_context is None:
#         raise RuntimeError("open_citybus_context не импортировался из commands.bus_cmd")
#
#     tokens = await _get_tokens()
#     url = _normalize_path(path_or_url)
#
#     if payload is None:
#         payload = []
#
#     p = None
#     browser_context = None
#
#     try:
#         p, browser_context = await open_citybus_context()
#
#         page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
#
#         if attach_capture is not None:
#             await attach_capture(page, tokens)
#
#         try:
#             await page.goto("https://citybus.tha.kz/", wait_until="domcontentloaded", timeout=30000)
#         except Exception:
#             pass
#
#         await page.wait_for_timeout(2000)
#
#         response = await browser_context.request.post(
#             url,
#             headers=build_headers(tokens),
#             data=json.dumps(payload, ensure_ascii=False),
#         )
#
#         body = await response.text()
#
#         return (
#             response.status,
#             response.headers.get("content-type", ""),
#             body,
#             dict(response.headers),
#         )
#
#     finally:
#         if browser_context:
#             await browser_context.close()
#         if p:
#             await p.stop()
#
#
# async def citybus_smart_get(path_or_url: str) -> tuple[str, int, str, str, dict]:
#     """
#     Сначала httpx. Если 401/403 — browser_context.
#     Возвращает method_used, status, content_type, body, headers.
#     """
#     status, ctype, body, headers = await citybus_httpx_get(path_or_url)
#
#     if status not in {401, 403}:
#         return "httpx", status, ctype, body, headers
#
#     status, ctype, body, headers = await citybus_browser_get(path_or_url)
#     return "browser", status, ctype, body, headers
#
#
# async def citybus_smart_post(path_or_url: str, payload=None) -> tuple[str, int, str, str, dict]:
#     status, ctype, body, headers = await citybus_httpx_post(path_or_url, payload)
#
#     if status not in {401, 403}:
#         return "httpx", status, ctype, body, headers
#
#     # Для arrival-board используем гарантированно рабочую цепочку fetch_arrival_board.
#     normalized = _normalize_path(path_or_url)
#
#     if "/arrival-board/stop/" in normalized:
#         stop_id = CITYBUS_STOP_ID
#
#         try:
#             stop_id = int(normalized.rstrip("/").split("/")[-1])
#         except Exception:
#             pass
#
#         rows = await fetch_arrival_board(stop_id)
#         body = json.dumps(rows, ensure_ascii=False)
#         return "fetch_arrival_board", 200, "application/json", body, {}
#
#     status, ctype, body, headers = await citybus_browser_post(path_or_url, payload)
#     return "browser", status, ctype, body, headers
#
#
# # ============================================================
# # COMMAND
# # ============================================================
#
# async def busdebug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """
#     /busdebug
#         Проверка основных endpoints, но arrival-board проверяется рабочей цепочкой.
#
#     /busdebug get /route/list
#         GET: сначала httpx, при 401/403 browser_context.
#
#     /busdebug rawget /route/list
#         Только httpx GET.
#
#     /busdebug browserget /route/list
#         Только browser_context GET.
#
#     /busdebug post /arrival-board/stop/2336782
#         POST: сначала httpx, при 401/403 рабочая цепочка/brower_context.
#
#     /busdebug arrival
#         Показывает полный ответ fetch_arrival_board для остановки.
#
#     /busdebug route 162891
#         Ищет routeId/id в /route/list.
#
#     /busdebug search 162891
#         Ищет строку по configuration/route/list/stop/list.
#
#     /busdebug stops 162891
#         Ищет поля, похожие на остановки/геометрию, внутри route object.
#     """
#     message = update.effective_message
#     args = context.args or []
#
#     try:
#         if not args:
#             await _busdebug_probe(message)
#             return
#
#         mode = safe_text(args[0]).strip().lower()
#
#         if mode == "get":
#             path = args[1] if len(args) >= 2 else "/route/list"
#             await _busdebug_get(message, path, smart=True)
#             return
#
#         if mode == "rawget":
#             path = args[1] if len(args) >= 2 else "/route/list"
#             await _busdebug_get(message, path, smart=False)
#             return
#
#         if mode == "browserget":
#             path = args[1] if len(args) >= 2 else "/route/list"
#             await _busdebug_browser_get(message, path)
#             return
#
#         if mode == "post":
#             path = args[1] if len(args) >= 2 else f"/arrival-board/stop/{CITYBUS_STOP_ID}"
#             await _busdebug_post(message, path)
#             return
#
#         if mode == "arrival":
#             stop_id = int(args[1]) if len(args) >= 2 else CITYBUS_STOP_ID
#             await _busdebug_arrival(message, stop_id)
#             return
#
#         if mode == "route":
#             route_id = int(args[1]) if len(args) >= 2 else CITYBUS_ROUTE_ID
#             await _busdebug_route(message, route_id)
#             return
#
#         if mode == "search":
#             if len(args) < 2:
#                 await message.reply_text("Формат: <code>/busdebug search 162891</code>", parse_mode=ParseMode.HTML)
#                 return
#
#             await _busdebug_search(message, args[1])
#             return
#
#         if mode == "stops":
#             route_id = int(args[1]) if len(args) >= 2 else CITYBUS_ROUTE_ID
#             await _busdebug_stops(message, route_id)
#             return
#
#         # Если первый аргумент похож на endpoint — считаем smart GET.
#         await _busdebug_get(message, args[0], smart=True)
#
#     except Exception as e:
#         await message.reply_text(
#             "🧪 <b>busdebug упал</b>\n\n"
#             f"<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>",
#             parse_mode=ParseMode.HTML,
#         )
#
#
# # ============================================================
# # SUBCOMMANDS
# # ============================================================
#
# async def _busdebug_probe(message):
#     endpoints = [
#         ("GET", "/configuration"),
#         ("GET", "/route/list"),
#         ("GET", "/stop/list"),
#         ("GET", "/position/stop/list"),
#         ("POST", f"/arrival-board/stop/{CITYBUS_STOP_ID}"),
#     ]
#
#     lines = ["🧪 <b>CityBus debug probe v2</b>", ""]
#
#     tokens = await _get_tokens()
#
#     lines.append(
#         "Токены: "
#         f"auth={'✅' if tokens.get('auth_token') else '❌'} "
#         f"visitor={'✅' if tokens.get('visitor_id') else '❌'}"
#     )
#     lines.append("")
#
#     for method, path in endpoints:
#         try:
#             if method == "GET":
#                 used, status, ctype, body, _headers = await citybus_smart_get(path)
#             else:
#                 used, status, ctype, body, _headers = await citybus_smart_post(path, [])
#
#             lines.append(
#                 f"<b>{method}</b> <code>{html.escape(path)}</code> via <code>{html.escape(used)}</code>\n"
#                 f"HTTP: <code>{status}</code>, size: <code>{len(body)}</code>, type: <code>{html.escape(ctype)}</code>"
#             )
#
#             preview = safe_text(body).strip().replace("\n", " ")[:220]
#             if preview:
#                 lines.append(f"<code>{html.escape(preview)}</code>")
#
#             lines.append("")
#
#         except Exception as e:
#             lines.append(
#                 f"<b>{method}</b> <code>{html.escape(path)}</code>\n"
#                 f"❌ <code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>\n"
#             )
#
#     await message.reply_text(
#         _clip("\n".join(lines)),
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_get(message, path: str, smart: bool):
#     if smart:
#         used, status, ctype, body, headers = await citybus_smart_get(path)
#     else:
#         status, ctype, body, headers = await citybus_httpx_get(path)
#         used = "httpx"
#
#     parsed = _loads_or_text(body)
#
#     text = (
#         f"🧪 <b>GET</b> <code>{html.escape(path)}</code> via <code>{html.escape(used)}</code>\n"
#         f"HTTP: <code>{status}</code>\n"
#         f"Type: <code>{html.escape(ctype)}</code>\n"
#         f"Size: <code>{len(body)}</code>\n\n"
#         f"{_html_pre(_json_pretty(parsed, 3400))}"
#     )
#
#     await message.reply_text(
#         text,
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_browser_get(message, path: str):
#     status, ctype, body, headers = await citybus_browser_get(path)
#     parsed = _loads_or_text(body)
#
#     text = (
#         f"🧪 <b>BROWSER GET</b> <code>{html.escape(path)}</code>\n"
#         f"HTTP: <code>{status}</code>\n"
#         f"Type: <code>{html.escape(ctype)}</code>\n"
#         f"Size: <code>{len(body)}</code>\n\n"
#         f"{_html_pre(_json_pretty(parsed, 3400))}"
#     )
#
#     await message.reply_text(
#         text,
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_post(message, path: str):
#     used, status, ctype, body, headers = await citybus_smart_post(path, [])
#     parsed = _loads_or_text(body)
#
#     text = (
#         f"🧪 <b>POST</b> <code>{html.escape(path)}</code> via <code>{html.escape(used)}</code>\n"
#         f"HTTP: <code>{status}</code>\n"
#         f"Type: <code>{html.escape(ctype)}</code>\n"
#         f"Size: <code>{len(body)}</code>\n\n"
#         f"{_html_pre(_json_pretty(parsed, 3400))}"
#     )
#
#     await message.reply_text(
#         text,
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_arrival(message, stop_id: int):
#     rows = await fetch_arrival_board(stop_id)
#
#     await message.reply_text(
#         f"🧪 <b>arrival-board stop {stop_id}</b> via <code>fetch_arrival_board</code>\n"
#         f"Rows: <code>{len(rows)}</code>\n\n"
#         f"{_html_pre(_json_pretty(rows, 3400))}",
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_route(message, route_id: int):
#     used, status, ctype, body, _headers = await citybus_smart_get("/route/list")
#     data = _loads_or_text(body)
#
#     if status != 200:
#         await message.reply_text(
#             f"🧪 /route/list via <code>{html.escape(used)}</code> вернул HTTP <code>{status}</code>\n\n"
#             f"{_html_pre(safe_text(body)[:3400])}",
#             parse_mode=ParseMode.HTML,
#         )
#         return
#
#     route = _find_route_in_obj(data, route_id)
#
#     if not route:
#         await message.reply_text(
#             f"Не нашёл routeId/id=<code>{route_id}</code> в <code>/route/list</code>.\n"
#             f"via: <code>{html.escape(used)}</code>\n"
#             f"Размер ответа: <code>{len(body)}</code>",
#             parse_mode=ParseMode.HTML,
#         )
#         return
#
#     await message.reply_text(
#         f"🧪 <b>route {route_id}</b> из <code>/route/list</code> via <code>{html.escape(used)}</code>\n\n"
#         f"{_html_pre(_json_pretty(route, 3500))}",
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_search(message, needle: str):
#     endpoints = [
#         "/configuration",
#         "/route/list",
#         "/stop/list",
#         "/position/stop/list",
#     ]
#
#     lines = [f"🧪 <b>Поиск</b> <code>{html.escape(needle)}</code>", ""]
#
#     for path in endpoints:
#         try:
#             used, status, ctype, body, _headers = await citybus_smart_get(path)
#
#             if status != 200:
#                 lines.append(
#                     f"<code>{html.escape(path)}</code> via <code>{html.escape(used)}</code>: "
#                     f"HTTP {status}, size {len(body)}"
#                 )
#                 continue
#
#             data = _loads_or_text(body)
#
#             if isinstance(data, str):
#                 count = data.count(needle)
#                 lines.append(
#                     f"<code>{html.escape(path)}</code> via <code>{html.escape(used)}</code>: "
#                     f"text hits={count}, size={len(body)}"
#                 )
#                 continue
#
#             hits = _find_occurrences(data, needle, max_hits=8)
#
#             lines.append(
#                 f"<code>{html.escape(path)}</code> via <code>{html.escape(used)}</code>: "
#                 f"hits={len(hits)}, size={len(body)}"
#             )
#
#             for hit in hits[:8]:
#                 lines.append(
#                     f"• <code>{html.escape(hit['path'])}</code>: "
#                     f"<code>{html.escape(hit['value'])}</code>"
#                 )
#
#             lines.append("")
#
#         except Exception as e:
#             lines.append(
#                 f"<code>{html.escape(path)}</code>: "
#                 f"❌ {html.escape(type(e).__name__)}: {html.escape(str(e))}"
#             )
#
#     await message.reply_text(
#         _clip("\n".join(lines)),
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
#
#
# async def _busdebug_stops(message, route_id: int):
#     used, status, ctype, body, _headers = await citybus_smart_get("/route/list")
#     data = _loads_or_text(body)
#
#     if status != 200:
#         await message.reply_text(
#             f"/route/list via <code>{html.escape(used)}</code> HTTP <code>{status}</code>\n\n"
#             f"{_html_pre(body[:3400])}",
#             parse_mode=ParseMode.HTML,
#         )
#         return
#
#     route = _find_route_in_obj(data, route_id)
#
#     if not route:
#         await message.reply_text(
#             f"Не нашёл routeId/id=<code>{route_id}</code> в /route/list via <code>{html.escape(used)}</code>.",
#             parse_mode=ParseMode.HTML,
#         )
#         return
#
#     interesting = _interesting_keys(route)
#
#     if not interesting:
#         await message.reply_text(
#             "В объекте route не нашёл очевидных полей типа stops/points/path/direction.\n\n"
#             f"Сам route:\n{_html_pre(_json_pretty(route, 3200))}",
#             parse_mode=ParseMode.HTML,
#             disable_web_page_preview=True,
#         )
#         return
#
#     await message.reply_text(
#         f"🧪 <b>Поля, похожие на остановки/путь для route {route_id}</b>\n"
#         f"via <code>{html.escape(used)}</code>\n\n"
#         f"{_html_pre(_json_pretty(interesting, 3400))}",
#         parse_mode=ParseMode.HTML,
#         disable_web_page_preview=True,
#     )
