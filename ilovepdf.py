"""
ilovepdf.py — конвертация DOCX/Office → PDF через iLovePDF REST API.
Документация: https://developer.ilovepdf.com/docs/api-reference

Логика:
1. Пробуем iLovePDF API (self-signed JWT, без /auth раунд-трипа)
2. При 401/403/любой ошибке API — fallback на mammoth + xhtml2pdf (только для DOCX/DOC)
3. Для XLSX/PPTX — только iLovePDF, если недоступен — понятная ошибка
"""

import os
import io
import time
import logging
import httpx

logger = logging.getLogger(__name__)

ILOVEPDF_PUBLIC_KEY = os.environ.get("ILOVEPDF_PUBLIC_KEY", "")
ILOVEPDF_SECRET_KEY = os.environ.get("ILOVEPDF_SECRET_KEY", "")

# Обратная совместимость: если задан только старый ключ ILOVEPDF_SECRET_KEY
# и он начинается с project_public_ — это на самом деле public key
_legacy = os.environ.get("ILOVEPDF_SECRET_KEY", "")
if not ILOVEPDF_PUBLIC_KEY and _legacy.startswith("project_public_"):
    ILOVEPDF_PUBLIC_KEY = _legacy
    ILOVEPDF_SECRET_KEY = ""

API_BASE = "https://api.ilovepdf.com/v1"


def _make_jwt() -> str:
    """
    Создаём self-signed JWT без /auth раунд-трипа.
    Нужны оба ключа: public (jti) и secret (подпись).
    """
    try:
        import jwt as pyjwt
    except ImportError:
        raise RuntimeError("Установи PyJWT: pip install PyJWT")

    now = int(time.time())
    payload = {
        "iss": "api.ilovepdf.com",
        "aud": "",
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
        "jti": ILOVEPDF_PUBLIC_KEY,
    }
    return pyjwt.encode(payload, ILOVEPDF_SECRET_KEY, algorithm="HS256")


async def _get_token_via_auth() -> str:
    """Fallback: получаем токен через /auth с public key."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE}/auth",
            json={"public_key": ILOVEPDF_PUBLIC_KEY}
        )
    if resp.status_code == 401:
        raise RuntimeError(
            "iLovePDF 401: неверный ключ или аккаунт не подтверждён. "
            "Проверь: 1) email подтверждён на developer.ilovepdf.com, "
            "2) переменная ILOVEPDF_PUBLIC_KEY содержит project_public_... ключ, "
            "3) переменная ILOVEPDF_SECRET_KEY содержит secret_key_... ключ"
        )
    resp.raise_for_status()
    return resp.json()["token"]


async def _get_token() -> str:
    """
    Получаем JWT. Пробуем self-signed (быстро, без сети),
    при ошибке (нет secret key) — через /auth.
    """
    if ILOVEPDF_PUBLIC_KEY and ILOVEPDF_SECRET_KEY:
        try:
            return _make_jwt()
        except Exception as e:
            logger.warning(f"self-signed JWT failed: {e}, fallback to /auth")

    if ILOVEPDF_PUBLIC_KEY:
        return await _get_token_via_auth()

    raise RuntimeError("Не заданы ключи iLovePDF. Задай ILOVEPDF_PUBLIC_KEY в переменных окружения Render.")


async def _office_to_pdf_api(file_bytes: bytes, filename: str) -> bytes:
    """Конвертация через iLovePDF API (основной путь)."""
    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=120) as client:
        # 1. Создаём задачу
        resp = await client.get(f"{API_BASE}/start/officepdf", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        server = data["server"]
        task_id = data["task"]

        base = f"https://{server}/v1"
        task_headers = {"Authorization": f"Bearer {token}"}

        # 2. Загружаем файл
        resp = await client.post(
            f"{base}/upload",
            headers=task_headers,
            data={"task": task_id},
            files={"file": (filename, file_bytes, "application/octet-stream")}
        )
        resp.raise_for_status()
        server_filename = resp.json()["server_filename"]

        # 3. Запускаем конвертацию
        resp = await client.post(
            f"{base}/process",
            headers=task_headers,
            json={
                "task": task_id,
                "tool": "officepdf",
                "files": [{"server_filename": server_filename, "filename": filename}]
            }
        )
        resp.raise_for_status()

        # 4. Скачиваем результат
        resp = await client.get(f"{base}/download/{task_id}", headers=task_headers)
        resp.raise_for_status()
        result_pdf = resp.content

        # 5. Чистим задачу
        try:
            await client.delete(f"{base}/task/{task_id}", headers=task_headers)
        except Exception:
            pass

    return result_pdf


def _office_to_pdf_local(file_bytes: bytes, filename: str) -> bytes:
    """
    Fallback для DOCX/DOC через mammoth + xhtml2pdf (чисто Python, без зависимостей ОС).
    Качество ниже чем у iLovePDF, но работает всегда.
    XLSX/PPTX не поддерживается этим методом.
    """
    try:
        import mammoth
        from xhtml2pdf import pisa

        logger.info(f"Fallback: mammoth + xhtml2pdf для {filename}")

        # DOCX → HTML
        result = mammoth.convert_to_html(io.BytesIO(file_bytes))
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; margin: 2cm; font-size: 11pt; line-height: 1.5; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td, th {{ border: 1px solid #ccc; padding: 4px 8px; }}
  img {{ max-width: 100%; }}
</style>
</head>
<body>{result.value}</body>
</html>"""

        output = io.BytesIO()
        pisa_status = pisa.CreatePDF(html, dest=output)
        if pisa_status.err:
            raise RuntimeError(f"xhtml2pdf error: {pisa_status.err}")
        return output.getvalue()

    except ImportError as e:
        raise RuntimeError(
            f"Fallback-конвертация недоступна: не установлены mammoth/xhtml2pdf ({e}). "
            "Добавь их в requirements.txt"
        )
    except Exception as e:
        logger.error(f"Local DOCX→PDF fallback error: {e}")
        raise RuntimeError(f"Ошибка локальной конвертации DOCX→PDF: {e}")


