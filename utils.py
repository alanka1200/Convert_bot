"""
utils.py — определение типа файла и доступных форматов конвертации.
"""

import mimetypes
import os
from typing import Optional

# Маппинг расширений → список доступных выходных форматов
FORMAT_MAP: dict[str, list[dict]] = {
    "pdf": [
        {"id": "docx",     "label": "📄 В DOCX (Word)"},
        {"id": "png",      "label": "🖼️ В PNG (постранично)"},
        {"id": "txt",      "label": "📝 Извлечь текст (TXT)"},
        {"id": "compress", "label": "🗜️ Сжать PDF"},
    ],
    "png": [
        {"id": "jpg",      "label": "🖼️ В JPG"},
        {"id": "pdf",      "label": "📄 В PDF"},
        {"id": "compress", "label": "🗜️ Сжать изображение"},
    ],
    "jpg": [
        {"id": "png",      "label": "🖼️ В PNG"},
        {"id": "pdf",      "label": "📄 В PDF"},
        {"id": "compress", "label": "🗜️ Сжать изображение"},
    ],
    "jpeg": [
        {"id": "png",      "label": "🖼️ В PNG"},
        {"id": "pdf",      "label": "📄 В PDF"},
        {"id": "compress", "label": "🗜️ Сжать изображение"},
    ],
    "bmp": [
        {"id": "png",      "label": "🖼️ В PNG"},
        {"id": "jpg",      "label": "🖼️ В JPG"},
        {"id": "pdf",      "label": "📄 В PDF"},
    ],
    "docx": [
        {"id": "txt",      "label": "📝 Извлечь текст (TXT)"},
    ],
    "txt": [
        {"id": "pdf",      "label": "📄 В PDF"},
    ],
}

# MIME-типы → расширение
MIME_TO_EXT: dict[str, str] = {
    "application/pdf":                                                      "pdf",
    "image/png":                                                            "png",
    "image/jpeg":                                                           "jpg",
    "image/bmp":                                                            "bmp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword":                                                   "docx",
    "text/plain":                                                           "txt",
}

MAX_FILE_SIZE_MB = 50


def get_extension(filename: str) -> Optional[str]:
    """Возвращает расширение файла в нижнем регистре без точки."""
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".") if ext else None


def get_extension_from_mime(mime: str) -> Optional[str]:
    """Определяет расширение по MIME-типу."""
    return MIME_TO_EXT.get(mime)


def detect_file_type(filename: str, content_type: Optional[str] = None) -> Optional[str]:
    """
    Определяет тип файла по расширению, затем по MIME.
    Возвращает расширение (строку) или None если неизвестный тип.
    """
    ext = get_extension(filename)
    if ext and ext in FORMAT_MAP:
        return ext

    if content_type:
        ext_from_mime = get_extension_from_mime(content_type)
        if ext_from_mime and ext_from_mime in FORMAT_MAP:
            return ext_from_mime

    return None


def get_possible_formats(file_type: str) -> list[dict]:
    """Возвращает список доступных форматов конвертации для данного типа файла."""
    return FORMAT_MAP.get(file_type, [])


def get_output_filename(original: str, target_format: str) -> str:
    """Генерирует имя выходного файла."""
    base = os.path.splitext(original)[0]
    # Для PNG постраничного — используем zip
    if target_format == "png_pages":
        return f"{base}_pages.zip"
    if target_format == "compress":
        # Определим расширение по оригиналу
        ext = get_extension(original) or "bin"
        output_ext = "pdf" if ext == "pdf" else ext
        return f"{base}_compressed.{output_ext}"
    if target_format == "merge":
        return "merged.pdf"
    return f"{base}.{target_format}"


def is_image_ext(ext: str) -> bool:
    return ext in ("png", "jpg", "jpeg", "bmp")
