// ─── Format definitions ───────────────────────────────────────────────────────

export type ConversionId =
  | 'pdf-to-docx' | 'pdf-to-txt' | 'pdf-to-png' | 'pdf-compress'
  | 'img-to-pdf' | 'img-to-jpg' | 'img-to-png' | 'img-compress'
  | 'docx-to-txt' | 'txt-to-pdf'
  | 'merge-pdf' | 'merge-img';

export interface FormatOption {
  id: ConversionId;
  label: string;
  description: string;
  icon: string;
  hot?: boolean; // popular conversion
}

// What formats can each file type convert TO
export const FORMAT_ROUTES: Record<string, FormatOption[]> = {
  pdf: [
    { id: 'pdf-to-docx', label: 'PDF → Word', description: 'Сохранит текст и форматирование', icon: '📄', hot: true },
    { id: 'pdf-to-txt',  label: 'PDF → TXT',  description: 'Только текст без разметки',       icon: '🔤' },
    { id: 'pdf-to-png',  label: 'PDF → PNG',  description: 'Каждая страница — отдельный файл',icon: '🖼️', hot: true },
    { id: 'pdf-compress',label: 'Сжать PDF',  description: 'Уменьшить вес без потери качества', icon: '🗜️' },
  ],
  png: [
    { id: 'img-to-pdf', label: 'PNG → PDF',   description: 'Изображение в документ',          icon: '📄', hot: true },
    { id: 'img-to-jpg', label: 'PNG → JPG',   description: 'Меньший вес, без прозрачности',   icon: '🖼️' },
    { id: 'img-compress',label: 'Сжать PNG',  description: 'Уменьшить вес изображения',       icon: '🗜️' },
  ],
  jpg: [
    { id: 'img-to-pdf', label: 'JPG → PDF',   description: 'Изображение в документ',          icon: '📄', hot: true },
    { id: 'img-to-png', label: 'JPG → PNG',   description: 'Без сжатия, с прозрачностью',     icon: '🖼️' },
    { id: 'img-compress',label: 'Сжать JPG',  description: 'Уменьшить вес изображения',       icon: '🗜️' },
  ],
  jpeg: [
    { id: 'img-to-pdf', label: 'JPG → PDF',   description: 'Изображение в документ',          icon: '📄', hot: true },
    { id: 'img-to-png', label: 'JPG → PNG',   description: 'Без сжатия, с прозрачностью',     icon: '🖼️' },
    { id: 'img-compress',label: 'Сжать JPG',  description: 'Уменьшить вес изображения',       icon: '🗜️' },
  ],
  bmp: [
    { id: 'img-to-pdf', label: 'BMP → PDF',   description: 'Изображение в документ',          icon: '📄' },
    { id: 'img-to-png', label: 'BMP → PNG',   description: 'Современный формат',              icon: '🖼️' },
    { id: 'img-to-jpg', label: 'BMP → JPG',   description: 'Компактный формат',               icon: '🖼️' },
  ],
  docx: [
    { id: 'docx-to-txt', label: 'Word → TXT', description: 'Извлечь текст из документа',      icon: '🔤', hot: true },
  ],
  doc: [
    { id: 'docx-to-txt', label: 'DOC → TXT',  description: 'Извлечь текст из документа',      icon: '🔤' },
  ],
  txt: [
    { id: 'txt-to-pdf', label: 'TXT → PDF',   description: 'Текст оформить в документ',       icon: '📄', hot: true },
  ],
};

// Popular conversions for the home screen (before file upload)
export const HOT_CONVERSIONS = [
  { id: 'pdf-to-docx', label: 'PDF → Word',  icon: '📄', accepts: '.pdf',            description: 'Редактируй PDF как Word' },
  { id: 'img-to-pdf',  label: 'Фото → PDF',  icon: '📷', accepts: '.png,.jpg,.jpeg,.bmp', description: 'Изображение в документ' },
  { id: 'pdf-to-png',  label: 'PDF → PNG',   icon: '🖼️', accepts: '.pdf',            description: 'Страницы в картинки' },
  { id: 'pdf-compress',label: 'Сжать PDF',   icon: '🗜️', accepts: '.pdf',            description: 'Уменьши вес файла' },
  { id: 'txt-to-pdf',  label: 'TXT → PDF',   icon: '🔤', accepts: '.txt',            description: 'Текст в красивый PDF' },
  { id: 'img-compress',label: 'Сжать фото',  icon: '📦', accepts: '.png,.jpg,.jpeg', description: 'Меньше вес, то же качество' },
];

export function getExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() || '';
}

export function getFormatsForFile(filename: string): FormatOption[] {
  const ext = getExtension(filename);
  return FORMAT_ROUTES[ext] || [];
}

export function isSupported(filename: string): boolean {
  return getFormatsForFile(filename).length > 0;
}

export function getMimeType(conversionId: ConversionId): string {
  const mimeMap: Record<string, string> = {
    'pdf-to-docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'pdf-to-txt': 'text/plain',
    'pdf-to-png': 'application/zip',
    'pdf-compress': 'application/pdf',
    'img-to-pdf': 'application/pdf',
    'img-to-jpg': 'image/jpeg',
    'img-to-png': 'image/png',
    'img-compress': 'image/jpeg',
    'docx-to-txt': 'text/plain',
    'txt-to-pdf': 'application/pdf',
    'merge-pdf': 'application/pdf',
    'merge-img': 'application/pdf',
  };
  return mimeMap[conversionId] || 'application/octet-stream';
}

export function getOutputExtension(conversionId: ConversionId, inputExt?: string): string {
  const extMap: Record<string, string> = {
    'pdf-to-docx': 'docx',
    'pdf-to-txt': 'txt',
    'pdf-to-png': 'zip',
    'pdf-compress': 'pdf',
    'img-to-pdf': 'pdf',
    'img-to-jpg': 'jpg',
    'img-to-png': 'png',
    'img-compress': inputExt || 'jpg',
    'docx-to-txt': 'txt',
    'txt-to-pdf': 'pdf',
    'merge-pdf': 'pdf',
    'merge-img': 'pdf',
  };
  return extMap[conversionId] || 'bin';
}
