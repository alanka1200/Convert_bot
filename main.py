"""
main.py — Telegram бот-конвертер файлов.
Чистый бот: пользователь шлёт файл → бот анализирует → предлагает варианты → конвертирует → присылает результат.
"""

import os
import io
import json
import random
import logging
import asyncio
import zipfile
import traceback
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from utils import detect_file_type, get_possible_formats, get_output_filename, is_image_ext
from converter import convert, merge_pdfs, merge_images_to_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
TG_API     = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Хранилище состояний в памяти: chat_id → dict
state: dict[int, dict] = {}


# ─── Telegram helpers ──────────────────────────────────────────────────────────

async def tg(method: str, **kwargs) -> dict:
    url = f"{TG_API}/{method}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, **kwargs)
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
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
    return resp.content


def sz(b: int) -> str:
    if b >= 1024 * 1024:
        return f"{b/1024/1024:.1f} МБ"
    if b >= 1024:
        return f"{b/1024:.0f} КБ"
    return f"{b} Б"


# ─── Приветственное описание бота (показывается через /start) ──────────────────

BOT_DESCRIPTION = (
    "Привет! 👋 Я бот-конвертер файлов.\n\n"
    "Помогаю конвертировать документы и изображения в нужный формат, "
    "сжимать файлы и создавать ZIP-архивы прямо в Telegram — "
    "бесплатно, быстро и без лишних действий.\n\n"
    "Полезен для учёбы, работы и повседневных задач 🎓💼\n\n"
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
    "1. Нажми кнопку 📦 Создать архив или напиши /zip\n"
    "2. Отправляй файлы по одному\n"
    "3. Напиши /done — получишь ZIP\n\n"
    "<b>Что поддерживается:</b>\n"
    "• PDF → Word, PNG, TXT, сжатие\n"
    "• PNG/JPG/BMP → PDF, другой формат, сжатие\n"
    "• DOCX (Word) → TXT\n"
    "• TXT → PDF\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/formats — все форматы\n"
    "/zip — создать ZIP-архив\n\n"
    "⚠️ Максимальный размер файла: 50 МБ"
)

FORMATS_TEXT = (
    "📋 <b>Поддерживаемые форматы конвертации</b>\n\n"
    "📄 <b>PDF</b>\n"
    "  → Word (DOCX), PNG, TXT, сжатие\n\n"
    "🖼 <b>PNG / JPG / JPEG / BMP</b>\n"
    "  → PDF, другой формат, сжатие\n\n"
    "📝 <b>DOCX (Word)</b>\n"
    "  → TXT (извлечь текст)\n\n"
    "🔤 <b>TXT</b>\n"
    "  → PDF\n\n"
    "📦 <b>ZIP-архив</b>\n"
    "  Любые файлы → ZIP\n"
    "  Команда: /zip"
)


# ─── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if BOT_TOKEN and WEBHOOK_URL:
        try:
            r = await tg("setWebhook", json={"url": WEBHOOK_URL})
            logger.info(f"Webhook set: {r.get('description', r)}")
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
        logger.error(f"Webhook parse error: {e}")
    return {"ok": True}


# ─── Главный диспетчер ────────────────────────────────────────────────────────

async def handle_update(update: dict):
    try:
        if "callback_query" in update:
            await on_callback(update["callback_query"])
            return

        msg = update.get("message", {})
        if not msg:
            return

        chat_id  = msg.get("chat", {}).get("id")
        if not chat_id:
            return

        text     = msg.get("text", "")
        document = msg.get("document")
        photo    = msg.get("photo")
        st       = state.get(chat_id, {})

        # ── Режим сбора файлов для ZIP-архива ──
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
                    "📦 Отправляй файлы для архива или напиши /done чтобы создать ZIP\n"
                    "Отмена: /cancel")
            return

        # ── Обычный режим ──
        if text.startswith("/start"):
            await cmd_start(chat_id, msg.get("from", {}))
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
                "/help — как пользоваться\n"
                "/formats — форматы конвертации\n"
                "/zip — создать ZIP-архив")
        elif text.startswith("/"):
            await send(chat_id,
                "Не знаю такую команду 🤷\n\n"
                "/start — главное меню\n"
                "/help — справка")

    except Exception as e:
        logger.error(f"handle_update error: {e}\n{traceback.format_exc()}")


