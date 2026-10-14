"use client";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, binomCdf } from "@/lib/api";

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- rows mirror results CSV columns
type Row = Record<string, any>;
const pct = (x: unknown, d = 1) => (typeof x === "number" && Number.isFinite(x) ? `${(x * 100).toFixed(d)}%` : "n/a");
const num = (x: unknown, d = 3) => (typeof x === "number" && Number.isFinite(x) ? x.toFixed(d) : "n/a");
const tip = { background: "var(--housing)", border: "1px solid var(--rule)", color: "var(--ink)" };
const axis = { stroke: "var(--ink-dim)", fontSize: 13 };

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-rule pt-6">
      <h2 className="font-display text-3xl font-semibold">{title}</h2>
      {note && <p className="mt-1 max-w-[75ch] text-[15px] text-ink-dim">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function Evaluation() {
  const q = useQuery({ queryKey: ["eval"], queryFn: api.evaluation });
  const [k, setK] = useState<"few" | "full">("full");
  const rows = useMemo(() => {
    const r = (q.data?.results ?? []) as Row[];
    const byCat: Record<string, Row[]> = {};
    r.forEach((x) => (byCat[x.category] ??= []).push(x));
    return Object.values(byCat).map((v) => (k === "few" ? v.reduce((a, b) => (a.k_build < b.k_build ? a : b)) : v.reduce((a, b) => (a.k_build > b.k_build ? a : b))));
  }, [q.data, k]);

  if (q.isLoading) return <p className="text-ink-dim">Loading results…</p>;
  if (q.isError || !q.data) return <p className="text-stop">Evaluation results are not bundled with this build yet.</p>;
  const d = q.data;
  const mean = (key: string) => rows.reduce((s, r) => s + (+r[key] || 0), 0) / Math.max(1, rows.length);
  const sum = (key: string) => rows.reduce((s, r) => s + (+r[key] || 0), 0);

  const methods = ["Golden-template difference", "Zero-shot VLM", "PatchCore, default threshold", "GoodPart, single threshold", "GoodPart (pass / review / reject)"];
  const baseAgg = methods.map((m) => {
    if (m === "Zero-shot VLM") {
      const z = d.zeroshot as Row[];
      if (!z.length) return null;
      const n = z.reduce((s, r) => s + r.n, 0);
      return { method: `Zero-shot ${z[0].model}`, auroc: z.reduce((s, r) => s + r.auroc * r.n, 0) / n,
               false_reject_rate: z.reduce((s, r) => s + r.false_reject_rate * r.n, 0) / n,
               miss_rate: z.reduce((s, r) => s + r.miss_rate * r.n, 0) / n, review_share: 0 };
    }
    const b = (d.baselines as Row[]).filter((x) => x.method === m && rows.some((r) => r.category === x.category && r.k_build === x.k_build));
    if (!b.length) return null;
    const avg = (key: string) => b.reduce((s, r) => s + (+r[key] || 0), 0) / b.length;
    return { method: m, auroc: avg("auroc"), false_reject_rate: avg("false_reject_rate"), miss_rate: avg("miss_rate"), review_share: avg("review_share") };
  }).filter(Boolean) as Row[];

  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="font-display text-4xl font-bold">Evaluation on VisA</h1>
        <p className="mt-1 max-w-[75ch] text-ink-dim">
          All 12 VisA categories, every official test image. Thresholds were set on good calibration parts and synthetic
          defects only; test images never touched them. Every number comes from <code>results/*.csv</code>.
        </p>
        <div className="mt-4 flex gap-2">
          {(["full", "few"] as const).map((v) => (
            <button key={v} onClick={() => setK(v)} aria-pressed={k === v}
                    className={`rounded-sm px-3 py-1.5 ${k === v ? "bg-housing-2" : "text-ink-dim hover:text-ink"}`}>
              {v === "full" ? "Full station (all good photos)" : "Few-shot station (32 photos)"}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
        {[
          ["Mean image AUROC", num(mean("auroc"))],
          ["Mean AUPRO", num(mean("aupro"))],
          ["Defects passed without review, all categories pooled", pct(sum("miss_k") / sum("n_test_bad"))],
          ["Good parts rejected, all categories pooled", pct(sum("false_reject_k") / sum("n_test_good"))],
        ].map(([l, v]) => (
          <div key={l}>
            <div className="font-display text-5xl font-bold">{v}</div>
            <div className="text-[15px] text-ink-dim">{l}</div>
          </div>
        ))}
      </div>

      <Section title="Per category" note="Miss rate counts defects that passed without review; bounds are exact one-sided 95% Clopper–Pearson. The false-reject guarantee is 1% for every station.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-[15px]">
            <thead className="text-left text-sm text-ink-dim">
              <tr>
                {["Category", "Photos", "Detectors", "AUROC A / B / station", "AUPRO", "Missed (≤ bound)", "False rejects (≤ bound)", "Review share", "a90/95"].map((h) => (
                  <th key={h} className="py-2 pr-3 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.category} className="border-t border-rule">
                  <td className="py-2 pr-3 font-semibold">{r.category}</td>
                  <td className="pr-3">{r.k_build}</td>
                  <td className="pr-3">{r.station}</td>
                  <td className="pr-3">{num(r.auroc_A)} / {num(r.auroc_B)} / <b>{num(r.auroc)}</b></td>
                  <td className="pr-3">{num(r.aupro)}</td>
                  <td className="pr-3">{pct(r.miss_rate, 0)} (≤ {pct(r.miss_upper95, 0)})</td>
                  <td className={`pr-3 ${1 - binomCdf(r.false_reject_k - 1, r.n_test_good, r.alpha_guaranteed) < 0.05 ? "text-hold" : ""}`}>
                    {pct(r.false_reject_rate, 0)} (≤ {pct(r.false_reject_upper95, 0)})
                  </td>
                  <td className="pr-3">{pct(r.review_share, 0)}</td>
                  <td className="pr-3">{r.a90_95_px ? `${Math.round(r.a90_95_px)} px` : "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm text-ink-dim">
          False-reject rates in yellow exceed the 1% guarantee by more than chance explains (binomial test, p &lt; 0.05).
          The guarantee assumes test parts look like calibration parts; on these categories the VisA test split differs
          from the training split, which is exactly the shift the drift guard is meant to catch.
        </p>
      </Section>

      <Section title="Against the baselines" note="Averaged over the categories above, at the same guaranteed false-reject target where a threshold is involved.">
        <table className="w-full max-w-[900px] text-[15px]">
          <thead className="text-left text-sm text-ink-dim">
            <tr>{["Method", "AUROC", "Missed", "False rejects", "Review share"].map((h) => <th key={h} className="py-2 pr-3 font-normal">{h}</th>)}</tr>
          </thead>
          <tbody>
            {baseAgg.map((b) => (
              <tr key={b.method} className={`border-t border-rule ${String(b.method).startsWith("GoodPart (") ? "font-semibold" : ""}`}>
                <td className="py-2 pr-3">{b.method}</td>
                <td className="pr-3">{num(b.auroc)}</td>
                <td className="pr-3">{pct(b.miss_rate)}</td>
                <td className="pr-3">{pct(b.false_reject_rate)}</td>
                <td className="pr-3">{b.review_share ? pct(b.review_share, 0) : "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {d.fewshot?.length > 0 && (
        <Section title="How many good photos are enough" note="Mean image AUROC over categories as the build set grows. Calibration parts stay fixed.">
          <div style={{ height: 320 }} className="max-w-[900px]">
            <ResponsiveContainer>
              <LineChart data={d.fewshot} margin={{ top: 28, right: 16, bottom: 20, left: 0 }}>
                <CartesianGrid stroke="var(--rule)" strokeOpacity={0.5} />
                <XAxis dataKey="k" tick={axis} label={{ value: "Good photos in the memory banks", position: "insideBottom", offset: -12, fill: "var(--ink-dim)", fontSize: 13 }} />
                <YAxis domain={[(lo: number) => Math.floor(lo * 20) / 20, 1]} tick={axis} width={46} tickFormatter={(v) => v.toFixed(2)} />
                <Tooltip contentStyle={tip} formatter={(v: number) => v.toFixed(3)} />
                <Legend verticalAlign="top" align="left" wrapperStyle={{ top: 0, fontSize: 14 }} />
                <Line dataKey="A" name="Detector A (DINOv2)" stroke="var(--series-good)" strokeWidth={2} dot={{ r: 4 }} />
                <Line dataKey="B" name="Detector B (PatchCore)" stroke="var(--series-defect)" strokeWidth={2} dot={{ r: 4 }} />
                <Line dataKey="AB" name="Combined" stroke="var(--ink)" strokeWidth={2} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Section>
      )}

      {d.benchmark && (
        <Section title="What the AMD GPU buys" note={`Same code on the AMD Instinct MI300X and on the droplet's CPU. Cost at $${d.benchmark.gpu_hour_usd}/GPU-hour.`}>
          <table className="w-full max-w-[900px] text-[15px]">
            <thead className="text-left text-sm text-ink-dim">
              <tr>{["Device", "Build (both detectors)", "Inspection, batch 32", "p95 latency, single part", "Stress test", "Cost per 1,000 parts"].map((h) => <th key={h} className="py-2 pr-3 font-normal">{h}</th>)}</tr>
            </thead>
            <tbody>
              {d.benchmark.rows.map((r) => (
                <tr key={String(r.device)} className="border-t border-rule">
                  <td className="py-2 pr-3 font-semibold">{r.device}</td>
                  <td className="pr-3">{(+r.build_A_s + +r.build_B_s).toFixed(1)} s</td>
                  <td className="pr-3">{(+r.img_per_s_bs32).toFixed(1)} img/s</td>
                  <td className="pr-3">{(+r.batch_latency_ms_bs1_p95).toFixed(0)} ms</td>
                  <td className="pr-3">{(+r.stress_img_per_s).toFixed(1)} img/s</td>
                  <td className="pr-3">{r.usd_per_1000_inspections ? `$${(+r.usd_per_1000_inspections).toFixed(4)}` : "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ height: 240 }} className="mt-6 max-w-[700px]">
            <ResponsiveContainer>
              <BarChart data={d.benchmark.rows.map((r) => ({ device: r.device, v: +r.img_per_s_bs32 }))} layout="vertical" margin={{ left: 20, right: 30 }}>
                <CartesianGrid stroke="var(--rule)" strokeOpacity={0.5} horizontal={false} />
                <XAxis type="number" tick={axis} label={{ value: "Inspections per second (batch 32)", position: "insideBottom", offset: -4, fill: "var(--ink-dim)", fontSize: 13 }} />
                <YAxis type="category" dataKey="device" tick={axis} width={200} />
                <Tooltip contentStyle={tip} formatter={(v: number) => `${v.toFixed(1)} img/s`} />
                <Bar dataKey="v" fill="var(--series-good)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Section>
      )}

      {d.failures?.length > 0 && (
        <Section title="Where it fails" note="Real defects that passed without review, and good parts rejected, on the full stations.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {d.failures.map((f, i) => (
              <figure key={i}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={f.overlay} alt={`${f.category}: ${f.kind}`} className="aspect-square w-full border border-rule object-cover" loading="lazy" />
                <figcaption className="mt-1 text-sm">
                  <span className={f.kind === "missed defect" ? "text-stop" : "text-hold"}>{f.kind}</span>
                  <span className="text-ink-dim">, {f.category}, score {f.score.toFixed(2)}</span>
                </figcaption>
              </figure>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
