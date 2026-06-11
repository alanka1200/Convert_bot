"""
main.py — Telegram бот-конвертер файлов.
"""

import os
import io
import json
import logging
import asyncio
import zipfile
import traceback
from datetime import date
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from utils import detect_file_type, get_possible_formats, get_output_filename, is_image_ext, needs_ilovepdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
TG_API      = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─── Хранилища в памяти ────────────────────────────────────────────────────────
state: dict[int, dict] = {}          # сессии конвертации
limits: dict[int, dict] = {}         # {chat_id: {"date": "2026-06-11", "count": 3}}
premium: dict[int, bool] = {}        # {chat_id: True} — платные пользователи

FREE_DAILY_LIMIT = 3                 # бесплатных конвертаций в день

# ─── Telegram Stars — цены (в Stars) ──────────────────────────────────────────
PRICE_MONTH    = 75   # подписка на месяц (≈ 150-200 руб)
PRICE_PACK_10  = 25   # пакет 10 конвертаций
PRICE_PACK_50  = 75   # пакет 50 конвертаций

# ─── Глобальный HTTP клиент ────────────────────────────────────────────────────
_http: httpx.AsyncClient | None = None

def get_http() -> httpx.AsyncClient:
    if _http is None:
        raise RuntimeError("HTTP client not initialized")
    return _http


# ─── Telegram helpers ──────────────────────────────────────────────────────────