async def office_to_pdf(file_bytes: bytes, filename: str) -> bytes:
    """
    Главная функция: DOCX/DOC/XLSX/XLS/PPTX/PPT → PDF.
    1. Пробуем iLovePDF API
    2. Если API недоступен и файл DOCX/DOC — пробуем локальный fallback
    3. Иначе — понятная ошибка
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Пробуем API
    if ILOVEPDF_PUBLIC_KEY:
        try:
            return await _office_to_pdf_api(file_bytes, filename)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                logger.error(
                    "iLovePDF 401: проверь ILOVEPDF_PUBLIC_KEY и ILOVEPDF_SECRET_KEY в Render. "
                    "Email аккаунта должен быть подтверждён на developer.ilovepdf.com"
                )
                # Для DOCX/DOC пробуем локальный fallback
                if ext in ("docx", "doc"):
                    logger.info("Пробуем локальный fallback (mammoth + xhtml2pdf)")
                    try:
                        return _office_to_pdf_local(file_bytes, filename)
                    except Exception as fe:
                        logger.error(f"Local fallback тоже упал: {fe}")
                raise RuntimeError(
                    "Конвертация Office → PDF временно недоступна (ошибка авторизации API). "
                    "Администратор уведомлён."
                )
            elif status == 429:
                raise RuntimeError("iLovePDF: превышен лимит запросов. Попробуй позже.")
            else:
                logger.error(f"iLovePDF API error {status}: {e.response.text[:300]}")
                # Fallback для DOCX/DOC
                if ext in ("docx", "doc"):
                    try:
                        return _office_to_pdf_local(file_bytes, filename)
                    except Exception as fe:
                        logger.error(f"Local fallback упал: {fe}")
                raise RuntimeError(f"Ошибка iLovePDF API: {status}")
        except Exception as e:
            logger.error(f"iLovePDF unexpected error: {e}")
            # Fallback для DOCX/DOC
            if ext in ("docx", "doc"):
                try:
                    return _office_to_pdf_local(file_bytes, filename)
                except Exception as fe:
                    logger.error(f"Local fallback упал: {fe}")
            raise

    # API не настроен — только DOCX fallback
    if ext in ("docx", "doc"):
        logger.warning("ILOVEPDF_PUBLIC_KEY не задан, используем локальный fallback")
        return _office_to_pdf_local(file_bytes, filename)

    raise RuntimeError(
        "Конвертация XLSX/PPTX → PDF требует iLovePDF API. "
        "Задай ILOVEPDF_PUBLIC_KEY в переменных окружения."
    )


def is_ilovepdf_available() -> bool:
    """API настроен или есть локальный fallback для DOCX."""
    return bool(ILOVEPDF_PUBLIC_KEY)


def is_any_pdf_conversion_available(file_ext: str) -> bool:
    """Можно ли сконвертировать файл в PDF хоть каким-то способом."""
    if ILOVEPDF_PUBLIC_KEY:
        return True
    # Без API умеем только DOCX через fallback
    return file_ext in ("docx", "doc")
