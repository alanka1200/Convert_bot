import { HOT_CONVERSIONS } from '@/lib/formats';

interface HotActionsProps {
  onSelect: (convId: string, accepts: string) => void;
}

export function HotActions({ onSelect }: HotActionsProps) {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {HOT_CONVERSIONS.map(conv => (
        <button
          key={conv.id}
          onClick={() => onSelect(conv.id, conv.accepts)}
          className="flex flex-col items-start gap-2 rounded-2xl border border-border bg-card p-4 text-left hover:border-primary/40 hover:bg-accent/30 hover:shadow-sm transition-all duration-150 active:scale-[0.97]"
        >
          <span className="text-2xl">{conv.icon}</span>
          <div>
            <p className="text-sm font-semibold text-foreground leading-tight">{conv.label}</p>
            <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">{conv.description}</p>
          </div>
        </button>
      ))}
    </div>
  );
}