async def tg(method: str, **kwargs) -> dict:
    url = f"{TG_API}/{method}"
    resp = await get_http().post(url, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        logger.error(f"TG [{method}]: {data}")
    return data

async def send(chat_id: int, text: str, kb=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if kb:
        p["reply_markup"] = json.dumps(kb)
    return await tg("sendMessage", json=p)

async def edit(chat_id: int, msg_id: int, text: str, kb=None):
    p = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if kb:
        p["reply_markup"] = json.dumps(kb)
    return await tg("editMessageText", json=p)

async def send_file(chat_id: int, data: bytes, filename: str, caption=""):
    files = {"document": (filename, io.BytesIO(data), "application/octet-stream")}
    form  = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if caption:
        form["caption"] = caption
    return await tg("sendDocument", files=files, data=form)

async def typing(chat_id: int, action="upload_document"):
    await tg("sendChatAction", json={"chat_id": chat_id, "action": action})

async def answer(cb_id: str, text=""):
    await tg("answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})

async def dl(file_id: str) -> bytes:
    r = await tg("getFile", json={"file_id": file_id})
    if not r.get("ok"):
        raise RuntimeError("Не удалось получить файл от Telegram")
    path = r["result"]["file_path"]
    url  = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    resp = await get_http().get(url)
    return resp.content

def sz(b: int) -> str:
    if b >= 1024 * 1024:
        return f"{b/1024/1024:.1f} МБ"
    if b >= 1024:
        return f"{b/1024:.0f} КБ"
    return f"{b} Б"


# ─── Лимиты и премиум ─────────────────────────────────────────────────────────

def is_premium(chat_id: int) -> bool:
    return premium.get(chat_id, False)

def get_today_count(chat_id: int) -> int:
    today = str(date.today())
    entry = limits.get(chat_id)
    if not entry or entry["date"] != today:
        return 0
    return entry["count"]

def increment_count(chat_id: int):
    today = str(date.today())
    entry = limits.get(chat_id)
    if not entry or entry["date"] != today:
        limits[chat_id] = {"date": today, "count": 1}
    else:
        limits[chat_id]["count"] += 1

def can_convert(chat_id: int) -> bool:
    if is_premium(chat_id):
        return True
    return get_today_count(chat_id) < FREE_DAILY_LIMIT

def remaining(chat_id: int) -> int:
    if is_premium(chat_id):
        return 999
    return max(0, FREE_DAILY_LIMIT - get_today_count(chat_id))


# ─── Telegram Stars оплата ────────────────────────────────────────────────────

async def send_invoice(chat_id: int, product: str):
    """Отправляет счёт через Telegram Stars."""
    products = {
        "month": {
            "title": "Премиум на месяц",
            "description": "Безлимитные конвертации на 30 дней. Без ограничений по форматам и размеру файлов.",
            "payload": "premium_month",
            "amount": PRICE_MONTH,
        },
        "pack10": {
            "title": "Пакет 10 конвертаций",
            "description": "10 дополнительных конвертаций. Не сгорают, используй когда нужно.",
            "payload": "pack_10",
            "amount": PRICE_PACK_10,
        },
        "pack50": {
            "title": "Пакет 50 конвертаций",
            "description": "50 дополнительных конвертаций. Лучшая цена за конвертацию.",
            "payload": "pack_50",
            "amount": PRICE_PACK_50,
        },
    }
    p = products.get(product)
    if not p:
        return

    await tg("sendInvoice", json={
        "chat_id": chat_id,
        "title": p["title"],
        "description": p["description"],
        "payload": p["payload"],
        "currency": "XTR",           # XTR = Telegram Stars
        "prices": [{"label": p["title"], "amount": p["amount"]}],
        "provider_token": "",         # пустой — для Stars не нужен
    })

async def handle_pre_checkout(pre_checkout_id: str):
    """Всегда подтверждаем — Stars не требуют верификации."""
    await tg("answerPreCheckoutQuery", json={
        "pre_checkout_query_id": pre_checkout_id,
        "ok": True,
    })

async def handle_successful_payment(chat_id: int, payload: str):
    """Начисляем бонусы после оплаты."""
    if payload == "premium_month":
        premium[chat_id] = True
        # Сбрасываем лимиты — они теперь не нужны
        limits.pop(chat_id, None)
        await send(chat_id,
            "🎉 <b>Премиум активирован!</b>\n\n"
            "Теперь у тебя безлимитные конвертации на 30 дней.\n"
            "Отправь файл — начнём!")

    elif payload == "pack_10":
        # Добавляем 10 конвертаций: уменьшаем счётчик сегодня
        entry = limits.get(chat_id, {"date": str(date.today()), "count": 0})
        entry["count"] = max(0, entry["count"] - 10)
        limits[chat_id] = entry
        await send(chat_id,
            "✅ <b>Пакет 10 конвертаций добавлен!</b>\n\n"
            f"Осталось сегодня: {remaining(chat_id) + 10} конвертаций.\n"
            "Отправь файл — начнём!")

    elif payload == "pack_50":
        entry = limits.get(chat_id, {"date": str(date.today()), "count": 0})
        entry["count"] = max(0, entry["count"] - 50)
        limits[chat_id] = entry
        await send(chat_id,
            "✅ <b>Пакет 50 конвертаций добавлен!</b>\n\n"
            "Надолго хватит — пользуйся!\n"
            "Отправь файл — начнём!")


# ─── Тексты ───────────────────────────────────────────────────────────────────

BOT_DESCRIPTION = (
    "Привет! 👋 Я бот-конвертер файлов.\n\n"
    "Помогаю конвертировать документы и изображения в нужный формат, "
    "сжимать файлы и создавать ZIP-архивы прямо в Telegram.\n\n"
    f"<b>Бесплатно:</b> {FREE_DAILY_LIMIT} конвертации в день\n"
    "<b>Премиум ⭐:</b> безлимит за Telegram Stars\n\n"
    "<b>Просто отправь мне файл</b> — я сам разберусь что с ним можно сделать 👇"
)

HELP_TEXT = (
    "❓ <b>Как пользоваться ботом</b>\n\n"
    "<b>Конвертация файлов:</b>\n"
    "1. Отправь файл в чат\n"
    "2. Бот покажет доступные варианты\n"
    "3. Нажми на нужный формат\n"
    "4. Получи готовый файл прямо здесь\n\n"
    "<b>Создание ZIP-архива:</b>\n"
    "1. Нажми 📦 Создать архив или напиши /zip\n"
    "2. Отправляй файлы по одному\n"
    "3. Напиши /done — получишь ZIP\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/premium — купить премиум\n"
    "/status — мой статус и лимиты\n"
    "/help — эта справка\n"
    "/formats — все форматы\n"
    "/zip — создать ZIP-архив\n\n"
    "⚠️ Максимальный размер файла: 50 МБ"
)

FORMATS_TEXT = (
    "📋 <b>Поддерживаемые форматы</b>\n\n"
    "📄 <b>PDF</b> → Word, PNG, TXT, сжатие\n"
    "📝 <b>Word (DOCX/DOC)</b> → PDF, TXT\n"
    "📊 <b>Excel (XLSX/XLS)</b> → PDF, CSV, TXT\n"
    "📑 <b>PowerPoint (PPTX/PPT)</b> → PDF, PNG\n"
    "🖼 <b>Изображения (PNG/JPG/BMP)</b> → PDF, другой формат, сжатие\n"
    "🔤 <b>TXT / CSV</b> → PDF\n"
    "📦 <b>ZIP-архив</b> — любые файлы → команда /zip"
)

PREMIUM_TEXT = (
    "⭐ <b>Премиум — безлимитные конвертации</b>\n\n"
    f"Бесплатно доступно {FREE_DAILY_LIMIT} конвертации в день.\n"
    "С премиумом — без ограничений.\n\n"
    "<b>Выбери вариант:</b>"
)

def limit_reached_text(chat_id: int) -> str:
    return (
        f"⛔ <b>Лимит исчерпан</b>\n\n"
        f"Сегодня ты использовал все {FREE_DAILY_LIMIT} бесплатные конвертации.\n\n"
        "Можешь:\n"
        "• подождать до завтра (лимит сбросится)\n"
        "• купить пакет или премиум прямо сейчас ⭐"
    )


# ─── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    limits_obj = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30)
    _http = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=120, write=60, pool=5),
        limits=limits_obj,
    )
    logger.info("HTTP client created")
    if BOT_TOKEN and WEBHOOK_URL:
        try:
            r = await tg("setWebhook", json={"url": WEBHOOK_URL})
            logger.info(f"Webhook set: {r.get('description', r)}")
        except Exception as e:
            logger.error(f"Webhook error: {e}")
    yield
    await _http.aclose()
    logger.info("HTTP client closed")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "bot": bool(BOT_TOKEN)}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
        asyncio.create_task(handle_update(update))
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
    return {"ok": True}


