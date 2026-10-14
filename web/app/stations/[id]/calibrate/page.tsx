"use client";
import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, readOnly, conformal, learnThenTest } from "@/lib/api";
import { ScoreHistogram } from "@/components/ScoreHistogram";

const pct = (x: number) => `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`;

export default function Calibrate() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["station", id], queryFn: () => api.station(id) });
  const st = q.data?.station;
  const [alpha, setAlpha] = useState<number | null>(null);
  const [cap, setCap] = useState<number | null>(null);
  const a = alpha ?? st?.calibration.alpha_target ?? 0.01;
  const c = cap ?? st?.calibration.review_cap ?? 0.15;

  // Instant preview with the same maths as the server; "Apply" makes it the station's setting.
  const preview = useMemo(() => {
    if (!st) return null;
    const cal = st.scores.calibration;
    const n = cal.length;
    const aG = Math.max(a, 1 / (n + 1));
    const tHigh = conformal(cal, aG);
    const { tLow, certified } = learnThenTest(cal, tHigh, c, 0.1, st.scores.synthetic);
    const review = cal.filter((s) => s >= tLow && s <= tHigh).length / n;
    const synthMiss = st.scores.synthetic.filter((s) => s < tLow).length / st.scores.synthetic.length;
    return { n, aG, tHigh, tLow, certified, review, synthMiss, needed: Math.ceil(1 / a - 1) };
  }, [st, a, c]);

  const apply = useMutation({
    mutationFn: () => api.calibrate(id, a, c),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["station", id] }),
  });

  if (q.isLoading) return <p className="text-ink-dim">Loading calibration…</p>;
  if (!st || !preview) return <p className="text-ink-dim">This product has not been trained yet.</p>;

  return (
    <div className="grid gap-10 lg:grid-cols-[360px_minmax(0,1fr)]">
      <div className="flex flex-col gap-7">
        <div>
          <label className="block">
            <span className="flex justify-between text-[15px]"><span>Target false-reject rate</span><b>{pct(a)}</b></span>
            <input type="range" min={0.005} max={0.1} step={0.005} value={a}
                   onChange={(e) => setAlpha(+e.target.value)} className="mt-2 w-full accent-[var(--steel)]" />
          </label>
          <p className="mt-1 text-sm text-ink-dim">
            Guaranteeing {pct(a)} needs at least {preview.needed} calibration parts; this product has {preview.n}.
          </p>
        </div>
        <div>
          <label className="block">
            <span className="flex justify-between text-[15px]"><span>Most good parts sent to review</span><b>{pct(c)}</b></span>
            <input type="range" min={0.02} max={0.4} step={0.01} value={c}
                   onChange={(e) => setCap(+e.target.value)} className="mt-2 w-full accent-[var(--steel)]" />
          </label>
        </div>

        <div className="border-l-4 border-steel bg-housing px-5 py-4">
          <p className="font-display text-2xl font-semibold leading-snug">
            With {preview.n} calibration parts, false rejects stay at or below {pct(preview.aG)}.
          </p>
          <p className="mt-2 text-[15px] text-ink-dim">
            {preview.certified
              ? `With 90% confidence, no more than ${pct(c)} of good parts go to an inspector (${pct(preview.review)} on calibration parts).`
              : `The review cap of ${pct(c)} cannot be certified with this calibration set; raise it or add confirmed good parts.`}
          </p>
          <p className="mt-2 text-[15px] text-ink-dim">
            Synthetic defects passed without review: {pct(preview.synthMiss)}. Real-defect miss rates are on the Evaluation page.
          </p>
          <p className="mt-2 text-sm text-ink-dim">
            Holds while production looks like the calibration parts. The drift guard pauses it when that changes.
          </p>
        </div>

        {!readOnly(id) ? (
          <button onClick={() => apply.mutate()} disabled={apply.isPending}
                  className="rounded-sm bg-steel px-4 py-3 text-lg font-semibold text-tag-ink disabled:opacity-60">
            {apply.isPending ? "Applying…" : "Apply thresholds"}
          </button>
        ) : (
          <p className="hatch p-2 text-sm text-hold">{api.demo ? "Demo mode: nothing is saved." : "Showcase product: thresholds preview only."}</p>
        )}
        {apply.isSuccess && <p className="text-pass">Thresholds applied to this product.</p>}
      </div>

      <div className="min-w-0">
        <h2 className="font-display text-2xl font-semibold">Where good parts and synthetic defects score</h2>
        <p className="mb-2 text-[15px] text-ink-dim">
          Pass below {preview.tLow.toFixed(2)}, reject above {Number.isFinite(preview.tHigh) ? preview.tHigh.toFixed(2) : "∞"}, review in between.
        </p>
        <ScoreHistogram tLow={preview.tLow} tHigh={preview.tHigh} series={[
          { key: "good", label: "Good calibration parts", scores: st.scores.calibration, color: "var(--series-good)" },
          { key: "synth", label: "Synthetic defects", scores: st.scores.synthetic, color: "var(--series-defect)" },
        ]} height={380} />
      </div>
    </div>
  );
}
