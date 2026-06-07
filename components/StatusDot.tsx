export type Status = 'good' | 'bad' | 'neutral';

export function StatusDot({ status }: { status: Status }) {
  const color =
    status === 'good' ? 'bg-good shadow-[0_0_8px_rgba(61,220,151,0.6)]'
    : status === 'bad' ? 'bg-bad shadow-[0_0_8px_rgba(255,107,129,0.6)]'
    : 'bg-muted/40';
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} aria-hidden />;
}
