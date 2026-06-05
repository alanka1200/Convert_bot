import { useState, useEffect, useCallback } from 'react';
import { DropZone } from '@/components/DropZone';
import { FileCard } from '@/components/FileCard';
import { ConvertOptions } from '@/components/ConvertOptions';
import { HotActions } from '@/components/HotActions';
import { Button } from '@/components/ui/button';
import { getFormatsForFile, isSupported } from '@/lib/formats';
import type { ConversionId } from '@/lib/formats';
import { convertFile, mergeFiles as mergeFilesApi, isBackendConfigured, ApiError } from '@/lib/api';
import { Upload, Layers, ArrowLeft, AlertCircle, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';

declare global { interface Window { Telegram?: { WebApp?: { ready: () => void; expand: () => void; BackButton?: { show: () => void; hide: () => void; onClick: (fn: () => void) => void }; HapticFeedback?: { notificationOccurred: (t: string) => void } } } } }

type AppStage = 'home' | 'select-format' | 'converting' | 'done' | 'error';

interface FileState {
  file: File;
  status: 'idle' | 'converting' | 'done' | 'error';
  progress: number;
  error?: string;
  resultUrl?: string;
  resultName?: string;
}

function useTelegramWebApp() {
  const tg = window.Telegram?.WebApp;
  useEffect(() => {
    if (tg) { tg.ready(); tg.expand(); }
  }, [tg]);
  return tg;
}

function formatBytes(b: number) {
  if (b < 1024) return `${b} Б`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(0)} КБ`;
  return `${(b / 1024 ** 2).toFixed(1)} МБ`;
}

export default function App() {
  const tg = useTelegramWebApp();
  const [tab, setTab] = useState<'convert' | 'merge'>('convert');
  const [stage, setStage] = useState<AppStage>('home');
  const [fileState, setFileState] = useState<FileState | null>(null);
  const [mergeFileList, setMergeFileList] = useState<File[]>([]);
  const [selectedFormat, setSelectedFormat] = useState<string | null>(null);
  const [hotPreset, setHotPreset] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [mergeStatus, setMergeStatus] = useState<'idle' | 'converting' | 'done' | 'error'>('idle');
  const [mergeResult, setMergeResult] = useState<{ url: string; name: string } | null>(null);

  useEffect(() => {
    if (!tg) return;
    if (stage !== 'home' || tab !== 'convert') {
      tg.BackButton?.show();
      tg.BackButton?.onClick(() => { reset(); });
    } else {
      tg.BackButton?.hide();
    }
  }, [stage, tab, tg]);

  const reset = useCallback(() => {
    setStage('home');
    setFileState(null);
    setSelectedFormat(null);
    setHotPreset(null);
    setGlobalError(null);
  }, []);

  const handleFiles = useCallback((files: File[]) => {
    setGlobalError(null);
    const file = files[0];
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      setGlobalError(`Файл слишком большой: ${formatBytes(file.size)}. Лимит 50 МБ.`);
      return;
    }
    if (!isSupported(file.name)) {
      setGlobalError(`Формат «${file.name.split('.').pop()?.toUpperCase()}» не поддерживается.`);
      return;
    }
    setFileState({ file, status: 'idle', progress: 0 });
    setSelectedFormat(hotPreset);
    setStage('select-format');
  }, [hotPreset]);

  const handleHotSelect = (convId: string, accepts: string) => {
    setHotPreset(convId);
    setSelectedFormat(convId);
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = accepts;
    input.onchange = (e) => {
      const files = Array.from((e.target as HTMLInputElement).files || []);
      if (files.length) handleFiles(files);
    };
    input.click();
  };

  const handleConvert = async () => {
    if (!fileState || !selectedFormat) return;
    if (!isBackendConfigured()) {
      setGlobalError('Сервер не настроен. Задай VITE_BACKEND_URL перед деплоем.');
      return;
    }
    setStage('converting');
    setFileState(s => s ? { ...s, status: 'converting', progress: 0 } : s);
    try {
      const result = await convertFile(
        fileState.file,
        selectedFormat as ConversionId,
        (pct) => setFileState(s => s ? { ...s, progress: pct } : s)
      );
      const url = URL.createObjectURL(result.blob);
      setFileState(s => s ? { ...s, status: 'done', progress: 100, resultUrl: url, resultName: result.filename } : s);
      setStage('done');
      tg?.HapticFeedback?.notificationOccurred('success');
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Неизвестная ошибка';
      setFileState(s => s ? { ...s, status: 'error', error: msg } : s);
      setStage('error');
      tg?.HapticFeedback?.notificationOccurred('error');
    }
  };

  const handleMergeFiles = (files: File[]) => {
    setMergeFileList(prev => [...prev, ...files].slice(0, 10));
  };

  const handleMerge = async () => {
    if (mergeFileList.length < 2) { setGlobalError('Нужно минимум 2 файла.'); return; }
    setMergeStatus('converting');
    setGlobalError(null);
    try {
      const result = await mergeFilesApi(mergeFileList);
      setMergeResult({ url: URL.createObjectURL(result.blob), name: result.filename });
      setMergeStatus('done');
      tg?.HapticFeedback?.notificationOccurred('success');
    } catch (e) {
      setGlobalError(e instanceof ApiError ? e.message : 'Ошибка объединения');
      setMergeStatus('error');
    }
  };

  const formatOptions = fileState ? getFormatsForFile(fileState.file.name) : [];
  const backendOk = isBackendConfigured();

  return (
    <div className="min-h-screen bg-background leaf-bg">
      <div className="max-w-md mx-auto px-4 py-5 pb-24">

        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-2xl">🌿</span>
            <h1 className="text-xl font-bold tracking-tight text-foreground">FileConvert</h1>
          </div>
          <p className="text-xs text-muted-foreground ml-9">Конвертер файлов · бесплатно</p>
        </div>

        {/* Backend warning */}
        {!backendOk && (
          <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>Демо-режим. Задай <code className="font-mono bg-amber-100 px-1 rounded">VITE_BACKEND_URL</code> в GitHub Secrets перед деплоем.</span>
          </div>
        )}

        {/* Global error */}
        {globalError && (
          <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{globalError}</span>
          </div>
        )}

        {/* ── CONVERT TAB ── */}
        {tab === 'convert' && (
          <>
            {stage === 'home' && (
              <div className="space-y-5">
                <DropZone
                  accept=".pdf,.docx,.doc,.txt,.png,.jpg,.jpeg,.bmp"
                  onFiles={handleFiles}
                  className="p-8 text-center"
                >
                  <div className="flex flex-col items-center gap-3 pointer-events-none">
                    <div className="w-14 h-14 rounded-2xl bg-secondary flex items-center justify-center">
                      <Upload className="w-6 h-6 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-foreground">Загрузи файл</p>
                      <p className="text-xs text-muted-foreground mt-1">PDF, Word, TXT, PNG, JPG · до 50 МБ</p>
                    </div>
                    <span className="text-xs text-primary font-medium">нажми или перетащи</span>
                  </div>
                </DropZone>
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Популярные</p>
                  <HotActions onSelect={handleHotSelect} />
                </div>
              </div>
            )}

            {stage === 'select-format' && fileState && (
              <div className="space-y-4">
                <button onClick={reset} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-1">
                  <ArrowLeft className="w-3.5 h-3.5" /> Назад
                </button>
                <FileCard file={fileState.file} onRemove={reset} />
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Выбери формат</p>
                  <ConvertOptions options={formatOptions} selected={selectedFormat} onSelect={setSelectedFormat} />
                </div>
                <Button className="w-full h-12 text-sm font-semibold rounded-xl" disabled={!selectedFormat} onClick={handleConvert}>
                  Конвертировать →
                </Button>
              </div>
            )}

            {stage === 'converting' && fileState && (
              <div className="space-y-4">
                <div className="text-center py-4">
                  <div className="w-16 h-16 rounded-2xl bg-secondary mx-auto flex items-center justify-center mb-4">
                    <span className="text-3xl" style={{ display: 'inline-block', animation: 'spin 2s linear infinite' }}>🌿</span>
                  </div>
                  <p className="text-sm font-semibold text-foreground">Конвертируем...</p>
                  <p className="text-xs text-muted-foreground mt-1">Подожди немного</p>
                </div>
                <FileCard file={fileState.file} status="converting" progress={fileState.progress} />
              </div>
            )}

            {stage === 'done' && fileState && (
              <div className="space-y-4">
                <div className="text-center py-4">
                  <div className="w-16 h-16 rounded-2xl bg-accent mx-auto flex items-center justify-center mb-4 text-3xl">✓</div>
                  <p className="text-sm font-semibold text-foreground">Готово!</p>
                  <p className="text-xs text-muted-foreground mt-1">Файл сконвертирован успешно</p>
                </div>
                <FileCard file={fileState.file} status="done" />
                {fileState.resultUrl && (
                  <a href={fileState.resultUrl} download={fileState.resultName}
                    className="flex items-center justify-center gap-2 w-full h-12 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 transition-opacity">
                    <ExternalLink className="w-4 h-4" />
                    Скачать {fileState.resultName}
                  </a>
                )}
                <Button variant="outline" className="w-full h-10 rounded-xl text-sm" onClick={reset}>
                  Конвертировать ещё
                </Button>
              </div>
            )}

            {stage === 'error' && fileState && (
              <div className="space-y-4">
                <div className="text-center py-4">
                  <div className="w-16 h-16 rounded-2xl bg-destructive/10 mx-auto flex items-center justify-center mb-4 text-3xl">✗</div>
                  <p className="text-sm font-semibold text-foreground">Ошибка конвертации</p>
                </div>
                <FileCard file={fileState.file} status="error" errorMsg={fileState.error} />
                <Button variant="outline" className="w-full h-10 rounded-xl text-sm" onClick={reset}>Попробовать снова</Button>
              </div>
            )}
          </>
        )}

        {/* ── MERGE TAB ── */}
        {tab === 'merge' && (
          <div className="space-y-4">
            <DropZone accept=".pdf,.png,.jpg,.jpeg,.bmp" multiple onFiles={handleMergeFiles} className="p-6 text-center">
              <div className="flex flex-col items-center gap-2 pointer-events-none">
                <Layers className="w-8 h-8 text-primary" />
                <p className="text-sm font-semibold text-foreground">Добавь файлы</p>
                <p className="text-xs text-muted-foreground">PDF или изображения · до 10 файлов</p>
              </div>
            </DropZone>

            {mergeFileList.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Файлы ({mergeFileList.length})</p>
                {mergeFileList.map((f, i) => (
                  <FileCard key={`${f.name}-${i}`} file={f}
                    onRemove={() => setMergeFileList(prev => prev.filter((_, j) => j !== i))}
                    status={mergeStatus === 'done' ? 'done' : 'idle'} />
                ))}
              </div>
            )}

            {mergeStatus === 'done' && mergeResult && (
              <a href={mergeResult.url} download={mergeResult.name}
                className="flex items-center justify-center gap-2 w-full h-12 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 transition-opacity">
                <ExternalLink className="w-4 h-4" />
                Скачать merged.pdf
              </a>
            )}

            <Button className="w-full h-12 text-sm font-semibold rounded-xl"
              disabled={mergeFileList.length < 2 || mergeStatus === 'converting'}
              onClick={handleMerge}>
              {mergeStatus === 'converting' ? '⏳ Объединяем...' : `Объединить в PDF (${mergeFileList.length})`}
            </Button>

            {mergeFileList.length > 0 && (
              <Button variant="ghost" className="w-full h-8 text-xs text-muted-foreground"
                onClick={() => { setMergeFileList([]); setMergeStatus('idle'); setMergeResult(null); }}>
                Очистить список
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Bottom tab bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-background/95 backdrop-blur border-t border-border">
        <div className="max-w-md mx-auto px-4 py-3 flex gap-2">
          <button onClick={() => { setTab('convert'); reset(); }}
            className={cn('flex-1 flex flex-col items-center gap-1 rounded-xl py-2 text-xs font-medium transition-colors',
              tab === 'convert' ? 'bg-accent text-primary' : 'text-muted-foreground hover:text-foreground')}>
            <Upload className="w-4 h-4" />Конвертер
          </button>
          <button onClick={() => setTab('merge')}
            className={cn('flex-1 flex flex-col items-center gap-1 rounded-xl py-2 text-xs font-medium transition-colors',
              tab === 'merge' ? 'bg-accent text-primary' : 'text-muted-foreground hover:text-foreground')}>
            <Layers className="w-4 h-4" />Объединить
          </button>
        </div>
      </div>
    </div>
  );
}
