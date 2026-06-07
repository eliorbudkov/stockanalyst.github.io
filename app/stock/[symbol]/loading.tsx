export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="h-24 animate-pulse rounded-2xl border border-border bg-panel/50" />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="h-[520px] animate-pulse rounded-2xl border border-border bg-panel/50 lg:col-span-2" />
        <div className="h-[520px] animate-pulse rounded-2xl border border-border bg-panel/50" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="h-48 animate-pulse rounded-2xl border border-border bg-panel/50" />
        <div className="h-48 animate-pulse rounded-2xl border border-border bg-panel/50" />
      </div>
    </div>
  );
}