# ─── Главный диспетчер ────────────────────────────────────────────────────────

async def handle_update(update: dict):
    try:
        # ── Callback кнопки ──
        if "callback_query" in update:
            await on_callback(update["callback_query"])
            return

        # ── Подтверждение оплаты (до списания) ──
        if "pre_checkout_query" in update:
            await handle_pre_checkout(update["pre_checkout_query"]["id"])
            return

        msg = update.get("message", {})
        if not msg:
            return

        chat_id  = msg.get("chat", {}).get("id")
        if not chat_id:
            return

        # ── Успешная оплата ──
        if "successful_payment" in msg:
            payload = msg["successful_payment"]["invoice_payload"]
            await handle_successful_payment(chat_id, payload)
            return

        text     = msg.get("text", "")
        document = msg.get("document")
        photo    = msg.get("photo")
        st       = state.get(chat_id, {})

        # ── Мусорные типы сообщений ──
        if not text and not document and not photo:
            unsupported = (
                msg.get("sticker") or msg.get("voice") or msg.get("video") or
                msg.get("video_note") or msg.get("audio") or msg.get("contact") or
                msg.get("location") or msg.get("venue") or msg.get("animation") or
                msg.get("poll")
            )
            if unsupported:
                await send(chat_id,
                    "📁 Я работаю только с файлами и изображениями.\n\n"
                    "Отправь документ, PDF, картинку или архив — и я помогу с конвертацией!")
                return

        # ── Режим сбора ZIP ──
        if st.get("mode") == "zip_collect":
            if text == "/done":
                await finish_zip(chat_id)
            elif text == "/cancel":
                state.pop(chat_id, None)
                await send(chat_id, "❌ Создание архива отменено.")
            elif document or photo:
                f = document if document else _photo_as_doc(photo)
                await collect_zip_file(chat_id, f)
            else:
                await send(chat_id,
                    "📦 Отправляй файлы для архива или напиши /done\nОтмена: /cancel")
            return

        # ── Команды ──
        if text.startswith("/start"):
            await cmd_start(chat_id, msg.get("from", {}))
        elif text.startswith("/premium"):
            await cmd_premium(chat_id)
        elif text.startswith("/status"):
            await cmd_status(chat_id)
        elif text.startswith("/help"):
            await send(chat_id, HELP_TEXT)
        elif text.startswith("/formats"):
            await send(chat_id, FORMATS_TEXT)
        elif text.startswith("/zip"):
            await cmd_zip(chat_id)
        elif text.startswith("/done") or text.startswith("/cancel"):
            await send(chat_id, "Нет активной операции. Отправь файл или нажми /start")
        elif document:
            await on_file(chat_id, document)
        elif photo:
            await on_file(chat_id, _photo_as_doc(photo))
        elif text and not text.startswith("/"):
            await send(chat_id,
                "📁 Отправь мне файл — и я помогу с ним!\n\n"
                "/help — как пользоваться\n/premium — купить безлимит")
        elif text.startswith("/"):
            await send(chat_id, "Не знаю такую команду 🤷\n/start — главное меню")

    except Exception as e:
        logger.error(f"handle_update error: {e}\n{traceback.format_exc()}")