def _photo_as_doc(photo: list) -> dict:
    best = photo[-1]
    return {
        "file_id":   best["file_id"],
        "file_name": "photo.jpg",
        "mime_type": "image/jpeg",
        "file_size": best.get("file_size", 0),
    }


# ─── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(chat_id: int, user: dict):
    name = user.get("first_name", "")
    greet = f"{'Привет, ' + name + '! 👋' if name else 'Привет! 👋'}\n\n"
    kb = {"inline_keyboard": [
        [{"text": "📋 Все форматы", "callback_data": "formats"},
         {"text": "❓ Помощь",      "callback_data": "help"}],
        [{"text": "📦 Создать ZIP-архив", "callback_data": "zip"}],
    ]}
    await send(chat_id, greet + BOT_DESCRIPTION, kb)


# ─── /zip ────────────────────────────────────────────────────────────────────

async def cmd_zip(chat_id: int):
    state[chat_id] = {"mode": "zip_collect", "files": []}
    await send(chat_id,
        "📦 <b>Создание ZIP-архива</b>\n\n"
        "Отправляй файлы по одному — я добавлю их в архив.\n"
        "Когда все файлы отправлены — напиши /done\n\n"
        "Отмена: /cancel")


async def collect_zip_file(chat_id: int, doc: dict):
    files = state.get(chat_id, {}).get("files", [])
    fname = doc.get("file_name", "file")
    fid   = doc.get("file_id", "")
    fsize = doc.get("file_size", 0)

    files.append({"file_id": fid, "file_name": fname, "file_size": fsize})
    state[chat_id]["files"] = files

    await send(chat_id,
        f"✅ Добавлен: <b>{fname}</b> ({sz(fsize)})\n"
        f"Файлов в архиве: <b>{len(files)}</b>\n\n"
        "Добавляй ещё или напиши /done для создания ZIP")


async def finish_zip(chat_id: int):
    files = state.get(chat_id, {}).get("files", [])

    if not files:
        await send(chat_id, "⚠️ Ты не добавил ни одного файла. Отправь файлы и напиши /done")
        return

    await send(chat_id, f"⚙️ Создаю ZIP-архив из {len(files)} файлов... ⏳")
    await typing(chat_id)

    try:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                data = await dl(f["file_id"])
                # Если одинаковые имена — добавляем номер
                zf.writestr(f["file_name"], data)

        zip_bytes = zip_buf.getvalue()
        await send_file(chat_id, zip_bytes, "archive.zip",
            f"✅ ZIP-архив готов!\n"
            f"📂 Файлов: {len(files)}\n"
            f"📦 Размер архива: {sz(len(zip_bytes))}")
        state.pop(chat_id, None)
        await send(chat_id, "Отправь новый файл если понадоблюсь 😊")

    except Exception as e:
        logger.error(f"ZIP error: {e}\n{traceback.format_exc()}")
        await send(chat_id, f"❌ Ошибка при создании архива:\n<code>{str(e)[:300]}</code>")


# ─── Обработка входящего файла ─────────────────────────────────────────────────

