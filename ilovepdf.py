"""
ilovepdf.py — конвертация DOCX/Office → PDF через iLovePDF REST API.
Документация: https://developer.ilovepdf.com/docs/api-reference
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

ILOVEPDF_KEY = os.environ.get("ILOVEPDF_SECRET_KEY", "")
API_START    = "https://api.ilovepdf.com/v1"


async def _get_token() -> str:
    """Получаем JWT токен по публичному ключу."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_START}/auth",
            json={"public_key": ILOVEPDF_KEY}
        )
    resp.raise_for_status()
    return resp.json()["token"]


async def office_to_pdf(file_bytes: bytes, filename: str) -> bytes:
    """
    Конвертирует DOCX/DOC/XLS/XLSX/PPT/PPTX в PDF через iLovePDF API.
    Возвращает байты PDF-файла.
    """
    if not ILOVEPDF_KEY:
        raise RuntimeError("ILOVEPDF_SECRET_KEY не задан в переменных окружения")

    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=120) as client:

        # 1. Создаём задачу officepdf
        resp = await client.get(
            f"{API_START}/start/officepdf",
            headers=headers
        )
        resp.raise_for_status()
        data        = resp.json()
        server      = data["server"]
        task_id     = data["task"]
        task_headers = {"Authorization": f"Bearer {token}"}

        base = f"https://{server}/v1"

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
        resp = await client.get(
            f"{base}/download/{task_id}",
            headers=task_headers
        )
        resp.raise_for_status()
        result_pdf = resp.content

        # 5. Удаляем задачу (вежливо чистим за собой)
        try:
            await client.delete(
                f"{base}/task/{task_id}",
                headers=task_headers
            )
        except Exception:
            pass

    return result_pdf


def is_ilovepdf_available() -> bool:
    return bool(ILOVEPDF_KEY)
