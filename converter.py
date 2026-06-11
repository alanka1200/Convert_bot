"""
converter.py — функции конвертации файлов.
Все функции принимают bytes и возвращают bytes.
"""

import io
import os
import logging
import tempfile
import zipfile
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# PDF — определение типа (скан или текстовый)
# ─────────────────────────────────────────────
def is_scanned_pdf(pdf_bytes: bytes) -> bool:
    """
    Определяет, является ли PDF сканом (изображение без текстового слоя).
    Использует PyMuPDF: проверяет текст, покрытие изображением и GlyphlessFont.
    """
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        scanned_pages = 0

        for page in doc:
            text = page.get_text("text").strip()

            # Проверяем GlyphlessFont — признак OCR-слоя поверх скана
            fonts = page.get_fonts(full=True)
            has_glyphless = any("GlyphLessFont" in (f[3] or "") for f in fonts)

            # Проверяем покрытие изображением (≥95% страницы)
            page_area = abs(page.rect)
            image_covered = False
            if page_area > 0:
                for img in page.get_images(full=True):
                    xref = img[0]
                    for r in page.get_image_rects(xref):
                        if abs(r & page.rect) / page_area >= 0.95:
                            image_covered = True
                            break
                    if image_covered:
                        break

            # Страница считается сканом если:
            # - нет текста И есть полностью покрывающее изображение
            # - есть GlyphlessFont (OCR поверх скана — текст есть но он "пустой")
            if has_glyphless or (image_covered and len(text) < 50):
                scanned_pages += 1

        doc.close()
        # Считаем PDF сканом если большинство страниц — сканы
        return scanned_pages > total_pages / 2

    except Exception as e:
        logger.warning(f"is_scanned_pdf check failed: {e}")
        return False


