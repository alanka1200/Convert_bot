"""
utils.py — определение типа файла и доступных форматов конвертации.
"""

import os
from typing import Optional

# Маппинг расширений → список форматов (id, icon, label)
FORMAT_MAP: dict[str, list[dict]] = {
    # ── PDF ───────────────────────────────────────────────────────────────────
    "pdf": [
        {"id": "docx",     "icon": "📝", "label": "PDF → Word (DOCX)"},
        {"id": "png",      "icon": "🖼",  "label": "PDF → PNG (картинки)"},
        {"id": "txt",      "icon": "🔤", "label": "PDF → TXT (текст)"},
        {"id": "compress", "icon": "🗜️", "label": "Сжать PDF"},
    ],
    # ── Word ──────────────────────────────────────────────────────────────────
    "docx": [
        {"id": "pdf",      "icon": "📄", "label": "Word → PDF"},
        {"id": "txt",      "icon": "🔤", "label": "Word → TXT (текст)"},
    ],
    "doc": [
        {"id": "pdf",      "icon": "📄", "label": "Word → PDF"},
        {"id": "txt",      "icon": "🔤", "label": "Word → TXT (текст)"},
    ],
    # ── Excel ─────────────────────────────────────────────────────────────────
    "xlsx": [
        {"id": "pdf",      "icon": "📄", "label": "Excel → PDF"},
        {"id": "csv",      "icon": "📊", "label": "Excel → CSV"},
        {"id": "txt",      "icon": "🔤", "label": "Excel → TXT"},
    ],
    "xls": [
        {"id": "pdf",      "icon": "📄", "label": "Excel → PDF"},
        {"id": "csv",      "icon": "📊", "label": "Excel → CSV"},
        {"id": "txt",      "icon": "🔤", "label": "Excel → TXT"},
    ],
    # ── PowerPoint ────────────────────────────────────────────────────────────
    "pptx": [
        {"id": "pdf",      "icon": "📄", "label": "PowerPoint → PDF"},
        {"id": "png",      "icon": "🖼",  "label": "PowerPoint → PNG (слайды)"},
    ],
    "ppt": [
        {"id": "pdf",      "icon": "📄", "label": "PowerPoint → PDF"},
        {"id": "png",      "icon": "🖼",  "label": "PowerPoint → PNG (слайды)"},
    ],
    # ── Изображения ───────────────────────────────────────────────────────────
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
    # ── Текст / данные ────────────────────────────────────────────────────────
    "txt": [
        {"id": "pdf",      "icon": "📄", "label": "TXT → PDF"},
    ],
    "csv": [
        {"id": "pdf",      "icon": "📄", "label": "CSV → PDF"},
        {"id": "txt",      "icon": "🔤", "label": "CSV → TXT"},
    ],
}

MIME_TO_EXT: dict[str, str] = {
    "application/pdf":                                                              "pdf",
    "image/png":                                                                    "png",
    "image/jpeg":                                                                   "jpg",
    "image/bmp":                                                                    "bmp",
    # Word
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":     "docx",
    "application/msword":                                                           "doc",
    # Excel
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":           "xlsx",
    "application/vnd.ms-excel":                                                     "xls",
    # PowerPoint
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":   "pptx",
    "application/vnd.ms-powerpoint":                                                "ppt",
    # Text/data
    "text/plain":                                                                   "txt",
    "text/csv":                                                                     "csv",
    "application/csv":                                                              "csv",
}

MAX_FILE_SIZE_MB = 50

# Форматы которые конвертируются через iLovePDF API
ILOVEPDF_FORMATS = {"docx", "doc", "xlsx", "xls", "pptx", "ppt"}


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
    if target_format == "png":
        # Может быть ZIP если многостраничный PDF
        return f"{base}.png"
    return f"{base}.{target_format}"


def is_image_ext(ext: str) -> bool:
    return ext in ("png", "jpg", "jpeg", "bmp")


def needs_ilovepdf(file_type: str) -> bool:
    """Возвращает True если конвертация требует iLovePDF API."""
    return file_type in ILOVEPDF_FORMATS
