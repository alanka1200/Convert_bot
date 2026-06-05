# 🔄 Telegram File Converter Bot

Бот для конвертации файлов прямо в Telegram + удобный WebApp с drag & drop.

**Что умеет:**
- PDF → DOCX, PNG, TXT, сжатие PDF
- PNG/JPG/BMP → PDF, другой формат изображения, сжатие
- DOCX → TXT
- TXT → PDF
- Объединение нескольких PDF или изображений в один PDF

---

## 🚀 Деплой на Render (FREE, 0 рублей)

### Шаг 1 — Создай бота в Telegram

1. Открой [@BotFather](https://t.me/botfather)
2. Отправь `/newbot`
3. Придумай имя и username (username должен заканчиваться на `bot`)
4. Скопируй `BOT_TOKEN` — он нужен на шаге 4

---

### Шаг 2 — Залей код на GitHub

```bash
# Если не установлен git:
# скачай с https://git-scm.com

git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/ТВОЙ_НИКИ/telegram-converter-bot.git
git push -u origin main
```

Или просто создай новый репозиторий на [github.com](https://github.com/new), загрузи файлы через кнопку **"Upload files"**.

---

### Шаг 3 — Зарегистрируйся на Render

Иди на [render.com](https://render.com) → Sign Up → через GitHub.

---

### Шаг 4 — Создай Web Service

1. На дашборде Render нажми **New +** → **Web Service**
2. Подключи репозиторий с GitHub
3. Заполни настройки:

| Поле | Значение |
|------|----------|
| **Name** | `telegram-converter-bot` (или любое) |
| **Region** | Frankfurt (ближайший для RU) |
| **Branch** | `main` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | **Free** |

4. Нажми **Create Web Service** и подожди 2-5 минут пока задеплоится.

5. После деплоя скопируй URL сервиса. Он выглядит как:
   ```
   https://telegram-converter-bot-xxxx.onrender.com
   ```

---

### Шаг 5 — Добавь переменные окружения

В дашборде Render → твой сервис → **Environment** → **Add Environment Variable**:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | `1234567890:AAF...` (от BotFather) |
| `WEBHOOK_URL` | `https://telegram-converter-bot-xxxx.onrender.com/webhook` |

После добавления переменных Render автоматически перезапустит сервис.

---

### Шаг 6 — Проверь что всё работает

1. В браузере открой `https://твой-сервис.onrender.com/health`
   - Должен вернуть: `{"status":"ok","bot_configured":true}`

2. Открой `https://твой-сервис.onrender.com/`
   - Должен показаться WebApp с drag & drop интерфейсом

3. Напиши своему боту в Telegram `/start`
   - Должна появиться кнопка «Открыть WebApp» и меню

---

## 💻 Локальный запуск (для тестирования)

```bash
# 1. Создай виртуальное окружение
python -m venv venv
source venv/bin/activate        # Linux/Mac
# или: venv\Scripts\activate    # Windows

# 2. Установи зависимости
pip install -r requirements.txt

# 3. Задай переменные окружения (для локала без бота)
export BOT_TOKEN="твой_токен"
export WEBHOOK_URL="https://твой-сервис.onrender.com/webhook"

# 4. Запусти
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. Открой в браузере: http://localhost:8000
```

### Тест конвертации через curl

```bash
# Проверить возможные форматы для файла:
curl -X POST http://localhost:8000/possible \
  -F "file=@test.pdf"

# Конвертировать PDF в TXT:
curl -X POST http://localhost:8000/convert \
  -F "file=@test.pdf" \
  -F "target_format=txt" \
  --output result.txt

# Конвертировать изображение в PDF:
curl -X POST http://localhost:8000/convert \
  -F "file=@photo.jpg" \
  -F "target_format=pdf" \
  --output result.pdf
```

---

## ⚠️ Известные ограничения

| Ограничение | Причина |
|-------------|---------|
| DOCX → PDF не поддерживается | Требует LibreOffice на сервере |
| PDF → DOCX не идеален | `pdf2docx` теряет сложные таблицы |
| Сервер засыпает через 15 мин бездействия | Бесплатный тариф Render |
| Первый запрос после сна = 10-15 сек | Render пробуждает контейнер |
| Файлы не хранятся | `/tmp` — временный, очищается |
| Макс. размер файла: 50 МБ | Ограничение Telegram Bot API |

---

## 📁 Структура проекта

```
telegram-converter-bot/
├── main.py          # FastAPI + Telegram бот + WebApp
├── converter.py     # Все функции конвертации
├── utils.py         # Определение типов, маппинг форматов
├── requirements.txt # Зависимости Python
├── render.yaml      # Blueprint для Render (опционально)
└── README.md        # Эта инструкция
```

---

## 🛠️ Кастомизация

### Добавить новый формат конвертации

1. В `utils.py` добавить в `FORMAT_MAP` новый вход/выход
2. В `converter.py` добавить функцию конвертации
3. В функции `convert()` добавить диспетчеризацию

### Поменять лимит файла

В `utils.py`:
```python
MAX_FILE_SIZE_MB = 50  # изменить на нужное значение
```

---

## 📊 Поддерживаемые форматы

| Входной | Выходные форматы |
|---------|-----------------|
| PDF | DOCX, PNG (zip если многостраничный), TXT, сжатый PDF |
| PNG | JPG, PDF, сжатый PNG |
| JPG/JPEG | PNG, PDF, сжатый JPG |
| BMP | PNG, JPG, PDF |
| DOCX | TXT |
| TXT | PDF |
| Несколько PDF | Объединённый PDF |
| Несколько изображений | PDF |