def _photo_as_doc(photo: list) -> dict:
    best = photo[-1]
    return {"file_id": best["file_id"], "file_name": "photo.jpg",
            "mime_type": "image/jpeg", "file_size": best.get("file_size", 0)}


# ─── Команды ──────────────────────────────────────────────────────────────────

async def cmd_start(chat_id: int, user: dict):
    name = user.get("first_name", "")
    greet = f"{'Привет, ' + name + '! 👋' if name else 'Привет! 👋'}\n\n"
    kb = {"inline_keyboard": [
        [{"text": "📋 Все форматы", "callback_data": "formats"},
         {"text": "❓ Помощь",      "callback_data": "help"}],
        [{"text": "⭐ Купить премиум", "callback_data": "premium"}],
        [{"text": "📦 Создать ZIP-архив", "callback_data": "zip"}],
    ]}
    await send(chat_id, greet + BOT_DESCRIPTION, kb)


async def cmd_premium(chat_id: int):
    if is_premium(chat_id):
        await send(chat_id,
            "✅ <b>У тебя уже есть премиум!</b>\n\n"
            "Пользуйся безлимитными конвертациями. Отправь файл — начнём!")
        return

    kb = {"inline_keyboard": [
        [{"text": f"⭐ Пакет 10 конвертаций — {PRICE_PACK_10} Stars",
          "callback_data": "buy_pack10"}],
        [{"text": f"⭐ Пакет 50 конвертаций — {PRICE_PACK_50} Stars",
          "callback_data": "buy_pack50"}],
        [{"text": f"🚀 Премиум на месяц — {PRICE_MONTH} Stars",
          "callback_data": "buy_month"}],
    ]}
    await send(chat_id, PREMIUM_TEXT, kb)


async def cmd_status(chat_id: int):
    if is_premium(chat_id):
        text = (
            "📊 <b>Твой статус</b>\n\n"
            "✅ Премиум активен\n"
            "Конвертаций: безлимит"
        )
    else:
        used  = get_today_count(chat_id)
        left  = remaining(chat_id)
        text = (
            "📊 <b>Твой статус</b>\n\n"
            f"Бесплатный план\n"
            f"Использовано сегодня: {used} из {FREE_DAILY_LIMIT}\n"
            f"Осталось: {left}\n\n"
            "Нужно больше? /premium"
        )
    await send(chat_id, text)


# ─── ZIP ──────────────────────────────────────────────────────────────────────

async def cmd_zip(chat_id: int):
    state[chat_id] = {"mode": "zip_collect", "files": []}
    await send(chat_id,
        "📦 <b>Создание ZIP-архива</b>\n\n"
        "Отправляй файлы по одному.\n"
        "Когда готово — напиши /done\n\nОтмена: /cancel")


async def collect_zip_file(chat_id: int, doc: dict):
    files = state.get(chat_id, {}).get("files", [])
    fname = doc.get("file_name", "file")
    fid   = doc.get("file_id", "")
    fsize = doc.get("file_size", 0)
    files.append({"file_id": fid, "file_name": fname, "file_size": fsize})
    state[chat_id]["files"] = files
    await send(chat_id,
        f"✅ Добавлен: <b>{fname}</b> ({sz(fsize)})\n"
        f"Файлов: <b>{len(files)}</b>\n\nДобавляй ещё или напиши /done")