async def on_file(chat_id: int, doc: dict):
    fname  = doc.get("file_name", "file")
    fid    = doc.get("file_id", "")
    mime   = doc.get("mime_type", "")
    fsize  = doc.get("file_size", 0)

    if fsize > 50 * 1024 * 1024:
        await send(chat_id,
            f"❌ Файл слишком большой ({sz(fsize)}).\n"
            "Максимальный размер — 50 МБ.")
        return

    ftype   = detect_file_type(fname, mime)
    formats = get_possible_formats(ftype) if ftype else []

    state[chat_id] = {
        "mode": "convert",
        "file_id":   fid,
        "file_name": fname,
        "file_ext":  ftype or "",
        "file_size": fsize,
    }

    ext_label = fname.rsplit(".", 1)[-1].upper() if "." in fname else "?"
    size_str  = f"  ·  {sz(fsize)}" if fsize else ""

    if not ftype or not formats:
        # Формат не поддерживается для конвертации — но можно добавить в архив
        kb = {"inline_keyboard": [
            [{"text": "📦 Добавить в ZIP-архив", "callback_data": "zip"}],
            [{"text": "❌ Отмена",               "callback_data": "cancel"}],
        ]}
        await send(chat_id,
            f"📁 <b>{fname}</b>{size_str}\n\n"
            f"Формат <b>.{ext_label}</b> не поддерживается для конвертации.\n\n"
            "Но я могу добавить этот файл в ZIP-архив 📦",
            kb)
        return

    # Строим кнопки: конвертация + архив
    buttons = [[{"text": f"{f['icon']}  {f['label']}", "callback_data": f"conv:{f['id']}"}]
               for f in formats]
    buttons.append([{"text": "📦 Добавить в ZIP-архив", "callback_data": "zip"}])
    buttons.append([{"text": "❌ Отмена", "callback_data": "cancel"}])

    await send(chat_id,
        f"📁 <b>{fname}</b>{size_str}\n\n"
        f"Вот что я могу сделать с этим файлом 👇",
        {"inline_keyboard": buttons})


# ─── Callback handler ──────────────────────────────────────────────────────────

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

    elif data == "zip":
        # Если есть текущий файл — предлагаем добавить его в архив сразу
        st = state.get(chat_id, {})
        if st.get("file_id"):
            state[chat_id] = {
                "mode": "zip_collect",
                "files": [{
                    "file_id":   st["file_id"],
                    "file_name": st["file_name"],
                    "file_size": st.get("file_size", 0),
                }]
            }
            await edit(chat_id, msg_id,
                f"📦 Файл <b>{st['file_name']}</b> добавлен в архив.\n\n"
                "Отправляй ещё файлы или напиши /done чтобы получить ZIP\n"
                "Отмена: /cancel")
        else:
            await cmd_zip(chat_id)

    elif data.startswith("conv:"):
        target = data.split(":", 1)[1]
        await do_convert(chat_id, msg_id, target)


# ─── Конвертация ───────────────────────────────────────────────────────────────

LABEL = {
    "docx": "Word (DOCX)", "txt": "TXT", "png": "PNG",
    "jpg": "JPG", "pdf": "PDF", "compress": "сжатый файл",
}


async def do_convert(chat_id: int, msg_id: int, target: str):
    info = state.get(chat_id)
    if not info or info.get("mode") != "convert" or not info.get("file_id"):
        await send(chat_id, "⚠️ Сессия устарела. Отправь файл заново.")
        return

    label = LABEL.get(target, target.upper())

    await edit(chat_id, msg_id,
        f"⚙️ Конвертирую в <b>{label}</b>...\n\nЭто может занять до 30 секунд ⏳")
    await typing(chat_id)

    try:
        raw    = await dl(info["file_id"])
        result, mime = convert(raw, info["file_ext"], target)
        out    = get_output_filename(info["file_name"], target)

        lines = [
            f"✅ <b>{info['file_ext'].upper()} → {label}</b>",
            f"📦 Размер: {sz(len(result))}",
        ]
        if target == "compress":
            saved = (1 - len(result) / len(raw)) * 100
            lines.append(
                f"💾 Сжато на {saved:.1f}%" if saved > 0
                else "ℹ️ Файл уже хорошо сжат"
            )

        await send_file(chat_id, result, out, "\n".join(lines))
        state.pop(chat_id, None)
        await send(chat_id, "Готово! Отправь ещё файл если нужно 📁")

    except Exception as e:
        logger.error(f"Convert error: {e}\n{traceback.format_exc()}")
        await send(chat_id,
            f"❌ Ошибка конвертации:\n<code>{str(e)[:300]}</code>\n\n"
            "Попробуй снова или отправь другой файл.")
