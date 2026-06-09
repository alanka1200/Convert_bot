"""
main.py — Telegram бот для конвертации файлов.
Чистый бот без WebApp. Пользователь шлёт файл → бот предлагает форматы → конвертирует → присылает результат.
"""

import os
import io
import json
import random
import logging
import asyncio
import traceback
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from utils import detect_file_type, get_possible_formats, get_output_filename, is_image_ext
from converter import convert, merge_pdfs, merge_images_to_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Хранилище состояний: chat_id → dict
pending: dict[int, dict] = {}

GREETINGS = [
    "Привет! 👋",
    "Здарова! 🤙",
    "Привет-привет! 😊",
]


# ─── Telegram helpers ──────────────────────────────────────────────────────────

async def tg(method: str, **kwargs) -> dict:
    url = f"{TELEGRAM_API}/{method}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        logger.error(f"TG [{method}] error: {data}")
    return data


async def send_msg(chat_id: int, text: str, keyboard=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)
    return await tg("sendMessage", json=payload)


async def edit_msg(chat_id: int, message_id: int, text: str, keyboard=None):
    payload = {"chat_id": chat_id, "message_id": message_id,
                "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard)
    return await tg("editMessageText", json=payload)


async def send_doc(chat_id: int, data: bytes, filename: str, caption=""):
    files = {"document": (filename, io.BytesIO(data), "application/octet-stream")}
    form = {"chat_id": str(chat_id)}
    if caption:
        form["caption"] = caption
        form["parse_mode"] = "HTML"
    return await tg("sendDocument", files=files, data=form)


async def send_action(chat_id: int, action="upload_document"):
    await tg("sendChatAction", json={"chat_id": chat_id, "action": action})


async def answer_cb(cb_id: str, text=""):
    await tg("answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})


async def download(file_id: str) -> bytes:
    r = await tg("getFile", json={"file_id": file_id})
    if not r.get("ok"):
        raise RuntimeError("Не удалось получить файл")
    path = r["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
    return resp.content


def sz(b: int) -> str:
    if b > 1024 * 1024:
        return f"{b/1024/1024:.1f} МБ"
    return f"{b/1024:.0f} КБ"


# ─── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if BOT_TOKEN and WEBHOOK_URL:
        try:
            r = await tg("setWebhook", json={"url": WEBHOOK_URL})
            logger.info(f"Webhook: {r}")
        except Exception as e:
            logger.error(f"Webhook error: {e}")
    yield


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
        logger.error(f"Webhook error: {e}")
    return {"ok": True}


# ─── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(chat_id: int, user: dict):
    name = user.get("first_name", "")
    hi = random.choice(GREETINGS)
    text = (
        f"{hi}{' ' + name + '!' if name else ''}\n\n"
        "Я конвертирую файлы прямо в Telegram — быстро и бесплатно.\n\n"
        "<b>Что умею:</b>\n"
        "📄 PDF → Word, PNG, TXT, сжатие\n"
        "🖼 PNG/JPG/BMP → PDF, другой формат, сжатие\n"
        "📝 Word (DOCX) → TXT\n"
        "🔤 TXT → PDF\n"
        "📎 Объединить PDF или фото в один PDF\n\n"
        "<b>Как пользоваться:</b> просто отправь файл 👇"
    )
    kb = {"inline_keyboard": [
        [{"text": "📋 Все форматы", "callback_data": "formats"}],
        [{"text": "📎 Объединить файлы", "callback_data": "start_merge"}],
    ]}
    await send_msg(chat_id, text, kb)


async def cmd_help(chat_id: int):
    text = (
        "❓ <b>Помощь</b>\n\n"
        "<b>Конвертация:</b>\n"
        "1. Отправь файл в чат\n"
        "2. Выбери формат из кнопок\n"
        "3. Получи готовый файл\n\n"
        "<b>Объединение файлов:</b>\n"
        "1. Напиши /merge\n"
        "2. Отправляй файлы по одному\n"
        "3. Напиши /done когда закончишь\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/formats — все форматы\n"
        "/merge — объединить файлы\n\n"
        "<b>Ограничения:</b>\n"
        "• Макс. размер файла: 50 МБ\n"
        "• DOCX → PDF не поддерживается\n"
        "• PDF → DOCX может терять сложную вёрстку"
    )
    await send_msg(chat_id, text)


async def cmd_formats(chat_id: int):
    text = (
        "📋 <b>Поддерживаемые форматы</b>\n\n"
        "📄 <b>PDF</b>\n"
        "  → Word (DOCX), PNG, TXT, сжатие\n\n"
        "🖼 <b>PNG / JPG / JPEG / BMP</b>\n"
        "  → PDF, другой формат, сжатие\n\n"
        "📝 <b>DOCX (Word)</b>\n"
        "  → TXT\n\n"
        "🔤 <b>TXT</b>\n"
        "  → PDF\n\n"
        "📎 <b>Объединение</b> (/merge)\n"
        "  Несколько PDF или фото → один PDF"
    )
    await send_msg(chat_id, text)


# ─── File handler ──────────────────────────────────────────────────────────────

async def handle_file(chat_id: int, doc: dict):
    file_id   = doc.get("file_id", "")
    file_name = doc.get("file_name", "file")
    mime      = doc.get("mime_type", "")
    size      = doc.get("file_size", 0)

    if size > 50 * 1024 * 1024:
        await send_msg(chat_id,
            f"❌ Файл слишком большой ({sz(size)}).\n"
            "Максимальный размер — 50 МБ.")
        return

    ftype = detect_file_type(file_name, mime)
    if not ftype:
        ext = file_name.rsplit(".", 1)[-1].upper() if "." in file_name else "?"
        await send_msg(chat_id,
            f"❌ Формат <b>.{ext}</b> не поддерживается.\n\n"
            "Напиши /formats чтобы увидеть список.")
        return

    formats = get_possible_formats(ftype)
    if not formats:
        await send_msg(chat_id, "❌ Для этого файла нет доступных конвертаций.")
        return

    pending[chat_id] = {
        "mode": "convert",
        "file_id": file_id,
        "file_name": file_name,
        "file_ext": ftype,
    }

    buttons = [[{"text": f"{f['icon']}  {f['label']}", "callback_data": f"conv:{f['id']}"}]
               for f in formats]
    buttons.append([{"text": "❌ Отмена", "callback_data": "cancel"}])

    size_str = f"  ·  {sz(size)}" if size else ""
    await send_msg(chat_id,
        f"📁 <b>{file_name}</b>{size_str}\n\n"
        "Выбери формат конвертации 👇",
        {"inline_keyboard": buttons})


# ─── Merge mode ────────────────────────────────────────────────────────────────

async def start_merge(chat_id: int):
    pending[chat_id] = {"mode": "merge_collect", "files": []}
    await send_msg(chat_id,
        "📎 <b>Режим объединения</b>\n\n"
        "Отправляй файлы по одному (PDF или изображения PNG/JPG/BMP).\n\n"
        "Когда добавишь все — напиши /done\n"
        "Отмена: /cancel")


async def collect_file(chat_id: int, doc: dict):
    state = pending.get(chat_id, {})
    files = state.get("files", [])

    fname = doc.get("file_name", "file")
    fid   = doc.get("file_id", "")
    mime  = doc.get("mime_type", "")
    ftype = detect_file_type(fname, mime)

    if not ftype or (ftype != "pdf" and not is_image_ext(ftype)):
        await send_msg(chat_id,
            f"❌ <b>{fname}</b> не подходит.\n"
            "Можно добавлять только PDF и изображения (PNG, JPG, BMP).")
        return

    files.append({"file_id": fid, "file_name": fname, "file_type": ftype})
    pending[chat_id]["files"] = files

    await send_msg(chat_id,
        f"✅ Добавлен: <b>{fname}</b>\n"
        f"Файлов в очереди: {len(files)}\n\n"
        f"Добавляй ещё или напиши /done для объединения")


async def finish_merge(chat_id: int):
    state = pending.get(chat_id, {})
    files = state.get("files", [])

    if len(files) < 2:
        await send_msg(chat_id, "⚠️ Добавь минимум 2 файла.")
        return

    await send_msg(chat_id, f"⚙️ Объединяю {len(files)} файлов... ⏳")
    await send_action(chat_id)

    try:
        pdfs, imgs = [], []
        for f in files:
            data = await download(f["file_id"])
            if f["file_type"] == "pdf":
                pdfs.append(data)
            else:
                imgs.append(data)

        if imgs and not pdfs:
            result = merge_images_to_pdf(imgs)
        elif pdfs and not imgs:
            result = merge_pdfs(pdfs)
        else:
            await send_msg(chat_id,
                "❌ Нельзя смешивать PDF и изображения.\n"
                "Используй только PDF или только изображения.")
            return

        await send_doc(chat_id, result, "merged.pdf",
            f"✅ Готово! Объединено файлов: {len(files)}\n"
            f"📦 Размер: {sz(len(result))}")
        pending.pop(chat_id, None)
        await send_msg(chat_id, "Отправь новый файл когда понадоблюсь 😊")

    except Exception as e:
        logger.error(f"Merge error: {e}\n{traceback.format_exc()}")
        await send_msg(chat_id, f"❌ Ошибка при объединении:\n<code>{str(e)[:300]}</code>")


# ─── Callback handler ──────────────────────────────────────────────────────────

async def handle_callback(cb: dict):
    chat_id    = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    data       = cb.get("data", "")
    cb_id      = cb["id"]

    await answer_cb(cb_id)

    if data == "cancel":
        pending.pop(chat_id, None)
        await edit_msg(chat_id, message_id, "❌ Отменено. Отправь новый файл когда будешь готов.")

    elif data == "formats":
        await cmd_formats(chat_id)

    elif data == "start_merge":
        await start_merge(chat_id)

    elif data.startswith("conv:"):
        target = data.split(":", 1)[1]
        await do_convert(chat_id, message_id, target)


async def do_convert(chat_id: int, message_id: int, target_format: str):
    info = pending.get(chat_id)
    if not info or info.get("mode") != "convert":
        await send_msg(chat_id, "⚠️ Сессия устарела. Отправь файл заново.")
        return

    label_map = {
        "docx": "Word (DOCX)", "txt": "TXT", "png": "PNG",
        "jpg": "JPG", "pdf": "PDF", "compress": "сжатый файл",
    }
    label = label_map.get(target_format, target_format.upper())

    await edit_msg(chat_id, message_id,
        f"⚙️ Конвертирую в <b>{label}</b>...\n\nЭто может занять до 30 секунд ⏳")
    await send_action(chat_id)

    try:
        file_bytes = await download(info["file_id"])
        result, mime = convert(file_bytes, info["file_ext"], target_format)
        out_name = get_output_filename(info["file_name"], target_format)

        caption_lines = [
            f"✅ Конвертировал <b>{info['file_ext'].upper()} → {label}</b>",
            f"📦 Размер: {sz(len(result))}",
        ]
        if target_format == "compress":
            saved = (1 - len(result) / len(file_bytes)) * 100
            if saved > 0:
                caption_lines.append(f"💾 Сжато на {saved:.1f}%")
            else:
                caption_lines.append("ℹ️ Файл уже хорошо сжат")

        await send_doc(chat_id, result, out_name, "\n".join(caption_lines))
        pending.pop(chat_id, None)
        await send_msg(chat_id, "Готово! Отправь ещё файл если нужно 📁")

    except Exception as e:
        logger.error(f"Convert error: {e}\n{traceback.format_exc()}")
        await send_msg(chat_id,
            f"❌ Ошибка конвертации:\n<code>{str(e)[:300]}</code>\n\n"
            "Попробуй снова или отправь другой файл.")


# ─── Main update handler ───────────────────────────────────────────────────────

async def handle_update(update: dict):
    try:
        if "callback_query" in update:
            await handle_callback(update["callback_query"])
            return

        msg = update.get("message", {})
        if not msg:
            return

        chat_id = msg.get("chat", {}).get("id")
        if not chat_id:
            return

        text     = msg.get("text", "")
        document = msg.get("document")
        photo    = msg.get("photo")
        state    = pending.get(chat_id, {})

        # Если идёт сбор файлов для merge
        if state.get("mode") == "merge_collect":
            if text in ("/done", "/merge_done"):
                await finish_merge(chat_id)
            elif text == "/cancel":
                pending.pop(chat_id, None)
                await send_msg(chat_id, "❌ Объединение отменено.")
            elif document:
                await collect_file(chat_id, document)
            elif photo:
                best = photo[-1]
                await collect_file(chat_id, {
                    "file_id": best["file_id"],
                    "file_name": "photo.jpg",
                    "mime_type": "image/jpeg",
                    "file_size": best.get("file_size", 0),
                })
            else:
                await send_msg(chat_id,
                    "Отправляй файлы или напиши /done для объединения\n"
                    "Отмена: /cancel")
            return

        # Обычные команды и файлы
        if text.startswith("/start"):
            await cmd_start(chat_id, msg.get("from", {}))
        elif text.startswith("/help"):
            await cmd_help(chat_id)
        elif text.startswith("/formats"):
            await cmd_formats(chat_id)
        elif text.startswith("/merge"):
            await start_merge(chat_id)
        elif document:
            await handle_file(chat_id, document)
        elif photo:
            best = photo[-1]
            await handle_file(chat_id, {
                "file_id": best["file_id"],
                "file_name": "photo.jpg",
                "mime_type": "image/jpeg",
                "file_size": best.get("file_size", 0),
            })
        elif text and not text.startswith("/"):
            await send_msg(chat_id,
                "📁 Просто отправь файл — я помогу с конвертацией!\n\n"
                "/help — помощь  •  /formats — форматы  •  /merge — объединить")
        elif text.startswith("/"):
            await send_msg(chat_id,
                "Не знаю такую команду.\n\n"
                "/start — главное меню\n/help — помощь\n/merge — объединить файлы")

    except Exception as e:
        logger.error(f"handle_update error: {e}\n{traceback.format_exc()}")
