import { cn } from '@/lib/cn';

export function Card({
  children,
  className,
  title,
  hint,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
  hint?: string;
}) {
  return (
    <section
      className={cn(
        'rounded-xl border border-border bg-panel/70 shadow-card backdrop-blur sm:rounded-2xl',
        className,
      )}
    >
      {(title || hint) && (
        <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border px-3 py-2.5 sm:px-5 sm:py-3">
          {title && <h2 className="text-sm font-semibold tracking-wide">{title}</h2>}
          {hint && <span className="text-[11px] text-muted sm:text-xs">{hint}</span>}
        </header>
      )}
      <div className="p-3 sm:p-5">{children}</div>
    </section>
  );
}
