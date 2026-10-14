"use client";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { PodFit } from "@/lib/api";

// Probability of detection against defect size (log x), with the one-sided 95% lower band
// and, when available, observed real-defect hit rates per size bin.
export function PodChart({ fit, unit, scale = 1, real, height = 340 }: {
  fit: PodFit; unit: string; scale?: number;
  real?: { size: number; observed: number; n: number }[]; height?: number;
}) {
  const data = fit.curve.size.map((s, i) => ({
    size: +(s * scale).toFixed(3), pod: fit.curve.pod[i], lower: fit.curve.lower95[i],
    band: [fit.curve.lower95[i], fit.curve.pod[i]] as [number, number],
  }));
  const axis = { stroke: "var(--ink-dim)", fontSize: 13 };
  const a9095 = fit.a90_95 ? fit.a90_95 * scale : null;
  return (
    <div style={{ height }} role="img" aria-label="Probability of detection by defect size">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 28, right: 16, bottom: 20, left: 0 }}>
          <CartesianGrid stroke="var(--rule)" strokeOpacity={0.5} />
          <XAxis dataKey="size" type="number" scale="log" domain={["dataMin", "dataMax"]} tick={axis}
                 tickFormatter={(v) => (v < 10 ? (+v).toFixed(1) : Math.round(v).toString())} allowDuplicatedCategory={false}
                 label={{ value: `Defect size, equivalent diameter (${unit})`, position: "insideBottom", offset: -12, fill: "var(--ink-dim)", fontSize: 13 }} />
          <YAxis domain={[0, 1]} tick={axis} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={46} />
          <Tooltip contentStyle={{ background: "var(--housing)", border: "1px solid var(--rule)", color: "var(--ink)" }}
                   formatter={(v: number | [number, number], k: string) =>
                     Array.isArray(v) ? [`${(v[0] * 100).toFixed(0)}% (95% lower bound)`, "Confidence band"] :
                       [`${(v * 100).toFixed(0)}%`, k === "pod" ? "Detection probability" : k === "observed" ? "Real defects caught" : k]}
                   labelFormatter={(x) => `${(+x).toFixed(1)} ${unit}`} />
          <Legend verticalAlign="top" align="left" wrapperStyle={{ top: 0, fontSize: 14 }}
                  formatter={(k) => <span style={{ color: "var(--ink)" }}>{k === "pod" ? "Synthetic defects (fitted)" : k === "band" ? "95% lower bound" : "Real defects (observed)"}</span>} />
          <Area dataKey="band" stroke="none" fill="var(--series-good)" fillOpacity={0.22} isAnimationActive={false} />
          <Line dataKey="pod" stroke="var(--series-good)" strokeWidth={2} dot={false} isAnimationActive={false} />
          {real && real.length > 0 && (
            <Scatter data={real.map((r) => ({ size: r.size * scale, observed: r.observed }))} dataKey="observed"
                     fill="var(--series-defect)" stroke="var(--housing)" strokeWidth={2} isAnimationActive={false} />
          )}
          <ReferenceLine y={0.9} stroke="var(--ink-dim)" strokeDasharray="4 4"
                         label={{ value: "90%", position: "insideLeft", fill: "var(--ink-dim)", fontSize: 12 }} />
          {a9095 && (
            <ReferenceLine x={a9095} stroke="var(--ink)" strokeWidth={2}
                           label={{ value: `a90/95 = ${a9095.toFixed(1)} ${unit}`, position: "insideTopLeft", fill: "var(--ink)", fontSize: 13 }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