async def finish_zip(chat_id: int):
    files = state.get(chat_id, {}).get("files", [])
    if not files:
        await send(chat_id, "⚠️ Ты не добавил ни одного файла.")
        return
    await send(chat_id, f"⚙️ Скачиваю и упаковываю {len(files)} файлов... ⏳")
    await typing(chat_id)
    try:
        downloaded = await asyncio.gather(*[dl(f["file_id"]) for f in files])
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            seen: dict[str, int] = {}
            for f, data in zip(files, downloaded):
                name = f["file_name"]
                if name in seen:
                    seen[name] += 1
                    base, ext = os.path.splitext(name)
                    name = f"{base}_{seen[name]}{ext}"
                else:
                    seen[name] = 0
                zf.writestr(name, data)
        zip_bytes = zip_buf.getvalue()
        await send_file(chat_id, zip_bytes, "archive.zip",
            f"✅ ZIP готов!\n📂 Файлов: {len(files)}\n📦 Размер: {sz(len(zip_bytes))}")
        state.pop(chat_id, None)
        await send(chat_id, "Отправь новый файл если понадоблюсь 😊")
    except Exception as e:
        logger.error(f"ZIP error: {e}\n{traceback.format_exc()}")
        await send(chat_id, f"❌ Ошибка при создании архива:\n<code>{str(e)[:300]}</code>")


# ─── Обработка файла ──────────────────────────────────────────────────────────

async def on_file(chat_id: int, doc: dict):
    fname  = doc.get("file_name", "file")
    fid    = doc.get("file_id", "")
    mime   = doc.get("mime_type", "")
    fsize  = doc.get("file_size", 0)

    if fsize > 50 * 1024 * 1024:
        await send(chat_id, f"❌ Файл слишком большой ({sz(fsize)}).\nМаксимум — 50 МБ.")
        return

    ftype   = detect_file_type(fname, mime)
    formats = get_possible_formats(ftype) if ftype else []

    state[chat_id] = {
        "mode": "convert", "file_id": fid,
        "file_name": fname, "file_ext": ftype or "", "file_size": fsize,
    }

    ext_label = fname.rsplit(".", 1)[-1].upper() if "." in fname else "?"
    size_str  = f"  ·  {sz(fsize)}" if fsize else ""

    if not ftype or not formats:
        kb = {"inline_keyboard": [
            [{"text": "📦 Добавить в ZIP", "callback_data": "zip"}],
            [{"text": "❌ Отмена",         "callback_data": "cancel"}],
        ]}
        await send(chat_id,
            f"📁 <b>{fname}</b>{size_str}\n\n"
            f"Формат <b>.{ext_label}</b> не поддерживается для конвертации.\n"
            "Но могу добавить в ZIP-архив 📦", kb)
        return

    buttons = [[{"text": f"{f['icon']}  {f['label']}", "callback_data": f"conv:{f['id']}"}]
               for f in formats]
    buttons.append([{"text": "📦 Добавить в ZIP", "callback_data": "zip"}])
    buttons.append([{"text": "❌ Отмена", "callback_data": "cancel"}])

    await send(chat_id,
        f"📁 <b>{fname}</b>{size_str}\n\nВот что я могу сделать с этим файлом 👇",
        {"inline_keyboard": buttons})


# ─── Callback ─────────────────────────────────────────────────────────────────

async def on_callback(cb: dict):
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    data    = cb.get("data", "")
    cb_id   = cb["id"]
    await answer(cb_id)

    if data == "cancel":
        state.pop(chat_id, None)
        await edit(chat_id, msg_id, "❌ Отменено. Отправь новый файл когда будешь готов.")

    elif data == "help":
        await send(chat_id, HELP_TEXT)

    elif data == "formats":
        await send(chat_id, FORMATS_TEXT)

    elif data == "premium":
        await cmd_premium(chat_id)

    elif data == "buy_month":
        await send_invoice(chat_id, "month")

    elif data == "buy_pack10":
        await send_invoice(chat_id, "pack10")

    elif data == "buy_pack50":
        await send_invoice(chat_id, "pack50")

    elif data == "zip":
        st = state.get(chat_id, {})
        if st.get("file_id"):
            state[chat_id] = {
                "mode": "zip_collect",
                "files": [{"file_id": st["file_id"], "file_name": st["file_name"],
                            "file_size": st.get("file_size", 0)}]
            }
            await edit(chat_id, msg_id,
                f"📦 Файл <b>{st['file_name']}</b> добавлен в архив.\n\n"
                "Отправляй ещё или напиши /done\nОтмена: /cancel")
        else:
            await cmd_zip(chat_id)

    elif data.startswith("conv:"):
        target = data.split(":", 1)[1]
        await do_convert(chat_id, msg_id, target)


