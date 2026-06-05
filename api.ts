// ─── API Client ───────────────────────────────────────────────────────────────
import type { ConversionId } from './formats';

const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handleResponse(resp: Response): Promise<Blob> {
  if (!resp.ok) {
    let msg = `Ошибка сервера (${resp.status})`;
    try {
      const data = await resp.json();
      msg = data.detail || msg;
    } catch (_) {}
    throw new ApiError(resp.status, msg);
  }
  return resp.blob();
}

export async function convertFile(
  file: File,
  conversionId: ConversionId,
  onProgress?: (pct: number) => void
): Promise<{ blob: Blob; filename: string }> {
  if (!BACKEND_URL) throw new ApiError(0, 'Backend URL не настроен. Добавь VITE_BACKEND_URL.');

  let tick = 0;
  const fakeProgress = setInterval(() => {
    tick = Math.min(tick + Math.random() * 15, 85);
    onProgress?.(tick);
  }, 400);

  try {
    const targetFormat = conversionId.split('-').pop() || '';
    const fd = new FormData();
    fd.append('file', file);
    fd.append('target_format', targetFormat);

    const resp = await fetch(`${BACKEND_URL}/convert`, { method: 'POST', body: fd });
    clearInterval(fakeProgress);
    onProgress?.(95);

    const blob = await handleResponse(resp);
    onProgress?.(100);

    const baseName = file.name.replace(/\.[^/.]+$/, '');
    const ext = conversionId.includes('compress')
      ? (file.name.split('.').pop() || 'bin')
      : conversionId.split('-').pop() || 'bin';

    const dispHeader = resp.headers.get('Content-Disposition');
    let filename = `${baseName}_converted.${ext}`;
    if (dispHeader) {
      const match = dispHeader.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    return { blob, filename };
  } catch (e) {
    clearInterval(fakeProgress);
    throw e;
  }
}

export async function mergeFiles(files: File[]): Promise<{ blob: Blob; filename: string }> {
  if (!BACKEND_URL) throw new ApiError(0, 'Backend URL не настроен');
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  const resp = await fetch(`${BACKEND_URL}/merge`, { method: 'POST', body: fd });
  const blob = await handleResponse(resp);
  return { blob, filename: 'merged.pdf' };
}

export function isBackendConfigured(): boolean {
  return Boolean(BACKEND_URL);
}
