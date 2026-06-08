"""
main.py — FastAPI-приложение + Telegram-бот.
Запуск: uvicorn main:app --host 0.0.0.0 --port 10000
"""

import os
import io
import json
import logging
import asyncio
import traceback
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from utils import detect_file_type, get_possible_formats, get_output_filename, MAX_FILE_SIZE_MB, is_image_ext
from converter import convert, merge_pdfs, merge_images_to_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─────────────────────────────────────────────
# Хранилище состояний (в памяти, без Redis)
# ─────────────────────────────────────────────
# chat_id → {"file_id": str, "file_name": str, "file_ext": str}
pending_files: dict[int, dict] = {}


# ─────────────────────────────────────────────
# Вспомогательные функции Telegram
# ─────────────────────────────────────────────
async def tg_request(method: str, **kwargs) -> dict:
    url = f"{TELEGRAM_API}/{method}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, **kwargs)
    return resp.json()


async def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    return await tg_request("sendMessage", json=payload)


async def send_document(chat_id: int, file_bytes: bytes, filename: str, caption: str = ""):
    files = {"document": (filename, io.BytesIO(file_bytes), "application/octet-stream")}
    data = {"chat_id": str(chat_id), "caption": caption}
    return await tg_request("sendDocument", files=files, data=data)


async def answer_callback(callback_id: str, text: str = ""):
    return await tg_request("answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})


async def download_file(file_id: str) -> bytes:
    """Скачивает файл по file_id через Telegram."""
    r = await tg_request("getFile", json={"file_id": file_id})
    file_path = r["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
    return resp.content


# ─────────────────────────────────────────────
# Lifespan (установка вебхука при старте)
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    if BOT_TOKEN and WEBHOOK_URL:
        try:
            result = await tg_request("setWebhook", json={"url": WEBHOOK_URL})
            logger.info(f"Webhook set: {result}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    yield
    logger.info("Shutdown.")


app = FastAPI(title="File Converter Bot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Статичная страница WebApp (GET /)
# ─────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>🔄 Конвертер файлов</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #1a1a2e; color: #eee; min-height: 100vh; }
  .container { max-width: 600px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 1.6rem; text-align: center; margin-bottom: 6px;
       background: linear-gradient(90deg,#4fc3f7,#b39ddb); -webkit-background-clip:text;
       -webkit-text-fill-color:transparent; }
  .subtitle { text-align: center; color: #aaa; font-size: 0.85rem; margin-bottom: 24px; }

  .drop-zone { border: 2px dashed #4fc3f7; border-radius: 16px; padding: 40px 20px;
               text-align: center; cursor: pointer; transition: all .2s;
               background: rgba(79,195,247,.06); }
  .drop-zone:hover, .drop-zone.active { background: rgba(79,195,247,.15);
                                         border-color: #b39ddb; }
  .drop-zone .icon { font-size: 3rem; margin-bottom: 12px; }
  .drop-zone p { color: #aaa; font-size: 0.9rem; }
  .drop-zone b { color: #4fc3f7; }
  #file-input { display: none; }

  .file-info { background: rgba(255,255,255,.05); border-radius: 12px; padding: 14px;
               margin-top: 16px; display: none; }
  .file-info .name { font-weight: 600; color: #fff; margin-bottom: 4px; }
  .file-info .size { font-size: 0.8rem; color: #aaa; }

  .formats { margin-top: 20px; display: none; }
  .formats h3 { font-size: 0.9rem; color: #aaa; margin-bottom: 12px; }
  .format-btns { display: flex; flex-wrap: wrap; gap: 10px; }
  .fmt-btn { padding: 10px 16px; border-radius: 10px; border: 1.5px solid #4fc3f7;
             background: transparent; color: #4fc3f7; cursor: pointer; font-size: 0.9rem;
             transition: all .18s; }
  .fmt-btn:hover, .fmt-btn.selected { background: #4fc3f7; color: #1a1a2e; font-weight: 700; }

  .convert-btn { width: 100%; margin-top: 20px; padding: 14px; border-radius: 12px;
                 background: linear-gradient(135deg,#4fc3f7,#b39ddb); color: #1a1a2e;
                 font-size: 1rem; font-weight: 700; border: none; cursor: pointer;
                 display: none; transition: opacity .2s; }
  .convert-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .progress { display: none; margin-top: 16px; text-align: center; color: #4fc3f7; }
  .spinner { display: inline-block; width: 24px; height: 24px; border: 3px solid #4fc3f7;
             border-top-color: transparent; border-radius: 50%;
             animation: spin 0.8s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .error-box { background: rgba(255,82,82,.15); border: 1px solid #ff5252;
               border-radius: 10px; padding: 12px 16px; margin-top: 16px;
               color: #ff5252; font-size: 0.88rem; display: none; }
  .success-box { background: rgba(76,175,80,.15); border: 1px solid #4caf50;
                 border-radius: 10px; padding: 12px 16px; margin-top: 16px;
                 color: #4caf50; font-size: 0.88rem; display: none; }

  .limits { margin-top: 32px; font-size: 0.78rem; color: #555; text-align: center; line-height: 1.6; }
  .mode-tabs { display: flex; gap: 8px; margin-bottom: 20px; }
  .tab { flex: 1; padding: 10px; border-radius: 10px; border: 1.5px solid #333;
         background: transparent; color: #aaa; cursor: pointer; font-size: 0.85rem; transition: all .2s; }
  .tab.active { background: #333; color: #fff; border-color: #4fc3f7; }
</style>
</head>
<body>
<div class="container">
  <h1>🔄 Конвертер файлов</h1>
  <p class="subtitle">Загрузи файл — получи нужный формат бесплатно</p>

  <div class="mode-tabs">
    <button class="tab active" onclick="setMode('single')">Один файл</button>
    <button class="tab" onclick="setMode('merge')">Объединить</button>
  </div>

  <div class="drop-zone" id="drop-zone" onclick="document.getElementById('file-input').click()">
    <div class="icon">📁</div>
    <p>Нажми или перетащи файл сюда</p>
    <p style="margin-top:6px"><b>PDF, DOCX, TXT, PNG, JPG, BMP</b></p>
    <p style="margin-top:6px;font-size:0.78rem">Макс. 50 МБ</p>
  </div>
  <input type="file" id="file-input" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.bmp"
         onchange="handleFile(event)" />

  <div class="file-info" id="file-info">
    <div class="name" id="file-name"></div>
    <div class="size" id="file-size"></div>
  </div>

  <div class="formats" id="formats">
    <h3>Выбери формат конвертации:</h3>
    <div class="format-btns" id="format-btns"></div>
  </div>

  <button class="convert-btn" id="convert-btn" onclick="startConvert()" disabled>
    ⚡ Конвертировать
  </button>

  <div class="progress" id="progress">
    <span class="spinner"></span>Конвертация... это может занять до 30 сек.
  </div>
  <div class="error-box" id="error-box"></div>
  <div class="success-box" id="success-box"></div>

  <div class="limits">
    ⚡ Сервер может не отвечать первые ~15 сек (пробуждение)<br>
    🗑️ Файлы удаляются сразу после скачивания<br>
    📦 Максимальный размер файла: 50 МБ
  </div>
</div>

<script>
let selectedFile = null;
let selectedFormat = null;
let currentMode = 'single';
let selectedFiles = [];

function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', (i===0&&mode==='single')||(i===1&&mode==='merge')));
  document.getElementById('file-input').multiple = (mode === 'merge');
  reset();
}

function reset() {
  selectedFile = null; selectedFormat = null; selectedFiles = [];
  document.getElementById('file-info').style.display = 'none';
  document.getElementById('formats').style.display = 'none';
  document.getElementById('convert-btn').style.display = 'none';
  document.getElementById('convert-btn').disabled = true;
  document.getElementById('error-box').style.display = 'none';
  document.getElementById('success-box').style.display = 'none';
}

function showError(msg) {
  const el = document.getElementById('error-box');
  el.textContent = '❌ ' + msg;
  el.style.display = 'block';
}
function showSuccess(msg) {
  const el = document.getElementById('success-box');
  el.innerHTML = msg;
  el.style.display = 'block';
}

// Drag & drop
const dz = document.getElementById('drop-zone');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('active'); });
dz.addEventListener('dragleave', () => dz.classList.remove('active'));
dz.addEventListener('drop', e => {
  e.preventDefault(); dz.classList.remove('active');
  const fakeEvent = { target: { files: e.dataTransfer.files } };
  handleFile(fakeEvent);
});

async function handleFile(event) {
  const files = event.target.files;
  if (!files || files.length === 0) return;
  document.getElementById('error-box').style.display = 'none';
  document.getElementById('success-box').style.display = 'none';

  if (currentMode === 'merge') {
    selectedFiles = Array.from(files);
    document.getElementById('file-info').style.display = 'block';
    document.getElementById('file-name').textContent = `Выбрано файлов: ${selectedFiles.length}`;
    const totalSize = selectedFiles.reduce((s,f)=>s+f.size,0);
    document.getElementById('file-size').textContent = `Общий размер: ${(totalSize/1024/1024).toFixed(2)} МБ`;
    document.getElementById('formats').style.display = 'none';
    document.getElementById('convert-btn').style.display = 'block';
    document.getElementById('convert-btn').disabled = false;
    document.getElementById('convert-btn').textContent = '📎 Объединить в PDF';
    return;
  }

  selectedFile = files[0];
  const sizeMB = selectedFile.size / 1024 / 1024;
  if (sizeMB > 50) { showError(`Файл слишком большой: ${sizeMB.toFixed(1)} МБ. Лимит 50 МБ.`); return; }

  document.getElementById('file-info').style.display = 'block';
  document.getElementById('file-name').textContent = selectedFile.name;
  document.getElementById('file-size').textContent = `${sizeMB.toFixed(2)} МБ`;

  // Запрашиваем возможные форматы
  const formData = new FormData();
  formData.append('file', selectedFile);
  try {
    const resp = await fetch('/possible', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.error) { showError(data.error); return; }
    renderFormatBtns(data.formats);
  } catch(e) {
    showError('Ошибка соединения с сервером. Попробуй ещё раз.');
  }
}

function renderFormatBtns(formats) {
  const container = document.getElementById('format-btns');
  container.innerHTML = '';
  if (!formats || formats.length === 0) {
    showError('Формат файла не поддерживается.');
    return;
  }
  formats.forEach(f => {
    const btn = document.createElement('button');
    btn.className = 'fmt-btn';
    btn.textContent = f.label;
    btn.dataset.id = f.id;
    btn.onclick = () => {
      document.querySelectorAll('.fmt-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedFormat = f.id;
      document.getElementById('convert-btn').style.display = 'block';
      document.getElementById('convert-btn').disabled = false;
      document.getElementById('convert-btn').textContent = '⚡ Конвертировать';
    };
    container.appendChild(btn);
  });
  document.getElementById('formats').style.display = 'block';
}

async function startConvert() {
  document.getElementById('error-box').style.display = 'none';
  document.getElementById('success-box').style.display = 'none';
  document.getElementById('progress').style.display = 'block';
  document.getElementById('convert-btn').disabled = true;

  const formData = new FormData();
  try {
    if (currentMode === 'merge') {
      selectedFiles.forEach(f => formData.append('files', f));
      const resp = await fetch('/merge', { method: 'POST', body: formData });
      await handleConvertResponse(resp, 'merged.pdf');
    } else {
      formData.append('file', selectedFile);
      formData.append('target_format', selectedFormat);
      const resp = await fetch('/convert', { method: 'POST', body: formData });
      const outName = getOutputName(selectedFile.name, selectedFormat);
      await handleConvertResponse(resp, outName);
    }
  } catch(e) {
    showError('Ошибка соединения. Попробуй ещё раз.');
  } finally {
    document.getElementById('progress').style.display = 'none';
    document.getElementById('convert-btn').disabled = false;
  }
}

async function handleConvertResponse(resp, filename) {
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({detail: 'Неизвестная ошибка'}));
    showError(err.detail || 'Ошибка конвертации.');
    return;
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
  showSuccess('✅ Готово! Файл скачивается...');
}

function getOutputName(originalName, format) {
  const base = originalName.replace(/\\.[^/.]+$/, '');
  if (format === 'compress') return base + '_compressed.' + (originalName.split('.').pop());
  if (format === 'png') return base + '.zip';
  return base + '.' + format;
}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_PAGE)


@app.post("/possible")
async def possible(file: UploadFile = File(...)):
    """Возвращает список доступных форматов конвертации для загруженного файла."""
    content = await file.read()
    size_mb = len(content) / 1024 / 1024
    if size_mb > MAX_FILE_SIZE_MB:
        return JSONResponse({"error": f"Файл слишком большой: {size_mb:.1f} МБ. Лимит {MAX_FILE_SIZE_MB} МБ."})

    file_type = detect_file_type(file.filename or "", file.content_type)
    if not file_type:
        return JSONResponse({"error": "Формат файла не поддерживается.", "formats": []})

    formats = get_possible_formats(file_type)
    return JSONResponse({"formats": formats, "file_type": file_type})


@app.post("/convert")
async def convert_endpoint(
    file: UploadFile = File(...),
    target_format: str = Form(...),
):
    """Конвертирует файл в указанный формат."""
    content = await file.read()
    size_mb = len(content) / 1024 / 1024
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, detail=f"Файл слишком большой: {size_mb:.1f} МБ.")

    file_type = detect_file_type(file.filename or "", file.content_type)
    if not file_type:
        raise HTTPException(400, detail="Формат файла не поддерживается.")

    try:
        result_bytes, mime = convert(content, file_type, target_format)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(500, detail=str(e))
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(500, detail=f"Внутренняя ошибка: {e}")

    out_filename = get_output_filename(file.filename or "file", target_format)
    return Response(
        content=result_bytes,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'},
    )


@app.post("/merge")
async def merge_endpoint(files: list[UploadFile] = File(...)):
    """Объединяет несколько файлов (PDF или изображений) в один PDF."""
    if not files or len(files) < 2:
        raise HTTPException(400, detail="Нужно загрузить минимум 2 файла.")

    pdf_bytes_list = []
    img_bytes_list = []

    for f in files:
        content = await f.read()
        ext = detect_file_type(f.filename or "", f.content_type)
        if ext == "pdf":
            pdf_bytes_list.append(content)
        elif ext and is_image_ext(ext):
            img_bytes_list.append(content)
        else:
            raise HTTPException(400, detail=f"Файл '{f.filename}' не поддерживается для объединения.")

    try:
        if img_bytes_list and not pdf_bytes_list:
            result = merge_images_to_pdf(img_bytes_list)
        elif pdf_bytes_list and not img_bytes_list:
            result = merge_pdfs(pdf_bytes_list)
        else:
            raise HTTPException(400, detail="Нельзя смешивать PDF и изображения при объединении.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(500, detail=f"Ошибка объединения: {e}")

    return Response(
        content=result,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="merged.pdf"'},
    )


# ─────────────────────────────────────────────
# Telegram Webhook
# ─────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request):
    """Принимает обновления от Telegram."""
    try:
        update = await request.json()
        asyncio.create_task(handle_update(update))
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
    return {"ok": True}


async def handle_update(update: dict):
    """Обрабатывает входящее Telegram-обновление."""
    try:
        # Callback query (нажатие инлайн-кнопки)
        if "callback_query" in update:
            await handle_callback(update["callback_query"])
            return

        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        if not chat_id:
            return

        text = message.get("text", "")
        document = message.get("document")
        photo = message.get("photo")

        if text.startswith("/start"):
            await handle_start(chat_id)

        elif text.startswith("/help"):
            await send_message(chat_id, (
                "📋 <b>Поддерживаемые форматы:</b>\n"
                "• PDF → DOCX, PNG, TXT, сжатие\n"
                "• PNG/JPG/BMP → PDF, другой формат, сжатие\n"
                "• DOCX → TXT\n"
                "• TXT → PDF\n\n"
                "Просто отправь файл и выбери что делать!"
            ))

        elif document:
            await handle_document(chat_id, document)

        elif photo:
            # Берём фото максимального размера
            photo_file = photo[-1]
            await handle_document(chat_id, {"file_id": photo_file["file_id"],
                                             "file_name": "photo.jpg",
                                             "mime_type": "image/jpeg"})
        else:
            if text and not text.startswith("/"):
                await send_message(chat_id, "Отправь мне файл, и я помогу с конвертацией! 📁")

    except Exception as e:
        logger.error(f"handle_update error: {e}\n{traceback.format_exc()}")


async def handle_start(chat_id: int):
    webapp_url = WEBHOOK_URL.replace("/webhook", "") if WEBHOOK_URL else "https://your-service.onrender.com"
    keyboard = {
        "inline_keyboard": [[
            {"text": "🌐 Открыть WebApp", "web_app": {"url": webapp_url}}
        ], [
            {"text": "❓ Помощь", "callback_data": "help"}
        ]]
    }
    await send_message(
        chat_id,
        "👋 Привет! Я конвертирую файлы прямо в Telegram.\n\n"
        "📁 <b>Просто отправь мне файл</b> — я предложу варианты конвертации.\n\n"
        "Или открой <b>WebApp</b> для удобного интерфейса с drag & drop!\n\n"
        "📝 <b>Поддерживаю:</b> PDF, DOCX, TXT, PNG, JPG, BMP",
        reply_markup=keyboard
    )


async def handle_document(chat_id: int, document: dict):
    """Обрабатывает входящий документ."""
    file_id = document.get("file_id")
    file_name = document.get("file_name", "file")
    mime_type = document.get("mime_type", "")

    file_type = detect_file_type(file_name, mime_type)
    if not file_type:
        await send_message(chat_id, "❌ Формат файла не поддерживается.\n\nПоддерживаю: PDF, DOCX, TXT, PNG, JPG, JPEG, BMP")
        return

    formats = get_possible_formats(file_type)
    if not formats:
        await send_message(chat_id, "❌ Для этого типа файла нет доступных конвертаций.")
        return

    # Сохраняем состояние
    pending_files[chat_id] = {
        "file_id": file_id,
        "file_name": file_name,
        "file_ext": file_type,
    }

    # Строим inline-клавиатуру с форматами
    buttons = [[{"text": f["label"], "callback_data": f"convert:{f['id']}"}] for f in formats]
    buttons.append([{"text": "❌ Отмена", "callback_data": "cancel"}])

    keyboard = {"inline_keyboard": buttons}
    await send_message(
        chat_id,
        f"📁 Файл принят: <b>{file_name}</b> ({file_type.upper()})\n\nВыбери формат конвертации:",
        reply_markup=keyboard
    )


async def handle_callback(callback_query: dict):
    """Обрабатывает нажатие инлайн-кнопки."""
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]
    data = callback_query.get("data", "")
    callback_id = callback_query["id"]

    await answer_callback(callback_id)

    if data == "cancel":
        pending_files.pop(chat_id, None)
        await tg_request("editMessageText", json={
            "chat_id": chat_id, "message_id": message_id,
            "text": "❌ Отменено. Отправь новый файл."
        })
        return

    if data == "help":
        await send_message(chat_id, (
            "📋 <b>Поддерживаемые форматы:</b>\n"
            "• PDF → DOCX, PNG, TXT, сжатие\n"
            "• PNG/JPG/BMP → PDF, другой формат, сжатие\n"
            "• DOCX → TXT\n• TXT → PDF"
        ))
        return

    if data.startswith("convert:"):
        target_format = data.split(":")[1]
        file_info = pending_files.get(chat_id)

        if not file_info:
            await send_message(chat_id, "⚠️ Сессия устарела. Отправь файл заново.")
            return

        # Уведомляем о начале конвертации
        await tg_request("editMessageText", json={
            "chat_id": chat_id, "message_id": message_id,
            "text": f"⚙️ Конвертирую в <b>{target_format.upper()}</b>... Подожди немного."
        })

        try:
            file_bytes = await download_file(file_info["file_id"])
            result_bytes, mime = convert(file_bytes, file_info["file_ext"], target_format)
            out_name = get_output_filename(file_info["file_name"], target_format)

            orig_size = len(file_bytes) / 1024
            result_size = len(result_bytes) / 1024
            caption = f"✅ Готово!\n📁 {out_size_str(len(result_bytes))}"
            if target_format == "compress":
                saved = (1 - len(result_bytes) / len(file_bytes)) * 100
                caption += f" (сжато на {saved:.1f}%)"

            await send_document(chat_id, result_bytes, out_name, caption)
            pending_files.pop(chat_id, None)

        except Exception as e:
            logger.error(f"Convert callback error: {e}\n{traceback.format_exc()}")
            await send_message(chat_id, f"❌ Ошибка конвертации: {e}\n\nПопробуй снова или используй WebApp.")


def out_size_str(size_bytes: int) -> str:
    if size_bytes > 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} МБ"
    return f"{size_bytes / 1024:.0f} КБ"


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "bot_configured": bool(BOT_TOKEN)}
