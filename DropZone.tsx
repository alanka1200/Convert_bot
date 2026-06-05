import { useRef, useState } from 'react';
import { cn } from '@/lib/utils';

interface DropZoneProps {
  accept?: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  children?: React.ReactNode;
  className?: string;
}

export function DropZone({ accept, multiple = false, onFiles, children, className }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(e.type === 'dragenter' || e.type === 'dragover');
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length) onFiles(files);
    e.target.value = '';
  };

  return (
    <div
      className={cn(
        'relative border-2 border-dashed rounded-2xl cursor-pointer transition-all duration-200 select-none',
        dragging ? 'border-primary bg-accent drag-active scale-[0.99]' : 'border-border hover:border-primary/50 hover:bg-accent/30',
        className
      )}
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input ref={inputRef} type="file" accept={accept} multiple={multiple} className="hidden" onChange={handleChange} />
      {children}
    </div>
  );
}
