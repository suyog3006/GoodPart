"use client";
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Series = { key: string; label: string; scores: number[]; color: string };

// Share of each group per score bin, so groups of different size are comparable.
function bins(series: Series[], n = 36, clipHigh?: number) {
  const all = series.flatMap((s) => s.scores).filter(Number.isFinite).sort((a, b) => a - b);
  const lo = all[0] ?? 0;
  const hi = clipHigh ?? all[Math.floor(all.length * 0.99)] ?? 1;
  const w = (hi - lo) / n || 1;
  return Array.from({ length: n }, (_, i) => {
    const a = lo + i * w;
    const row: Record<string, number> = { x: +(a + w / 2).toFixed(2) };
    for (const s of series) {
      const c = s.scores.filter((v) => (i === n - 1 ? v >= a : v >= a && v < a + w)).length;
      row[s.key] = s.scores.length ? c / s.scores.length : 0;
    }
    return row;
  });
}

export function ScoreHistogram({ series, tLow, tHigh, height = 300 }: {
  series: Series[]; tLow: number; tHigh: number; height?: number;
}) {
  const data = bins(series, 36, Number.isFinite(tHigh) ? Math.max(tHigh * 1.6, tHigh + 6) : undefined);
  const axis = { stroke: "var(--ink-dim)", fontSize: 13 };
  return (
    <div style={{ height }} role="img" aria-label="Distribution of anomaly scores with the pass and reject thresholds">
      <ResponsiveContainer>
        <BarChart data={data} barGap={2} barCategoryGap={2} margin={{ top: 28, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke="var(--rule)" strokeOpacity={0.5} vertical={false} />
          <XAxis dataKey="x" tick={axis} tickLine={false} axisLine={{ stroke: "var(--rule)" }}
                 label={{ value: "Anomaly score (robust z)", position: "insideBottom", offset: -10, fill: "var(--ink-dim)", fontSize: 13 }} />
          <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={44} />
          <Tooltip cursor={{ fill: "var(--housing-2)" }}
                   contentStyle={{ background: "var(--housing)", border: "1px solid var(--rule)", color: "var(--ink)" }}
                   formatter={(v: number, k: string) => [`${(v * 100).toFixed(1)}%`, series.find((s) => s.key === k)?.label ?? k]}
                   labelFormatter={(x) => `score ≈ ${x}`} />
          <Legend verticalAlign="top" align="left" wrapperStyle={{ top: 0, color: "var(--ink)", fontSize: 14 }}
                  formatter={(k) => <span style={{ color: "var(--ink)" }}>{series.find((s) => s.key === k)?.label}</span>} />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} fill={s.color} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          ))}
          <ReferenceLine x={nearest(data, tLow)} stroke="var(--pass)" strokeWidth={2}
                         label={{ value: "Pass below", position: "insideTopLeft", fill: "var(--ink)", fontSize: 13 }} />
          {Number.isFinite(tHigh) && (
            <ReferenceLine x={nearest(data, tHigh)} stroke="var(--stop)" strokeWidth={2}
                           label={{ value: "Reject above", position: "insideTopRight", fill: "var(--ink)", fontSize: 13 }} />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function nearest(data: Record<string, number>[], v: number) {
  return data.reduce((b, d) => (Math.abs(d.x - v) < Math.abs(b.x - v) ? d : b), data[0])?.x;
}
