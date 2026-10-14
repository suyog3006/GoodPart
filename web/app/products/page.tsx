"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type StationSummary } from "@/lib/api";

function pct(x: unknown) {
  if (typeof x !== "number") return "n/a";
  const v = x * 100;
  return `${Number.isInteger(+v.toFixed(1)) ? v.toFixed(0) : v.toFixed(1)}%`;
}

function StationRow({ s }: { s: StationSummary }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- meta is free-form JSON from the service
  const m = s.meta as Record<string, any>;
  const cal = m.calibration ?? {};
  const total = (s.counts.pass ?? 0) + (s.counts.review ?? 0) + (s.counts.reject ?? 0);
  return (
    <Link href={s.status === "ready" || api.demo ? `/?product=${s.id}` : `/setup?station=${s.id}`}
          className="grid grid-cols-2 gap-4 border-t border-rule px-1 py-5 hover:bg-housing sm:grid-cols-[2fr_1fr_1fr_1fr_1.4fr] sm:items-center">
      <div className="col-span-2 sm:col-span-1">
        <div className="font-display text-2xl font-semibold leading-tight">{s.name}</div>
        {m.description && <div className="text-sm text-ink">{m.description}</div>}
        <div className="text-sm text-ink-dim">
          {s.status === "ready"
            ? `${m.n_build ?? "?"} good photos in memory, ${cal.n_cal ?? "?"} for calibration`
            : s.status === "building"
              ? "Learning on the GPU…"
              : s.status === "error"
                ? "Training failed. Open to add photos and try again."
                : `Needs more good photos: ${s.n_usable ?? 0} usable saved so far`}
        </div>
      </div>
      <div>
        <div className="text-sm text-ink-dim">False rejects at most</div>
        <div className="font-display text-2xl">{pct(cal.alpha_guaranteed)}</div>
      </div>
      <div>
        <div className="text-sm text-ink-dim">Reliably catches from</div>
        <div className="font-display text-2xl">{m.a90_95_mm ? `${(+m.a90_95_mm).toFixed(1)} mm` : m.a90_95_px ? `${Math.round(+m.a90_95_px)} px` : "n/a"}</div>
      </div>
      <div>
        <div className="text-sm text-ink-dim">Drift</div>
        <div className={`font-display text-2xl ${m.drift === "drift" ? "text-stop" : m.drift === "ok" ? "text-pass" : "text-ink-dim"}`}>
          {m.drift === "drift" ? "Shifted" : m.drift === "ok" ? "Stable" : "Not enough data"}
        </div>
      </div>
      <div className="col-span-2 sm:col-span-1">
        <div className="text-sm text-ink-dim">{total} inspected</div>
        <div className="mt-1 flex h-3 w-full overflow-hidden rounded-sm bg-housing-2">
          {(["pass", "review", "reject"] as const).map((d) => (
            <div key={d} className={d === "pass" ? "bg-pass" : d === "review" ? "bg-hold" : "bg-stop"}
                 style={{ width: total ? `${((s.counts[d] ?? 0) / total) * 100}%` : 0 }} />
          ))}
        </div>
        <div className="mt-1 text-sm text-ink-dim">
          {s.counts.pass ?? 0} pass, {s.counts.review ?? 0} review, {s.counts.reject ?? 0} reject
        </div>
      </div>
    </Link>
  );
}

export default function Products() {
  const q = useQuery({ queryKey: ["stations"], queryFn: api.stations });
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl font-bold">Products</h1>
          <p className="mt-1 max-w-[65ch] text-ink-dim">
            Each product learned what a good part looks like from photos of good parts only, and is saved. Click one to
            inspect a photo of it; its history page has past inspections, the review queue and its thresholds.
          </p>
        </div>
        {!api.demo && (
          <Link href="/setup" className="rounded-sm bg-steel px-4 py-2.5 font-semibold text-tag-ink">Add a product</Link>
        )}
      </div>
      {q.isLoading && <p className="text-ink-dim">Loading products…</p>}
      {q.isError && <p className="text-stop">Could not load products: {(q.error as Error).message}</p>}
      {q.data?.length === 0 && (
        <p className="text-ink-dim">No products yet. <Link className="text-steel underline" href="/setup">Add the first one</Link> with about 30 photos of good parts.</p>
      )}
      <div className="border-b border-rule">{q.data?.map((s) => <StationRow key={s.id} s={s} />)}</div>
    </div>
  );
}
