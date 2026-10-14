export function ComputeBadge({ device, ms }: { device: string; ms?: number }) {
  const amd = /AMD|MI300|Instinct|Radeon/i.test(device);
  return (
    <span className={`inline-flex items-center gap-2 rounded-sm border px-2 py-0.5 text-sm ${amd ? "border-steel/60 text-steel" : "border-rule text-ink-dim"}`}>
      {device}
      {ms != null && <span className="text-ink-dim">{ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(1)} s`}</span>}
    </span>
  );
}
