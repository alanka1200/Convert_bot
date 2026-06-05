# 🌿 FileConvert — Telegram Mini App

Красивый конвертер файлов в виде Telegram Mini App (WebApp).  
Дизайн: эко-минимализм, зелёная тема, мобильный интерфейс.

## Стек
- React 18 + TypeScript + Vite
- Tailwind CSS + shadcn/ui
- Telegram WebApp SDK

## Возможности
- 📄 PDF → Word, PNG, TXT, сжатие
- 🖼️ PNG/JPG/BMP → PDF, другой формат, сжатие  
- 📝 Word → TXT, TXT → PDF
- 📎 Объединение PDF и изображений в PDF
- 🔥 Главный экран с популярными конвертациями
- ↩️ Кнопка Back в Telegram
- 📳 Haptic feedback

---

## 🚀 Деплой (GitHub Pages = бесплатно)

### 1. Залей на GitHub

```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/ТВОЙ_НИК/tg-converter-webapp.git
git push -u origin main
```

### 2. Добавь секрет VITE_BACKEND_URL

GitHub → твой репо → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `VITE_BACKEND_URL` | `https://твой-рендер-сервис.onrender.com` |

### 3. Включи GitHub Pages

GitHub → твой репо → **Settings → Pages**  
Source: **GitHub Actions**

### 4. Запусти первый деплой

После push — Actions запустится автоматически.  
Через 2-3 минуты сайт будет по адресу:  
`https://ТВОЙ_НИК.github.io/tg-converter-webapp/`

### 5. Подключи к боту

В BotFather → `/newapp` или через `/mybots` → выбери бота → App Settings → Set URL:
```
https://ТВОЙ_НИК.github.io/tg-converter-webapp/
```

В коде бота добавь кнопку:
```python
keyboard = {"inline_keyboard": [[
    {"text": "🌿 Открыть конвертер", "web_app": {"url": "https://ТВОЙ_НИК.github.io/tg-converter-webapp/"}}
]]}
```

---

## 💻 Локальная разработка

```bash
pnpm install
cp .env.example .env      # впиши VITE_BACKEND_URL
pnpm dev                  # http://localhost:5173
```

---

## 📁 Структура

```
src/
├── App.tsx               # Главный компонент, вся логика
├── components/
│   ├── DropZone.tsx      # Drag & drop зона загрузки
│   ├── FileCard.tsx      # Карточка файла с прогрессом
│   ├── ConvertOptions.tsx# Выбор формата конвертации
│   ├── HotActions.tsx    # Сетка популярных конвертаций
│   └── ui/               # shadcn/ui компоненты
├── lib/
│   ├── formats.ts        # Маппинг форматов, логика
│   └── api.ts            # Клиент к Python-бэкенду
└── index.css             # Дизайн-токены (эко-тема)
```
