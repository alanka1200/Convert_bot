import { X, FileText, Image, File } from 'lucide-react';
import { cn } from '@/lib/utils';

interface FileCardProps {
  file: File;
  onRemove?: () => void;
  status?: 'idle' | 'converting' | 'done' | 'error';
  progress?: number;
  errorMsg?: string;
  className?: string;
}

function FileIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase();
  if (['pdf', 'docx', 'doc', 'txt'].includes(ext || '')) return <FileText className="w-5 h-5 text-primary" />;
  if (['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'].includes(ext || '')) return <Image className="w-5 h-5 text-primary" />;
  return <File className="w-5 h-5 text-muted-foreground" />;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

export function FileCard({ file, onRemove, status = 'idle', progress = 0, errorMsg, className }: FileCardProps) {
  return (
    <div className={cn(
      'file-enter flex items-center gap-3 rounded-xl border bg-card p-3 shadow-sm transition-all',
      status === 'error' && 'border-destructive/40 bg-destructive/5',
      status === 'done' && 'border-primary/40 bg-accent/30',
      className
    )}>
      <div className="shrink-0 w-9 h-9 rounded-lg bg-secondary flex items-center justify-center">
        <FileIcon name={file.name} />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate text-foreground">{file.name}</p>
        <p className="text-xs text-muted-foreground mt-0.5">{formatBytes(file.size)}</p>

        {status === 'converting' && (
          <div className="mt-2 h-1 bg-border rounded-full overflow-hidden relative progress-shimmer">
            <div
              className="h-full bg-primary rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
        {status === 'done' && (
          <p className="text-xs text-primary mt-1 font-medium">✓ Готово</p>
        )}
        {status === 'error' && (
          <p className="text-xs text-destructive mt-1">{errorMsg || 'Ошибка конвертации'}</p>
        )}
      </div>

      {onRemove && status === 'idle' && (
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center hover:bg-secondary transition-colors"
        >
          <X className="w-3.5 h-3.5 text-muted-foreground" />
        </button>
      )}
    </div>
  );
}
