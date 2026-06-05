import type { FormatOption } from '@/lib/formats';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';

interface ConvertOptionsProps {
  options: FormatOption[];
  selected: string | null;
  onSelect: (id: string) => void;
}

export function ConvertOptions({ options, selected, onSelect }: ConvertOptionsProps) {
  if (!options.length) return null;

  return (
    <div className="space-y-2">
      {options.map(opt => (
        <button
          key={opt.id}
          onClick={() => onSelect(opt.id)}
          className={cn(
            'w-full flex items-center gap-3 rounded-xl border p-3.5 text-left transition-all duration-150 hover:border-primary/50 hover:bg-accent/30',
            selected === opt.id
              ? 'border-primary bg-accent/60 shadow-sm'
              : 'border-border bg-card'
          )}
        >
          <span className="text-xl leading-none">{opt.icon}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">{opt.label}</span>
              {opt.hot && (
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 bg-primary/10 text-primary border-0">
                  popular
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{opt.description}</p>
          </div>
          <div className={cn(
            'shrink-0 w-4 h-4 rounded-full border-2 transition-colors',
            selected === opt.id ? 'border-primary bg-primary' : 'border-border'
          )} />
        </button>
      ))}
    </div>
  );
}