# ─── Конвертация ──────────────────────────────────────────────────────────────

LABEL = {
    "docx": "Word (DOCX)", "txt": "TXT", "png": "PNG",
    "jpg": "JPG", "pdf": "PDF", "compress": "сжатый файл", "csv": "CSV",
}


async def do_convert(chat_id: int, msg_id: int, target: str):
    info = state.get(chat_id)
    if not info or info.get("mode") != "convert" or not info.get("file_id"):
        await send(chat_id, "⚠️ Сессия устарела. Отправь файл заново.")
        return

    # ── Проверка лимитов ──────────────────────────────────────────────────────
    if not can_convert(chat_id):
        kb = {"inline_keyboard": [
            [{"text": f"⭐ Пакет 10 конвертаций — {PRICE_PACK_10} Stars",
              "callback_data": "buy_pack10"}],
            [{"text": f"🚀 Безлимит на месяц — {PRICE_MONTH} Stars",
              "callback_data": "buy_month"}],
        ]}
        await edit(chat_id, msg_id, limit_reached_text(chat_id), kb)
        return

    label    = LABEL.get(target, target.upper())
    file_ext = info["file_ext"]

    await edit(chat_id, msg_id,
        f"⚙️ Конвертирую в <b>{label}</b>...\n\nЭто может занять до 30 секунд ⏳")
    await typing(chat_id)

    try:
        raw = await dl(info["file_id"])

        if target == "pdf" and needs_ilovepdf(file_ext):
            from ilovepdf import office_to_pdf, is_ilovepdf_available
            if not is_ilovepdf_available():
                await send(chat_id,
                    "⚠️ Конвертация Office → PDF временно недоступна.\n"
                    "Попробуй позже или используй другой формат.")
                return
            result = await office_to_pdf(raw, info["file_name"])
            mime   = "application/pdf"
        else:
            from converter import convert
            result, mime = convert(raw, file_ext, target)

        # ── Засчитываем конвертацию ───────────────────────────────────────────
        increment_count(chat_id)
        left = remaining(chat_id)

        out   = get_output_filename(info["file_name"], target)
        lines = [
            f"✅ <b>{file_ext.upper()} → {label}</b>",
            f"📦 Размер: {sz(len(result))}",
        ]
        if target == "compress":
            saved = (1 - len(result) / len(raw)) * 100
            lines.append(f"💾 Сжато на {saved:.1f}%" if saved > 0 else "ℹ️ Файл уже хорошо сжат")

        # Показываем остаток лимита (только бесплатным)
        if not is_premium(chat_id):
            if left == 0:
                lines.append(f"\n⚠️ Это была последняя бесплатная конвертация на сегодня.")
            elif left == 1:
                lines.append(f"\nℹ️ Осталась {left} бесплатная конвертация на сегодня.")
            else:
                lines.append(f"\nℹ️ Осталось {left} бесплатных конвертации на сегодня.")

        await send_file(chat_id, result, out, "\n".join(lines))
        state.pop(chat_id, None)

        # Если лимит исчерпан — сразу предлагаем купить
        if not is_premium(chat_id) and left == 0:
            kb = {"inline_keyboard": [
                [{"text": f"⭐ Ещё 10 конвертаций — {PRICE_PACK_10} Stars",
                  "callback_data": "buy_pack10"}],
                [{"text": f"🚀 Безлимит на месяц — {PRICE_MONTH} Stars",
                  "callback_data": "buy_month"}],
            ]}
            await send(chat_id,
                "⛔ <b>Лимит исчерпан</b> — завтра сбросится автоматически.\n\n"
                "Или купи пакет прямо сейчас 👇", kb)
        else:
            await send(chat_id, "Готово! Отправь ещё файл если нужно 📁")

    except Exception as e:
        logger.error(f"Convert error: {e}\n{traceback.format_exc()}")
        await send(chat_id,
            f"❌ Ошибка конвертации:\n<code>{str(e)[:300]}</code>\n\n"
            "Попробуй снова или отправь другой файл.")
