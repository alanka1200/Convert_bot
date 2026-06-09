"""
utils.py — определение типа файла и доступных форматов конвертации.
"""

import os
from typing import Optional

# Маппинг расширений → список форматов (id, icon, label)
FORMAT_MAP: dict[str, list[dict]] = {
    "pdf": [
        {"id": "docx",     "icon": "📄", "label": "PDF → Word (DOCX)"},
        {"id": "png",      "icon": "🖼",  "label": "PDF → PNG (постранично)"},
        {"id": "txt",      "icon": "🔤", "label": "PDF → TXT (извлечь текст)"},
        {"id": "compress", "icon": "🗜️", "label": "Сжать PDF"},
    ],
    "png": [
        {"id": "jpg",      "icon": "🖼",  "label": "PNG → JPG"},
        {"id": "pdf",      "icon": "📄", "label": "PNG → PDF"},
        {"id": "compress", "icon": "🗜️", "label": "Сжать PNG"},
    ],
    "jpg": [
        {"id": "png",      "icon": "🖼",  "label": "JPG → PNG"},
        {"id": "pdf",      "icon": "📄", "label": "JPG → PDF"},
        {"id": "compress", "icon": "🗜️", "label": "Сжать JPG"},
    ],
    "jpeg": [
        {"id": "png",      "icon": "🖼",  "label": "JPG → PNG"},
        {"id": "pdf",      "icon": "📄", "label": "JPG → PDF"},
        {"id": "compress", "icon": "🗜️", "label": "Сжать JPG"},
    ],
    "bmp": [
        {"id": "png",      "icon": "🖼",  "label": "BMP → PNG"},
        {"id": "jpg",      "icon": "🖼",  "label": "BMP → JPG"},
        {"id": "pdf",      "icon": "📄", "label": "BMP → PDF"},
    ],
    "docx": [
        {"id": "txt",      "icon": "🔤", "label": "Word → TXT (извлечь текст)"},
    ],
    "doc": [
        {"id": "txt",      "icon": "🔤", "label": "DOC → TXT (извлечь текст)"},
    ],
    "txt": [
        {"id": "pdf",      "icon": "📄", "label": "TXT → PDF"},
    ],
}

MIME_TO_EXT: dict[str, str] = {
    "application/pdf":                                                          "pdf",
    "image/png":                                                                "png",
    "image/jpeg":                                                               "jpg",
    "image/bmp":                                                                "bmp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword":                                                       "doc",
    "text/plain":                                                               "txt",
}

MAX_FILE_SIZE_MB = 50


def get_extension(filename: str) -> Optional[str]:
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".") if ext else None


def get_extension_from_mime(mime: str) -> Optional[str]:
    return MIME_TO_EXT.get(mime)


def detect_file_type(filename: str, content_type: Optional[str] = None) -> Optional[str]:
    ext = get_extension(filename)
    if ext and ext in FORMAT_MAP:
        return ext
    if content_type:
        ext_from_mime = get_extension_from_mime(content_type)
        if ext_from_mime and ext_from_mime in FORMAT_MAP:
            return ext_from_mime
    return None


def get_possible_formats(file_type: str) -> list[dict]:
    return FORMAT_MAP.get(file_type or "", [])


def get_output_filename(original: str, target_format: str) -> str:
    base = os.path.splitext(original)[0]
    if target_format == "compress":
        ext = get_extension(original) or "bin"
        out_ext = "pdf" if ext == "pdf" else ext
        return f"{base}_compressed.{out_ext}"
    return f"{base}.{target_format}"


def is_image_ext(ext: str) -> bool:
    return ext in ("png", "jpg", "jpeg", "bmp")
