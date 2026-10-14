"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, type PodFit } from "@/lib/api";
import { PodChart } from "@/components/PodChart";

type Extra = {
  pod_agreement?: { size_lo: number; size_hi: number; n: number; observed_real: number; predicted_synthetic: number }[];
  pod_real?: PodFit;
  gallery?: { image: string; size_px: number; contrast: number; kind: string; hit: boolean }[];
};

export default function Stress() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["station", id], queryFn: () => api.station(id) });
  const [kind, setKind] = useState<"all" | "hit" | "miss">("all");
  const st = q.data?.station;
  if (q.isLoading) return <p className="text-ink-dim">Loading the stress test…</p>;
  if (!st) return <p className="text-ink-dim">Build the station first; the stress test runs as part of the build.</p>;
  const extra = q.data as unknown as Extra;
  const mm = st.mm_per_px;
  const unit = mm ? "mm" : "px";
  const scale = mm ?? 1;
  const real = extra.pod_agreement?.map((b) => ({ size: (b.size_lo + b.size_hi) / 2, observed: b.observed_real, n: b.n }));
  const gallery = (extra.gallery ?? []).filter((g) => kind === "all" || (kind === "hit") === g.hit);

  return (
    <div className="flex flex-col gap-10">
      <section className="grid gap-8 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <p className="max-w-[60ch] text-[15px] text-ink-dim">
            Before seeing any real defect, the station painted {st.scores.synthetic.length} synthetic defects of known size and
            contrast onto held-out good parts, and checked which ones it would send to review or reject.
          </p>
          <div className="border-l-4 border-steel bg-housing px-5 py-4">
            <div className="text-sm text-ink-dim">Catches 90% of defects, with 95% confidence, from</div>
            <div className="font-display text-5xl font-bold">
              {st.pod.a90_95 ? `${(st.pod.a90_95 * scale).toFixed(1)} ${unit}` : "n/a"}
            </div>
            <div className="mt-1 text-sm text-ink-dim">
              {st.pod.a90 ? `Best estimate ${(st.pod.a90 * scale).toFixed(1)} ${unit}. ` : ""}
              Synthetic hit rate {st.pod.hit_rate != null ? `${Math.round(st.pod.hit_rate * 100)}%` : "n/a"}.
            </div>
          </div>
          {extra.pod_agreement && (
            <div>
              <h3 className="font-display text-xl font-semibold">Does it predict real defects?</h3>
              <table className="mt-2 w-full text-[15px]">
                <thead className="text-left text-sm text-ink-dim">
                  <tr><th className="py-1 font-normal">Real size ({unit})</th><th className="font-normal">n</th><th className="font-normal">Predicted</th><th className="font-normal">Observed</th></tr>
                </thead>
                <tbody>
                  {extra.pod_agreement.map((b, i) => (
                    <tr key={i} className="border-t border-rule">
                      <td className="py-1">{(b.size_lo * scale).toFixed(0)}–{(b.size_hi * scale).toFixed(0)}</td>
                      <td>{b.n}</td>
                      <td>{Math.round(b.predicted_synthetic * 100)}%</td>
                      <td>{Math.round(b.observed_real * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-sm text-ink-dim">Real VisA defects, binned by size. Where predicted and observed differ, the synthetic curve is a stress test, not a guarantee.</p>
            </div>
          )}
        </div>
        <div className="min-w-0">
          <PodChart fit={st.pod} unit={unit} scale={scale} real={real} height={400} />
        </div>
      </section>

      {extra.gallery && (
        <section>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="mr-4 font-display text-2xl font-semibold">Synthetic defects</h2>
            {(["all", "hit", "miss"] as const).map((k) => (
              <button key={k} onClick={() => setKind(k)} aria-pressed={kind === k}
                      className={`rounded-sm px-3 py-1.5 text-[15px] ${kind === k ? "bg-housing-2" : "text-ink-dim hover:text-ink"}`}>
                {k === "all" ? "All" : k === "hit" ? "Caught" : "Missed"}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-9">
            {gallery.map((g, i) => (
              <figure key={i} className="relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={g.image} alt={`${g.kind}, ${g.size_px.toFixed(0)} px, ${g.hit ? "caught" : "missed"}`}
                     className={`aspect-square w-full border-2 object-cover ${g.hit ? "border-pass" : "border-stop"}`} loading="lazy" />
                <figcaption className="mt-0.5 text-xs text-ink-dim">
                  {g.hit ? "✓" : "✕"} {g.kind}, {(g.size_px * scale).toFixed(1)} {unit}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
