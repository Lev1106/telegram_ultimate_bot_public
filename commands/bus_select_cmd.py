# import asyncio
# import os
# import json
# import html
# import time
# import math
# import secrets
# from pathlib import Path
# from typing import Any
#
# import httpx
# from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.constants import ParseMode
# from telegram.ext import ContextTypes
# from telegram.error import BadRequest
#
# from commands.bus_cmd import (
#     CITYBUS_API_BASE,
#     CITYBUS_ROUTE_ID,
#     CITYBUS_STOP_ID,
#     build_headers,
#     load_tokens,
#     safe_text,
# )
#
# try:
#     from commands.bus_cmd import open_citybus_context
# except Exception:
#     open_citybus_context = None
#
#
# ROUTES_PER_PAGE = int(os.getenv("CITYBUS_ROUTES_PER_PAGE", "10"))
# STOPS_PER_PAGE = int(os.getenv("CITYBUS_STOPS_PER_PAGE", "10"))
#
# MEM_CACHE_TTL_SECONDS = int(os.getenv("CITYBUS_MEM_CACHE_TTL_SECONDS", "1800"))
# DISK_CACHE_TTL_SECONDS = int(os.getenv("CITYBUS_DISK_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))
#
# CITYBUS_ROUTES_CACHE_FILE = Path(os.getenv("CITYBUS_ROUTES_CACHE_FILE", "citybus_routes_cache.json"))
# CITYBUS_STOPS_CACHE_FILE = Path(os.getenv("CITYBUS_STOPS_CACHE_FILE", "citybus_stops_cache.json"))
#
# # Чтобы не засрать консоль километрами CityBus-логов.
# BUSPICK_DEBUG = os.getenv("BUSPICK_DEBUG", "0").strip() in {"1", "true", "True", "yes"}
#
# _cache: dict[str, Any] = {
#     "routes": None,
#     "stops": None,
#     "routes_at": 0.0,
#     "stops_at": 0.0,
# }
#
# _filter_sessions: dict[str, dict[str, Any]] = {}
#
#
# # ============================================================
# # LOG / UTILS
# # ============================================================
#
# def _log(*args):
#     if BUSPICK_DEBUG:
#         print("[BUSPICK]", *args)
#
#
# def _clip(text: str, limit: int = 3900) -> str:
#     text = safe_text(text)
#
#     if len(text) <= limit:
#         return text
#
#     return text[: limit - 100] + "\n\n...<обрезано, Telegram не автобусный парк>"
#
#
# def _normalize_path(path: str) -> str:
#     path = safe_text(path).strip()
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
# def _api_path_from_url(url: str) -> str:
#     url = safe_text(url)
#
#     prefix = CITYBUS_API_BASE
#
#     if url.startswith(prefix):
#         path = url[len(prefix):]
#     else:
#         path = url
#
#     if "?" in path:
#         path = path.split("?", 1)[0]
#
#     return path
#
#
# def _get_nested_ru(obj: Any, fallback: str = "") -> str:
#     if isinstance(obj, dict):
#         value = obj.get("ru") or obj.get("ru_RU") or obj.get("en") or obj.get("kk")
#         if value:
#             return safe_text(value)
#
#     if obj:
#         return safe_text(obj)
#
#     return fallback
#
#
# def _route_name(route: dict) -> str:
#     name = _get_nested_ru(route.get("name"), "")
#     if name:
#         return name
#
#     return str(route.get("id") or route.get("routeId") or "?")
#
#
# def _route_id(route: dict) -> int | None:
#     for key in ("id", "routeId", "route_id"):
#         try:
#             return int(route.get(key))
#         except Exception:
#             pass
#
#     return None
#
#
# def _route_type_id(route: dict) -> int | None:
#     for key in ("typeId", "type_id", "transportTypeId"):
#         try:
#             return int(route.get(key))
#         except Exception:
#             pass
#
#     return None
#
#
# def _route_type_icon(route: dict) -> str:
#     """
#     По логам CityBus в route/list есть typeId.
#     Точные названия лучше потом подтвердить на паре известных маршрутов,
#     но для UI уже полезнее, чем два одинаковых "1".
#     """
#     type_id = _route_type_id(route)
#
#     mapping = {
#         0: "🚌",  # автобус
#         1: "🚎",  # троллейбус
#         2: "🚋",  # трамвай/другой рельсовый, если внезапно есть
#     }
#
#     return mapping.get(type_id, f"🚍{type_id}" if type_id is not None else "🚍")
#
#
# def _route_type_text(route: dict) -> str:
#     type_id = _route_type_id(route)
#
#     mapping = {
#         0: "автобус",
#         1: "троллейбус",
#         2: "трамвай",
#     }
#
#     return mapping.get(type_id, f"typeId={type_id}" if type_id is not None else "тип неизвестен")
#
#
# def _sort_route_key(route: dict):
#     name = _route_name(route).strip()
#
#     if name.isdigit():
#         return (0, int(name), name)
#
#     return (1, name.casefold(), name)
#
#
# def _extract_stop_id(stop_item: Any) -> int | None:
#     if isinstance(stop_item, int):
#         return stop_item
#
#     if isinstance(stop_item, dict):
#         for key in ("stopId", "stop_id", "id"):
#             try:
#                 return int(stop_item.get(key))
#             except Exception:
#                 pass
#
#     return None
#
#
# def _stop_name(stop_obj: dict | None, stop_id: int | None = None) -> str:
#     if stop_obj:
#         name = _get_nested_ru(stop_obj.get("name"), "")
#         if name:
#             return name
#
#     if stop_id is not None:
#         return f"Остановка {stop_id}"
#
#     return "Остановка ?"
#
#
# def _make_session(query: str = "") -> str:
#     query = safe_text(query).strip()
#     sid = secrets.token_hex(3)
#
#     _filter_sessions[sid] = {
#         "query": query,
#         "created_at": time.time(),
#     }
#
#     now = time.time()
#
#     for old_sid in list(_filter_sessions.keys()):
#         if now - float(_filter_sessions[old_sid].get("created_at", 0)) > 3600:
#             _filter_sessions.pop(old_sid, None)
#
#     return sid
#
#
# def _get_session_query(sid: str) -> str:
#     if sid == "all":
#         return ""
#
#     return safe_text(_filter_sessions.get(sid, {}).get("query", ""))
#
#
# def _filter_routes(routes: list[dict], query: str) -> list[dict]:
#     query = safe_text(query).strip().casefold()
#
#     if not query:
#         return routes
#
#     out = []
#
#     for r in routes:
#         rid = _route_id(r)
#         name = _route_name(r)
#
#         hay = f"{rid} {name}".casefold()
#
#         if query in hay:
#             out.append(r)
#
#     return out
#
#
# def _route_label(route: dict) -> str:
#     rid = _route_id(route)
#     name = _route_name(route)
#     icon = _route_type_icon(route)
#
#     if rid is None:
#         return f"{icon} {name[:40]}"
#
#     if str(rid) == name:
#         return f"{icon} {name}"
#
#     return f"{icon} {name} · {rid}"
#
#
# # ============================================================
# # DISK CACHE
# # ============================================================
#
# def _cache_payload(data: Any) -> dict:
#     return {
#         "saved_at": time.time(),
#         "data": data,
#     }
#
#
# def _save_disk_cache(path: Path, data: Any) -> None:
#     try:
#         path.write_text(
#             json.dumps(_cache_payload(data), ensure_ascii=False),
#             encoding="utf-8",
#         )
#         _log("saved disk cache:", path)
#     except Exception as e:
#         _log(f"failed to save disk cache {path}: {e!r}")
#
#
# def _load_disk_cache(path: Path, allow_stale: bool = True) -> Any | None:
#     if not path.exists():
#         return None
#
#     try:
#         obj = json.loads(path.read_text(encoding="utf-8"))
#
#         if isinstance(obj, dict) and "data" in obj:
#             saved_at = float(obj.get("saved_at", 0) or 0)
#             age = time.time() - saved_at
#
#             if allow_stale or age <= DISK_CACHE_TTL_SECONDS:
#                 _log(f"loaded disk cache: {path}, age={int(age)}s")
#                 return obj.get("data")
#
#             return None
#
#         if isinstance(obj, list):
#             _log(f"loaded old disk cache list: {path}")
#             return obj
#
#     except Exception as e:
#         _log(f"failed to load disk cache {path}: {e!r}")
#
#     return None
#
#
# def _save_known_dataset(path: str, data: Any) -> None:
#     if path == "/route/list" and isinstance(data, list):
#         routes = [x for x in data if isinstance(x, dict)]
#         routes.sort(key=_sort_route_key)
#
#         _cache["routes"] = routes
#         _cache["routes_at"] = time.time()
#         _save_disk_cache(CITYBUS_ROUTES_CACHE_FILE, routes)
#
#     elif path == "/stop/list" and isinstance(data, list):
#         stops = [x for x in data if isinstance(x, dict)]
#
#         _cache["stops"] = stops
#         _cache["stops_at"] = time.time()
#         _save_disk_cache(CITYBUS_STOPS_CACHE_FILE, stops)
#
#
# # ============================================================
# # CITYBUS DATA FETCHING
# # ============================================================
#
# async def _httpx_get_json(path: str) -> Any:
#     tokens = load_tokens()
#     url = _normalize_path(path)
#
#     async with httpx.AsyncClient(timeout=35.0) as client:
#         response = await client.get(
#             url,
#             headers=build_headers(tokens),
#         )
#
#     response.raise_for_status()
#     return response.json()
#
#
# async def _open_citybus_context_compat():
#     """
#     В разных версиях bus_cmd open_citybus_context был то без аргументов,
#     то с tokens. Поддерживаем оба варианта.
#     """
#     if open_citybus_context is None:
#         raise RuntimeError("open_citybus_context не импортировался из commands.bus_cmd")
#
#     try:
#         return await open_citybus_context()
#     except TypeError:
#         return await open_citybus_context(load_tokens())
#
#
# async def _browser_capture_json(wanted_path: str, timeout_seconds: float = 12.0) -> Any:
#     """
#     Ключевой фикс.
#
#     Старый вариант открывал сайт, видел в логах 200 на /route/list,
#     а потом делал ОТДЕЛЬНЫЙ browser_context.request.get('/route/list'),
#     и именно этот отдельный запрос ловил 401.
#
#     Теперь мы не делаем второй запрос.
#     Мы открываем сайт и забираем JSON прямо из реального response,
#     который фронт CityBus сам успешно получил.
#     """
#     wanted_path = wanted_path.split("?", 1)[0]
#
#     p = None
#     browser_context = None
#
#     captured: dict[str, Any] = {}
#     done = asyncio.Event()
#
#     async def on_response(response):
#         try:
#             url = response.url or ""
#
#             if "cdu-rest-api.tha.kz" not in url:
#                 return
#
#             path = _api_path_from_url(url)
#
#             if path not in {"/route/list", "/stop/list", wanted_path}:
#                 return
#
#             if response.status != 200:
#                 _log(f"frontend response {response.status}: {path}")
#                 return
#
#             text = await response.text()
#             data = json.loads(text)
#
#             captured[path] = data
#             _save_known_dataset(path, data)
#
#             _log(f"captured frontend 200: {path}, size={len(text)}")
#
#             if path == wanted_path:
#                 done.set()
#
#         except Exception as e:
#             _log("capture response error:", repr(e))
#
#     try:
#         p, browser_context = await _open_citybus_context_compat()
#         page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
#
#         page.on("response", lambda response: asyncio.create_task(on_response(response)))
#
#         try:
#             await page.goto("https://citybus.tha.kz/", wait_until="domcontentloaded", timeout=30000)
#         except Exception as e:
#             _log("page goto failed:", repr(e))
#
#         try:
#             await asyncio.wait_for(done.wait(), timeout=timeout_seconds)
#         except asyncio.TimeoutError:
#             pass
#
#         if wanted_path in captured:
#             return captured[wanted_path]
#
#         # Иногда нужный ответ приходит чуть позже и успевает попасть в captured,
#         # но Event не отработал из-за гонки.
#         await page.wait_for_timeout(1500)
#
#         if wanted_path in captured:
#             return captured[wanted_path]
#
#         have = ", ".join(sorted(captured.keys())) or "nothing"
#         raise RuntimeError(f"Не поймал frontend response 200 для {wanted_path}; поймал: {have}")
#
#     finally:
#         if browser_context:
#             await browser_context.close()
#         if p:
#             await p.stop()
#
#
# async def _citybus_get_json(path: str) -> Any:
#     """
#     Сначала пробуем дешёвый httpx.
#     Если CityBus опять даёт 401/403 — забираем JSON из реального frontend-response.
#     """
#     try:
#         data = await _httpx_get_json(path)
#         _save_known_dataset(path, data)
#         return data
#
#     except httpx.HTTPStatusError as e:
#         if e.response.status_code not in {401, 403}:
#             raise
#
#         _log(f"httpx GET {path} got {e.response.status_code}, using frontend capture")
#
#     data = await _browser_capture_json(path)
#     _save_known_dataset(path, data)
#     return data
#
#
# async def _frontend_arrival_board(stop_id: int, stop_obj: dict | None = None) -> list[dict]:
#     """
#     Пробует получить arrival-board тремя путями:
#
#     1. Берём точные headers из реального frontend-response /route/list или /stop/list
#        и делаем POST через httpx.
#     2. Теми же headers пробуем browser_context.request.post.
#     3. Если оба получили 401 — открываем карту, центрируемся на stop.point,
#        кликаем по маркеру остановки и ловим НАСТОЯЩИЙ frontend-response
#        /arrival-board/stop/{stop_id}.
#
#     Третий путь нужен потому, что CityBus, судя по всему, генерит X-Auth-Token
#     отдельно под конкретный POST arrival-board, а не принимает токен от route/list.
#     """
#     if open_citybus_context is None:
#         raise RuntimeError("open_citybus_context не импортировался из commands.bus_cmd")
#
#     async def capture_headers_from_frontend() -> tuple[dict[str, str], Any, Any]:
#         p = None
#         browser_context = None
#
#         captured_headers: dict[str, str] = {}
#         got_headers = asyncio.Event()
#
#         def prepare_arrival_headers(headers: dict) -> dict:
#             out = {}
#
#             for k, v in (headers or {}).items():
#                 key = safe_text(k)
#                 val = safe_text(v)
#
#                 if not key:
#                     continue
#
#                 lk = key.lower()
#
#                 if lk in {
#                     "host",
#                     "content-length",
#                     "connection",
#                     "accept-encoding",
#                 }:
#                     continue
#
#                 out[key] = val
#
#             out["Accept"] = "application/json, text/plain, */*"
#             out["Content-Type"] = "application/json;charset=utf-8"
#             out["Origin"] = "https://citybus.tha.kz"
#             out["Referer"] = "https://citybus.tha.kz/"
#
#             return out
#
#         async def on_response(response):
#             try:
#                 url = response.url or ""
#
#                 if "cdu-rest-api.tha.kz" not in url:
#                     return
#
#                 if response.status != 200:
#                     return
#
#                 path = _api_path_from_url(url)
#
#                 if path not in {"/route/list", "/stop/list"}:
#                     return
#
#                 req_headers = response.request.headers or {}
#
#                 auth = req_headers.get("x-auth-token") or req_headers.get("X-Auth-Token")
#                 visitor = req_headers.get("x-visitor-id") or req_headers.get("X-Visitor-Id")
#
#                 if not (auth and visitor):
#                     return
#
#                 captured_headers.clear()
#                 captured_headers.update(prepare_arrival_headers(req_headers))
#                 got_headers.set()
#
#             except Exception as e:
#                 _log("arrival header capture failed:", repr(e))
#
#         p, browser_context = await _open_citybus_context_compat()
#         page = await browser_context.new_page()
#         page.on("response", lambda response: asyncio.create_task(on_response(response)))
#
#         try:
#             await page.goto("https://citybus.tha.kz/", wait_until="domcontentloaded", timeout=30000)
#         except Exception as e:
#             _log("arrival page goto failed:", repr(e))
#
#         try:
#             await asyncio.wait_for(got_headers.wait(), timeout=12.0)
#         except asyncio.TimeoutError:
#             pass
#
#         if not (
#             captured_headers.get("x-auth-token")
#             or captured_headers.get("X-Auth-Token")
#         ):
#             if browser_context:
#                 await browser_context.close()
#             if p:
#                 await p.stop()
#             raise RuntimeError("Не поймал X-Auth-Token из frontend-response")
#
#         if not (
#             captured_headers.get("x-visitor-id")
#             or captured_headers.get("X-Visitor-Id")
#         ):
#             if browser_context:
#                 await browser_context.close()
#             if p:
#                 await p.stop()
#             raise RuntimeError("Не поймал X-Visitor-Id из frontend-response")
#
#         return captured_headers, p, browser_context
#
#     url = f"{CITYBUS_API_BASE}/arrival-board/stop/{stop_id}"
#
#     headers = None
#     p = None
#     browser_context = None
#     first_error = None
#
#     try:
#         headers, p, browser_context = await capture_headers_from_frontend()
#
#         async with httpx.AsyncClient(timeout=25.0) as client:
#             response = await client.post(
#                 url,
#                 headers=headers,
#                 content="[]",
#             )
#
#         if response.status_code == 200:
#             data = response.json()
#
#             if not isinstance(data, list):
#                 raise RuntimeError(f"arrival-board вернул не список, а {type(data).__name__}: {data!r}")
#
#             return data
#
#         first_error = f"httpx={response.status_code}"
#
#         browser_response = await browser_context.request.post(
#             url,
#             headers=headers,
#             data="[]",
#         )
#
#         body = await browser_response.text()
#
#         if browser_response.status == 200:
#             data = json.loads(body)
#
#             if not isinstance(data, list):
#                 raise RuntimeError(f"arrival-board вернул не список, а {type(data).__name__}: {data!r}")
#
#             return data
#
#         first_error += f", browser_context={browser_response.status}"
#
#     finally:
#         if browser_context:
#             await browser_context.close()
#         if p:
#             await p.stop()
#
#     # Последний, самый похожий на реального юзера путь: кликнуть маркер остановки.
#     clicked = await _arrival_board_by_clicking_stop(stop_id, stop_obj)
#
#     if clicked is not None:
#         return clicked
#
#     raise httpx.HTTPStatusError(
#         f"Arrival-board failed: {first_error}; click-fallback=no-response",
#         request=httpx.Request("POST", url),
#         response=httpx.Response(
#             status_code=401,
#             text="",
#             request=httpx.Request("POST", url),
#         ),
#     )
#
#
# async def _arrival_board_by_clicking_stop(stop_id: int, stop_obj: dict | None) -> list[dict] | None:
#     """
#     Открывает карту CityBus, центрируется на координатах остановки и пытается
#     заставить сам фронт сделать /arrival-board/stop/{stop_id}.
#
#     v8 показал maps=1, markers=0.
#     Значит карта Leaflet есть, но остановки рисуются не через L.Marker/L.CircleMarker,
#     а, скорее всего, как generic layer / SVG path / canvas-ish слой.
#
#     Поэтому тут патчим шире:
#     - L.Map.addLayer
#     - L.LayerGroup.addLayer
#     - L.FeatureGroup.addLayer
#     - L.Marker/CircleMarker/Circle/Polyline/Polygon
#     И если Leaflet-layer всё равно не поймали — делаем DOM click через
#     document.elementFromPoint(...) прямо из page.evaluate, без Playwright mouse.click.
#     """
#     if not stop_obj:
#         return None
#
#     point = stop_obj.get("point")
#
#     if not (
#         isinstance(point, list)
#         and len(point) >= 2
#         and isinstance(point[0], (int, float))
#         and isinstance(point[1], (int, float))
#     ):
#         return None
#
#     lat = float(point[0])
#     lon = float(point[1])
#
#     p = None
#     browser_context = None
#
#     result: dict[str, Any] = {}
#     got_arrival = asyncio.Event()
#
#     init_script = """
#     (() => {
#         window.__citybus_maps = window.__citybus_maps || [];
#         window.__citybus_layers = window.__citybus_layers || [];
#
#         function rememberLayer(layer) {
#             try {
#                 if (!layer) return;
#
#                 const useful =
#                     (layer.getLatLng && typeof layer.getLatLng === "function") ||
#                     (layer.getBounds && typeof layer.getBounds === "function") ||
#                     layer._latlng ||
#                     layer._latlngs ||
#                     layer._icon ||
#                     layer._path;
#
#                 if (!useful) return;
#
#                 if (!window.__citybus_layers.includes(layer)) {
#                     window.__citybus_layers.push(layer);
#                 }
#             } catch (e) {}
#         }
#
#         function rememberMap(map) {
#             try {
#                 if (!map) return;
#                 if (!window.__citybus_maps.includes(map)) {
#                     window.__citybus_maps.push(map);
#                 }
#
#                 if (map.eachLayer) {
#                     map.eachLayer(layer => rememberLayer(layer));
#                 }
#             } catch (e) {}
#         }
#
#         function patchMethod(proto, name, wrapperFactory) {
#             try {
#                 if (!proto || !proto[name] || proto[name].__citybus_patched) return;
#                 const old = proto[name];
#                 const wrapped = wrapperFactory(old);
#                 wrapped.__citybus_patched = true;
#                 proto[name] = wrapped;
#             } catch (e) {}
#         }
#
#         function patchLeaflet(L) {
#             try {
#                 if (!L || L.__citybus_wide_patched) return;
#                 L.__citybus_wide_patched = true;
#
#                 if (L.Map && L.Map.prototype) {
#                     patchMethod(L.Map.prototype, "initialize", old => function(...args) {
#                         old.apply(this, args);
#                         rememberMap(this);
#                     });
#
#                     patchMethod(L.Map.prototype, "addLayer", old => function(layer) {
#                         const r = old.apply(this, arguments);
#                         rememberMap(this);
#                         rememberLayer(layer);
#                         return r;
#                     });
#                 }
#
#                 const groupTypes = [L.LayerGroup, L.FeatureGroup, L.GeoJSON];
#
#                 for (const T of groupTypes) {
#                     if (T && T.prototype) {
#                         patchMethod(T.prototype, "addLayer", old => function(layer) {
#                             const r = old.apply(this, arguments);
#                             rememberLayer(layer);
#                             return r;
#                         });
#                     }
#                 }
#
#                 const layerTypes = [L.Marker, L.CircleMarker, L.Circle, L.Polyline, L.Polygon];
#
#                 for (const T of layerTypes) {
#                     if (T && T.prototype) {
#                         patchMethod(T.prototype, "initialize", old => function(...args) {
#                             old.apply(this, args);
#                             rememberLayer(this);
#                         });
#
#                         patchMethod(T.prototype, "onAdd", old => function(...args) {
#                             const r = old.apply(this, args);
#                             rememberLayer(this);
#                             return r;
#                         });
#                     }
#                 }
#
#                 try {
#                     if (L.map && !L.map.__citybus_patched) {
#                         const oldMapFactory = L.map;
#                         const wrappedMapFactory = function(...args) {
#                             const map = oldMapFactory.apply(this, args);
#                             rememberMap(map);
#                             return map;
#                         };
#                         wrappedMapFactory.__citybus_patched = true;
#                         L.map = wrappedMapFactory;
#                     }
#                 } catch (e) {}
#             } catch (e) {}
#         }
#
#         let currentL = window.L;
#
#         try {
#             Object.defineProperty(window, "L", {
#                 configurable: true,
#                 get() {
#                     return currentL;
#                 },
#                 set(v) {
#                     currentL = v;
#                     patchLeaflet(v);
#                 }
#             });
#         } catch (e) {}
#
#         try { patchLeaflet(currentL); } catch (e) {}
#
#         setInterval(() => {
#             try {
#                 patchLeaflet(window.L);
#
#                 for (const map of (window.__citybus_maps || [])) {
#                     rememberMap(map);
#                 }
#             } catch (e) {}
#         }, 100);
#     })();
#     """
#
#     async def on_response(response):
#         try:
#             url = response.url or ""
#
#             if f"/arrival-board/stop/{stop_id}" not in url:
#                 return
#
#             status = response.status
#             body = await response.text()
#
#             if status != 200:
#                 _log(f"click/js arrival response {status}: {body[:200]}")
#                 return
#
#             data = json.loads(body)
#
#             if isinstance(data, list):
#                 result["data"] = data
#                 got_arrival.set()
#
#         except Exception as e:
#             _log("click/js arrival capture failed:", repr(e))
#
#     try:
#         p, browser_context = await _open_citybus_context_compat()
#
#         try:
#             await browser_context.add_init_script(script=init_script)
#         except Exception as e:
#             _log("add_init_script failed:", repr(e))
#
#         page = await browser_context.new_page()
#         page.on("response", lambda response: asyncio.create_task(on_response(response)))
#
#         try:
#             await page.goto("https://citybus.tha.kz/", wait_until="domcontentloaded", timeout=30000)
#         except Exception as e:
#             _log("click page goto failed:", repr(e))
#
#         await page.wait_for_timeout(7000)
#
#         center_info = await page.evaluate(
#             """
#             ({ lat, lon }) => {
#                 const maps = window.__citybus_maps || [];
#                 const map = maps.find(m => m && m.setView && m.getContainer);
#
#                 if (!map) {
#                     return {
#                         ok: false,
#                         reason: "no-leaflet-map",
#                         maps: maps.length,
#                         layers: (window.__citybus_layers || []).length
#                     };
#                 }
#
#                 map.setView([lat, lon], 18, { animate: false });
#
#                 try {
#                     map.eachLayer(layer => {
#                         if (!window.__citybus_layers.includes(layer)) {
#                             window.__citybus_layers.push(layer);
#                         }
#                     });
#                 } catch (e) {}
#
#                 return {
#                     ok: true,
#                     maps: maps.length,
#                     layers: (window.__citybus_layers || []).length
#                 };
#             }
#             """,
#             {"lat": lat, "lon": lon},
#         )
#
#         _log("leaflet center:", center_info)
#
#         await page.wait_for_timeout(3000)
#
#         fire_info = await page.evaluate(
#             """
#             ({ lat, lon }) => {
#                 function dist(a, b, c, d) {
#                     const dx = a - c;
#                     const dy = b - d;
#                     return Math.sqrt(dx * dx + dy * dy);
#                 }
#
#                 function layerLatLng(layer) {
#                     try {
#                         if (layer.getLatLng) {
#                             const ll = layer.getLatLng();
#                             return { lat: Number(ll.lat), lon: Number(ll.lng) };
#                         }
#
#                         if (layer._latlng) {
#                             return { lat: Number(layer._latlng.lat), lon: Number(layer._latlng.lng) };
#                         }
#
#                         if (layer.getBounds) {
#                             const c = layer.getBounds().getCenter();
#                             return { lat: Number(c.lat), lon: Number(c.lng) };
#                         }
#                     } catch (e) {}
#
#                     return null;
#                 }
#
#                 const maps = window.__citybus_maps || [];
#                 const map = maps.find(m => m && m.latLngToContainerPoint && m.getContainer);
#                 const layers = (window.__citybus_layers || [])
#                     .filter(layer => layer && (layer.getLatLng || layer._latlng || layer.getBounds || layer._icon || layer._path));
#
#                 let best = null;
#
#                 for (const layer of layers) {
#                     const ll = layerLatLng(layer);
#                     if (!ll) continue;
#
#                     const d = dist(ll.lat, ll.lon, lat, lon);
#
#                     if (!best || d < best.d) {
#                         best = { layer, d, lat: ll.lat, lon: ll.lon };
#                     }
#                 }
#
#                 const clicked = [];
#                 const errors = [];
#
#                 if (best && best.d < 0.002) {
#                     try {
#                         if (best.layer.fire) {
#                             best.layer.fire("click");
#                             clicked.push("layer.fire(click)");
#                         }
#                     } catch (e) {
#                         errors.push("layer.fire: " + String(e));
#                     }
#
#                     try {
#                         if (best.layer.fire) {
#                             best.layer.fire("mousedown");
#                             best.layer.fire("mouseup");
#                             best.layer.fire("click");
#                             clicked.push("layer.fire(mouse)");
#                         }
#                     } catch (e) {
#                         errors.push("layer.fire mouse: " + String(e));
#                     }
#
#                     try {
#                         const el = best.layer._icon || best.layer._path;
#                         if (el) {
#                             el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
#                             el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
#                             el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
#                             clicked.push(best.layer._icon ? "dom-icon-click" : "dom-path-click");
#                         }
#                     } catch (e) {
#                         errors.push("dom layer click: " + String(e));
#                     }
#                 }
#
#                 // Fallback без layer: DOM elementFromPoint вокруг координаты.
#                 let domClicks = [];
#
#                 try {
#                     if (map) {
#                         const container = map.getContainer();
#                         const rect = container.getBoundingClientRect();
#                         const p = map.latLngToContainerPoint([lat, lon]);
#
#                         const baseX = rect.left + p.x;
#                         const baseY = rect.top + p.y;
#
#                         const offsets = [
#                             [0, 0], [0, -12], [0, -24], [0, 12],
#                             [12, 0], [-12, 0], [12, -12], [-12, -12],
#                             [18, -18], [-18, -18], [18, 6], [-18, 6],
#                         ];
#
#                         for (const [dx, dy] of offsets) {
#                             const x = baseX + dx;
#                             const y = baseY + dy;
#                             const el = document.elementFromPoint(x, y);
#
#                             if (!el) continue;
#
#                             const desc = [
#                                 el.tagName,
#                                 el.className && String(el.className).slice(0, 80),
#                                 el.getAttribute && el.getAttribute("src"),
#                                 el.getAttribute && el.getAttribute("alt"),
#                                 el.getAttribute && el.getAttribute("title"),
#                             ].filter(Boolean).join("|");
#
#                             domClicks.push(desc);
#
#                             el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y }));
#                             el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y }));
#                             el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y }));
#
#                             clicked.push("elementFromPoint");
#                         }
#                     }
#                 } catch (e) {
#                     errors.push("elementFromPoint: " + String(e));
#                 }
#
#                 return {
#                     ok: true,
#                     maps: maps.length,
#                     layers: layers.length,
#                     nearestDistance: best ? best.d : null,
#                     nearestLat: best ? best.lat : null,
#                     nearestLon: best ? best.lon : null,
#                     clicked,
#                     domClicks: domClicks.slice(0, 8),
#                     errors: errors.slice(0, 5)
#                 };
#             }
#             """,
#             {"lat": lat, "lon": lon},
#         )
#
#         _log("leaflet layer/dom fire:", fire_info)
#
#         try:
#             await asyncio.wait_for(got_arrival.wait(), timeout=10.0)
#         except asyncio.TimeoutError:
#             pass
#
#         if "data" in result:
#             return result["data"]
#
#         return None
#
#     except Exception as e:
#         _log("arrival by layer/dom fire failed:", repr(e))
#         return None
#
#     finally:
#         if browser_context:
#             await browser_context.close()
#         if p:
#             await p.stop()
#
#
# async def get_routes(force: bool = False) -> list[dict]:
#     now = time.time()
#
#     if (
#         not force
#         and isinstance(_cache.get("routes"), list)
#         and now - float(_cache.get("routes_at", 0)) < MEM_CACHE_TTL_SECONDS
#     ):
#         return _cache["routes"]
#
#     if not force:
#         disk = _load_disk_cache(CITYBUS_ROUTES_CACHE_FILE, allow_stale=True)
#         if isinstance(disk, list):
#             routes = [x for x in disk if isinstance(x, dict)]
#             routes.sort(key=_sort_route_key)
#
#             _cache["routes"] = routes
#             _cache["routes_at"] = now
#
#             return routes
#
#     try:
#         data = await _citybus_get_json("/route/list")
#     except Exception as e:
#         disk = _load_disk_cache(CITYBUS_ROUTES_CACHE_FILE, allow_stale=True)
#         if isinstance(disk, list):
#             _log(f"route/list failed, using stale disk cache: {e!r}")
#
#             routes = [x for x in disk if isinstance(x, dict)]
#             routes.sort(key=_sort_route_key)
#
#             _cache["routes"] = routes
#             _cache["routes_at"] = now
#
#             return routes
#
#         raise
#
#     if not isinstance(data, list):
#         raise RuntimeError(f"/route/list вернул не список, а {type(data).__name__}")
#
#     routes = [x for x in data if isinstance(x, dict)]
#     routes.sort(key=_sort_route_key)
#
#     _cache["routes"] = routes
#     _cache["routes_at"] = now
#     _save_disk_cache(CITYBUS_ROUTES_CACHE_FILE, routes)
#
#     return routes
#
#
# async def get_stops(force: bool = False) -> list[dict]:
#     now = time.time()
#
#     if (
#         not force
#         and isinstance(_cache.get("stops"), list)
#         and now - float(_cache.get("stops_at", 0)) < MEM_CACHE_TTL_SECONDS
#     ):
#         return _cache["stops"]
#
#     if not force:
#         disk = _load_disk_cache(CITYBUS_STOPS_CACHE_FILE, allow_stale=True)
#         if isinstance(disk, list):
#             stops = [x for x in disk if isinstance(x, dict)]
#
#             _cache["stops"] = stops
#             _cache["stops_at"] = now
#
#             return stops
#
#     try:
#         data = await _citybus_get_json("/stop/list")
#     except Exception as e:
#         disk = _load_disk_cache(CITYBUS_STOPS_CACHE_FILE, allow_stale=True)
#         if isinstance(disk, list):
#             _log(f"stop/list failed, using stale disk cache: {e!r}")
#
#             stops = [x for x in disk if isinstance(x, dict)]
#
#             _cache["stops"] = stops
#             _cache["stops_at"] = now
#
#             return stops
#
#         raise
#
#     if not isinstance(data, list):
#         raise RuntimeError(f"/stop/list вернул не список, а {type(data).__name__}")
#
#     stops = [x for x in data if isinstance(x, dict)]
#
#     _cache["stops"] = stops
#     _cache["stops_at"] = now
#     _save_disk_cache(CITYBUS_STOPS_CACHE_FILE, stops)
#
#     return stops
#
#
# async def get_route_map() -> dict[int, dict]:
#     routes = await get_routes()
#     out = {}
#
#     for r in routes:
#         rid = _route_id(r)
#         if rid is not None:
#             out[rid] = r
#
#     return out
#
#
# async def get_stop_map() -> dict[int, dict]:
#     stops = await get_stops()
#     out = {}
#
#     for s in stops:
#         try:
#             sid = int(s.get("id"))
#             out[sid] = s
#         except Exception:
#             pass
#
#     return out
#
#
# # ============================================================
# # RENDERERS
# # ============================================================
#
# async def render_route_page(sid: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
#     routes = await get_routes()
#     query = _get_session_query(sid)
#     filtered = _filter_routes(routes, query)
#
#     pages = max(1, math.ceil(len(filtered) / ROUTES_PER_PAGE))
#     page = max(0, min(page, pages - 1))
#
#     start = page * ROUTES_PER_PAGE
#     chunk = filtered[start: start + ROUTES_PER_PAGE]
#
#     title = "🚌 <b>Выбери маршрут</b>"
#
#     if query:
#         title += f"\nФильтр: <code>{html.escape(query)}</code>"
#
#     text = (
#         f"{title}\n\n"
#         f"Маршрутов: <code>{len(filtered)}</code>\n"
#         f"Страница: <code>{page + 1}/{pages}</code>"
#     )
#
#     rows = []
#
#     for route in chunk:
#         rid = _route_id(route)
#
#         if rid is None:
#             continue
#
#         rows.append([
#             InlineKeyboardButton(
#                 _route_label(route)[:60],
#                 callback_data=f"bus:route:{sid}:{rid}",
#             )
#         ])
#
#     nav = []
#
#     if page > 0:
#         nav.append(InlineKeyboardButton("⬅️", callback_data=f"bus:rpage:{sid}:{page - 1}"))
#
#     nav.append(InlineKeyboardButton("🔄", callback_data=f"bus:rpage:{sid}:{page}"))
#
#     if page + 1 < pages:
#         nav.append(InlineKeyboardButton("➡️", callback_data=f"bus:rpage:{sid}:{page + 1}"))
#
#     if nav:
#         rows.append(nav)
#
#     rows.append([
#         InlineKeyboardButton("🧹 Сбросить фильтр", callback_data="bus:rpage:all:0"),
#     ])
#
#     return text, InlineKeyboardMarkup(rows)
#
#
# async def render_direction_page(route_id: int, sid: str = "all") -> tuple[str, InlineKeyboardMarkup]:
#     route_map = await get_route_map()
#     stop_map = await get_stop_map()
#
#     route = route_map.get(route_id)
#
#     if not route:
#         raise RuntimeError(f"Не нашёл маршрут {route_id} в /route/list")
#
#     directions = route.get("directions") or []
#
#     if not directions:
#         raise RuntimeError(f"У маршрута {route_id} нет directions")
#
#     text = (
#         f"🚌 <b>Маршрут {_route_label(route)}</b>\n"
#         f"Тип: <b>{html.escape(_route_type_text(route))}</b>\n\n"
#         "Выбери направление:"
#     )
#
#     rows = []
#
#     for idx, direction in enumerate(directions):
#         stops = direction.get("stops") or []
#
#         stop_ids = [_extract_stop_id(x) for x in stops]
#         stop_ids = [x for x in stop_ids if x is not None]
#
#         if stop_ids:
#             first_name = _stop_name(stop_map.get(stop_ids[0]), stop_ids[0])
#             last_name = _stop_name(stop_map.get(stop_ids[-1]), stop_ids[-1])
#             label = f"{idx + 1}. {first_name} → {last_name}"
#         else:
#             label = f"{idx + 1}. Направление {idx + 1}"
#
#         rows.append([
#             InlineKeyboardButton(
#                 label[:60],
#                 callback_data=f"bus:spage:{route_id}:{idx}:0",
#             )
#         ])
#
#     rows.append([
#         InlineKeyboardButton("⬅️ К маршрутам", callback_data=f"bus:rpage:{sid}:0"),
#     ])
#
#     return text, InlineKeyboardMarkup(rows)
#
#
# async def render_stop_page(route_id: int, direction_idx: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
#     route_map = await get_route_map()
#     stop_map = await get_stop_map()
#
#     route = route_map.get(route_id)
#
#     if not route:
#         raise RuntimeError(f"Не нашёл маршрут {route_id} в /route/list")
#
#     directions = route.get("directions") or []
#
#     if direction_idx < 0 or direction_idx >= len(directions):
#         raise RuntimeError(f"У маршрута нет направления index={direction_idx}")
#
#     direction = directions[direction_idx]
#     raw_stops = direction.get("stops") or []
#
#     stop_ids = [_extract_stop_id(x) for x in raw_stops]
#     stop_ids = [x for x in stop_ids if x is not None]
#
#     pages = max(1, math.ceil(len(stop_ids) / STOPS_PER_PAGE))
#     page = max(0, min(page, pages - 1))
#
#     start = page * STOPS_PER_PAGE
#     chunk = stop_ids[start: start + STOPS_PER_PAGE]
#
#     text = (
#         f"🚌 <b>Маршрут {_route_label(route)}</b>\n"
#         f"Тип: <b>{html.escape(_route_type_text(route))}</b>\n"
#         f"Направление: <code>{direction_idx + 1}</code>\n\n"
#         "Выбери остановку:\n"
#         f"Страница: <code>{page + 1}/{pages}</code>"
#     )
#
#     rows = []
#
#     for absolute_idx, stop_id in enumerate(chunk, start=start + 1):
#         stop = stop_map.get(stop_id)
#         name = _stop_name(stop, stop_id)
#
#         rows.append([
#             InlineKeyboardButton(
#                 f"{absolute_idx}. {name}"[:60],
#                 callback_data=f"bus:stop:{route_id}:{direction_idx}:{stop_id}",
#             )
#         ])
#
#     nav = []
#
#     if page > 0:
#         nav.append(InlineKeyboardButton("⬅️", callback_data=f"bus:spage:{route_id}:{direction_idx}:{page - 1}"))
#
#     nav.append(InlineKeyboardButton("🔄", callback_data=f"bus:spage:{route_id}:{direction_idx}:{page}"))
#
#     if page + 1 < pages:
#         nav.append(InlineKeyboardButton("➡️", callback_data=f"bus:spage:{route_id}:{direction_idx}:{page + 1}"))
#
#     if nav:
#         rows.append(nav)
#
#     rows.append([
#         InlineKeyboardButton("⬅️ К направлениям", callback_data=f"bus:route:all:{route_id}"),
#     ])
#
#     return text, InlineKeyboardMarkup(rows)
#
#
# async def render_arrival(route_id: int, direction_idx: int, stop_id: int) -> tuple[str, InlineKeyboardMarkup]:
#     route_map = await get_route_map()
#     stop_map = await get_stop_map()
#
#     route = route_map.get(route_id)
#     stop = stop_map.get(stop_id)
#
#     arrival_error = None
#
#     try:
#         rows = await _frontend_arrival_board(stop_id, stop)
#     except Exception as e:
#         rows = []
#         arrival_error = e
#
#     found = None
#
#     for row in rows:
#         try:
#             if int(row.get("routeId")) == route_id:
#                 found = row
#                 break
#         except Exception:
#             pass
#
#     route_label = _route_label(route) if route else str(route_id)
#     stop_label = _stop_name(stop, stop_id)
#
#     if found:
#         data = found.get("data") or {}
#         ru = safe_text(data.get("ru") or "").strip()
#
#         if not ru:
#             minutes = found.get("time")
#             distance = found.get("distance")
#
#             parts = []
#
#             if isinstance(minutes, (int, float)):
#                 parts.append(f"~{round(minutes)} мин")
#
#             if isinstance(distance, (int, float)):
#                 if distance >= 1000:
#                     parts.append(f"~{distance / 1000:.1f} км")
#                 else:
#                     parts.append(f"~{round(distance)} м")
#
#             ru = ", ".join(parts) if parts else "нет данных"
#
#         text = (
#             "🚌 <b>Прибытие</b>\n\n"
#             f"Маршрут: <b>{html.escape(route_label)}</b>\n"
#             f"Тип: <b>{html.escape(_route_type_text(route) if route else 'тип неизвестен')}</b>\n"
#             f"Остановка: <b>{html.escape(stop_label)}</b>\n"
#             f"Прибытие: <b>{html.escape(ru)}</b>"
#         )
#     else:
#         available = []
#
#         for row in rows:
#             try:
#                 available.append(str(row.get("routeId")))
#             except Exception:
#                 pass
#
#         if arrival_error is not None:
#             text = (
#                 "🚌 <b>Не смог получить табло этой остановки</b>\n\n"
#                 f"Маршрут: <b>{html.escape(route_label)}</b>\n"
#                 f"Тип: <b>{html.escape(_route_type_text(route) if route else 'тип неизвестен')}</b>\n"
#                 f"Остановка: <b>{html.escape(stop_label)}</b>\n"
#                 f"Stop ID: <code>{stop_id}</code>\n\n"
#                 "CityBus вернул 401 даже с headers из frontend-response. "
#                 "Это значит, что arrival-board токен у них, похоже, генерится отдельно под конкретный POST, "
#                 "а не переиспользуется от route/list/stop/list.\n\n"
#                 f"<code>{html.escape(type(arrival_error).__name__)}: {html.escape(str(arrival_error))[:700]}</code>"
#             )
#         else:
#             text = (
#                 "🚌 <b>Сейчас этого маршрута на табло нет</b>\n\n"
#                 f"Маршрут: <b>{html.escape(route_label)}</b>\n"
#                 f"Тип: <b>{html.escape(_route_type_text(route) if route else 'тип неизвестен')}</b>\n"
#                 f"Остановка: <b>{html.escape(stop_label)}</b>\n\n"
#                 f"На табло сейчас: <code>{html.escape(', '.join(available[:25]))}</code>"
#             )
#
#     keyboard = InlineKeyboardMarkup([
#         [
#             InlineKeyboardButton("🔄 Обновить", callback_data=f"bus:stop:{route_id}:{direction_idx}:{stop_id}"),
#         ],
#         [
#             InlineKeyboardButton("⬅️ К остановкам", callback_data=f"bus:spage:{route_id}:{direction_idx}:0"),
#         ],
#         [
#             InlineKeyboardButton("⬅️ К маршрутам", callback_data="bus:rpage:all:0"),
#         ],
#     ])
#
#     return text, keyboard
#
#
#
# async def _safe_edit(query, text: str, keyboard: InlineKeyboardMarkup | None = None):
#     try:
#         await query.edit_message_text(
#             text,
#             parse_mode=ParseMode.HTML,
#             reply_markup=keyboard,
#             disable_web_page_preview=True,
#         )
#     except BadRequest as e:
#         # Telegram ругается, если ты пытаешься поставить тот же текст/кнопки.
#         if "Message is not modified" in str(e):
#             return
#         raise
#
# # ============================================================
# # COMMANDS
# # ============================================================
#
# async def buspick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """
#     /buspick
#     /buspick 236
#     /buspick 162891
#     """
#     message = update.effective_message
#
#     try:
#         query = " ".join(context.args or []).strip()
#         sid = "all" if not query else _make_session(query)
#
#         text, keyboard = await render_route_page(sid, 0)
#
#         await message.reply_text(
#             text,
#             parse_mode=ParseMode.HTML,
#             reply_markup=keyboard,
#             disable_web_page_preview=True,
#         )
#
#     except Exception as e:
#         await message.reply_text(
#             "🚌 <b>buspick упал</b>\n\n"
#             f"<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>",
#             parse_mode=ParseMode.HTML,
#         )
#
#
# async def bus_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#
#     if not query:
#         return
#
#     await query.answer()
#
#     data = safe_text(query.data)
#     parts = data.split(":")
#
#     try:
#         if len(parts) < 2 or parts[0] != "bus":
#             return
#
#         action = parts[1]
#
#         if action == "rpage":
#             sid = parts[2]
#             page = int(parts[3])
#
#             text, keyboard = await render_route_page(sid, page)
#
#             await _safe_edit(query, text, keyboard)
#             return
#
#         if action == "route":
#             sid = parts[2]
#             route_id = int(parts[3])
#
#             text, keyboard = await render_direction_page(route_id, sid)
#
#             await _safe_edit(query, text, keyboard)
#             return
#
#         if action == "spage":
#             route_id = int(parts[2])
#             direction_idx = int(parts[3])
#             page = int(parts[4])
#
#             text, keyboard = await render_stop_page(route_id, direction_idx, page)
#
#             await _safe_edit(query, text, keyboard)
#             return
#
#         if action == "stop":
#             route_id = int(parts[2])
#             direction_idx = int(parts[3])
#             stop_id = int(parts[4])
#
#             text, keyboard = await render_arrival(route_id, direction_idx, stop_id)
#
#             await _safe_edit(query, text, keyboard)
#             return
#
#     except Exception as e:
#         await _safe_edit(
#             query,
#             "🚌 <b>buspick упал</b>\n\n"
#             f"<code>{html.escape(type(e).__name__)}: {html.escape(str(e))}</code>",
#             None,
#         )