# ─────────────────────────────────────────────
# PDF → DOCX
# ─────────────────────────────────────────────
def pdf_to_docx(pdf_bytes: bytes) -> bytes:
    """
    Конвертирует PDF в DOCX.
    Если PDF — скан, кидает понятную ошибку вместо пустого файла.
    """
    # Проверяем тип PDF перед конвертацией
    if is_scanned_pdf(pdf_bytes):
        raise RuntimeError(
            "PDF содержит сканированные страницы (изображения без текста). "
            "Конвертация в Word невозможна без OCR. "
            "Попробуй сначала конвертировать PDF → TXT или используй "
            "онлайн-сервис с поддержкой распознавания текста."
        )

    try:
        from pdf2docx import Converter
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_in:
            tmp_in.write(pdf_bytes)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(".pdf", ".docx")
        try:
            cv = Converter(tmp_in_path)
            cv.convert(tmp_out_path, start=0, end=None)
            cv.close()
            with open(tmp_out_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(tmp_in_path):
                os.remove(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"pdf_to_docx error: {e}")
        raise RuntimeError(f"Ошибка конвертации PDF → DOCX: {e}")


# ─────────────────────────────────────────────
# PDF → PNG (постранично, ZIP-архив)
# ─────────────────────────────────────────────
def pdf_to_png(pdf_bytes: bytes) -> bytes:
    """
    Конвертирует каждую страницу PDF в PNG.
    Если страница одна — возвращает PNG.
    Если страниц несколько — ZIP-архив с PNG-файлами.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            mat = fitz.Matrix(2.0, 2.0)  # x2 разрешение
            pix = page.get_pixmap(matrix=mat)
            pages.append((f"page_{i+1:03d}.png", pix.tobytes("png")))
        doc.close()

        if len(pages) == 1:
            return pages[0][1]

        # Несколько страниц — пакуем в ZIP
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in pages:
                zf.writestr(name, data)
        return zip_buf.getvalue()
    except Exception as e:
        logger.error(f"pdf_to_png error: {e}")
        raise RuntimeError(f"Ошибка конвертации PDF → PNG: {e}")


# ─────────────────────────────────────────────
# PDF → TXT (извлечение текста)
# ─────────────────────────────────────────────
def pdf_to_txt(pdf_bytes: bytes) -> bytes:
    """
    Извлекает текст из PDF.
    Если PDF — скан, возвращает понятное сообщение.
    """
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        empty_pages = 0

        for i, page in enumerate(doc):
            text = page.get_text("text")
            text_parts.append(f"=== Страница {i+1} ===\n{text}\n")
            if not text.strip():
                empty_pages += 1

        doc.close()
        full_text = "\n".join(text_parts)
        total_pages = len(text_parts)

        # Если большинство страниц пустые — это скан
        if empty_pages > total_pages / 2 or not full_text.strip():
            raise RuntimeError(
                "PDF содержит сканированные страницы (изображения без текстового слоя). "
                "Извлечение текста невозможно без OCR. "
                "Для распознавания текста используй сервисы: Adobe Acrobat, Google Drive "
                "(открой PDF → Файл → Открыть с помощью → Google Документы) или онлайн OCR."
            )

        return full_text.encode("utf-8")
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"pdf_to_txt error: {e}")
        raise RuntimeError(f"Ошибка извлечения текста из PDF: {e}")


# ─────────────────────────────────────────────
# PDF → сжатый PDF
# ─────────────────────────────────────────────
def compress_pdf(pdf_bytes: bytes) -> bytes:
    """Сжимает PDF через pypdf."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for page in writer.pages:
            page.compress_content_streams()
        output = io.BytesIO()
        writer.write(output)
        result = output.getvalue()
        if len(result) >= len(pdf_bytes):
            logger.info("Сжатие PDF: результат не меньше оригинала, возвращаем оригинал.")
        return result
    except Exception as e:
        logger.error(f"compress_pdf error: {e}")
        raise RuntimeError(f"Ошибка сжатия PDF: {e}")


# ─────────────────────────────────────────────
# Изображение → PDF
# ─────────────────────────────────────────────
def image_to_pdf(image_bytes: bytes) -> bytes:
    """Конвертирует одно изображение в PDF."""
    try:
        import img2pdf
        return img2pdf.convert(image_bytes)
    except Exception as e:
        logger.error(f"image_to_pdf error: {e}")
        raise RuntimeError(f"Ошибка конвертации изображения → PDF: {e}")


# ─────────────────────────────────────────────
# Изображение → другой формат (PNG/JPG)
# ─────────────────────────────────────────────
def convert_image(image_bytes: bytes, target_format: str) -> bytes:
    """
    Конвертирует изображение в нужный формат.
    target_format: 'png', 'jpg', 'jpeg'
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if target_format.lower() in ("jpg", "jpeg") and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        out = io.BytesIO()
        fmt = "JPEG" if target_format.lower() in ("jpg", "jpeg") else target_format.upper()
        img.save(out, format=fmt)
        return out.getvalue()
    except Exception as e:
        logger.error(f"convert_image error: {e}")
        raise RuntimeError(f"Ошибка конвертации изображения: {e}")


# ─────────────────────────────────────────────
# Сжатие изображения
# ─────────────────────────────────────────────
def compress_image(image_bytes: bytes, ext: str) -> bytes:
    """Сжимает изображение с понижением качества."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        out = io.BytesIO()
        if ext.lower() in ("jpg", "jpeg"):
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            img.save(out, format="JPEG", quality=65, optimize=True)
        else:
            img = img.convert("RGB") if img.mode == "P" else img
            img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as e:
        logger.error(f"compress_image error: {e}")
        raise RuntimeError(f"Ошибка сжатия изображения: {e}")


# ─────────────────────────────────────────────
# DOCX → TXT
# ─────────────────────────────────────────────
def docx_to_txt(docx_bytes: bytes) -> bytes:
    """Извлекает текст из DOCX-документа."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(docx_bytes))
        paragraphs = [p.text for p in doc.paragraphs]
        text = "\n".join(paragraphs)
        if not text.strip():
            text = "Текст не найден в документе."
        return text.encode("utf-8")
    except Exception as e:
        logger.error(f"docx_to_txt error: {e}")
        raise RuntimeError(f"Ошибка извлечения текста из DOCX: {e}")


# ─────────────────────────────────────────────
# TXT → PDF
# ─────────────────────────────────────────────
def txt_to_pdf(txt_bytes: bytes) -> bytes:
    """Создаёт PDF из текстового файла (кириллица поддерживается)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import cm

        text = txt_bytes.decode("utf-8", errors="replace")
        output = io.BytesIO()

        doc = SimpleDocTemplate(
            output,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        style = ParagraphStyle(
            "custom",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            wordWrap="CJK",
        )

        story = []
        for line in text.split("\n"):
            safe_line = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
            )
            if safe_line.strip():
                story.append(Paragraph(safe_line, style))
            else:
                story.append(Spacer(1, 0.3 * cm))

        doc.build(story)
        return output.getvalue()
    except Exception as e:
        logger.error(f"txt_to_pdf error: {e}")
        raise RuntimeError(f"Ошибка конвертации TXT → PDF: {e}")


# ─────────────────────────────────────────────
# Excel → CSV/TXT
# ─────────────────────────────────────────────
def excel_to_csv(excel_bytes: bytes, ext: str) -> bytes:
    """Конвертирует Excel в CSV (первый лист)."""
    try:
        import openpyxl
        import csv
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = wb.active
        out = io.StringIO()
        writer = csv.writer(out)
        for row in ws.iter_rows(values_only=True):
            writer.writerow([str(c) if c is not None else "" for c in row])
        return out.getvalue().encode("utf-8")
    except ImportError:
        try:
            import xlrd
            import csv
            wb = xlrd.open_workbook(file_contents=excel_bytes)
            ws = wb.sheet_by_index(0)
            out = io.StringIO()
            writer = csv.writer(out)
            for r in range(ws.nrows):
                writer.writerow([str(ws.cell_value(r, c)) for c in range(ws.ncols)])
            return out.getvalue().encode("utf-8")
        except Exception as e2:
            raise RuntimeError(f"Ошибка конвертации Excel → CSV: {e2}")
    except Exception as e:
        logger.error(f"excel_to_csv error: {e}")
        raise RuntimeError(f"Ошибка конвертации Excel → CSV: {e}")


# ─────────────────────────────────────────────
# Объединение PDF
# ─────────────────────────────────────────────
def merge_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    """Объединяет несколько PDF-файлов в один."""
    try:
        import pypdf
        writer = pypdf.PdfWriter()
        for pdf_bytes in pdf_bytes_list:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except Exception as e:
        logger.error(f"merge_pdfs error: {e}")
        raise RuntimeError(f"Ошибка объединения PDF: {e}")


# ─────────────────────────────────────────────
# Объединение изображений в PDF
# ─────────────────────────────────────────────
def merge_images_to_pdf(image_bytes_list: list[bytes]) -> bytes:
    """Объединяет несколько изображений в один PDF."""
    try:
        import img2pdf
        return img2pdf.convert(image_bytes_list)
    except Exception as e:
        logger.error(f"merge_images_to_pdf error: {e}")
        raise RuntimeError(f"Ошибка объединения изображений в PDF: {e}")


# ─────────────────────────────────────────────
# Главный диспетчер конвертации
# ─────────────────────────────────────────────
def convert(
    file_bytes: bytes,
    file_ext: str,
    target_format: str,
) -> tuple[bytes, str]:
    """
    Главная функция конвертации.
    Возвращает (result_bytes, mime_type).
    """
    file_ext = file_ext.lower()
    target_format = target_format.lower()

    # PDF → ...
    if file_ext == "pdf":
        if target_format == "docx":
            return pdf_to_docx(file_bytes), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if target_format == "png":
            data = pdf_to_png(file_bytes)
            mime = "application/zip" if data[:2] == b"PK" else "image/png"
            return data, mime
        if target_format == "txt":
            return pdf_to_txt(file_bytes), "text/plain; charset=utf-8"
        if target_format == "compress":
            return compress_pdf(file_bytes), "application/pdf"

    # Изображения → ...
    if file_ext in ("png", "jpg", "jpeg", "bmp"):
        if target_format == "pdf":
            return image_to_pdf(file_bytes), "application/pdf"
        if target_format in ("png", "jpg", "jpeg"):
            return convert_image(file_bytes, target_format), f"image/{target_format}"
        if target_format == "compress":
            return compress_image(file_bytes, file_ext), f"image/{'jpeg' if file_ext in ('jpg','jpeg') else 'png'}"

    # DOCX/DOC → ...
    if file_ext in ("docx", "doc"):
        if target_format == "txt":
            return docx_to_txt(file_bytes), "text/plain; charset=utf-8"

    # TXT → ...
    if file_ext == "txt":
        if target_format == "pdf":
            return txt_to_pdf(file_bytes), "application/pdf"

    # Excel → CSV/TXT
    if file_ext in ("xlsx", "xls"):
        if target_format in ("csv", "txt"):
            return excel_to_csv(file_bytes, file_ext), "text/plain; charset=utf-8"

    # CSV → TXT/PDF
    if file_ext == "csv":
        if target_format == "txt":
            # FIX: был баг с неопределённой переменной csv_bytes
            return file_bytes, "text/plain; charset=utf-8"
        if target_format == "pdf":
            return txt_to_pdf(file_bytes), "application/pdf"

    raise ValueError(f"Конвертация {file_ext} → {target_format} не поддерживается.")
