"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Decision, type Inspection } from "@/lib/api";
import { DecisionTag } from "@/components/DecisionTag";
import { InspectionViewer } from "@/components/InspectionViewer";
import { ComputeBadge } from "@/components/ComputeBadge";
import { Camera } from "@/components/Camera";

const FILTERS: (Decision | "all")[] = ["all", "reject", "review", "pass"];

export default function Inspect() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["inspections", id], queryFn: () => api.inspections(id) });
  const [current, setCurrent] = useState<Inspection | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [camera, setCamera] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const inspect = useMutation({
    mutationFn: (f: File) => api.inspect(id, f),
    onSuccess: (r) => {
      setCurrent(r);
      qc.invalidateQueries({ queryKey: ["inspections", id] });
    },
  });

  // Live updates: defect names arrive a moment after the decision.
  useEffect(() => {
    if (api.demo) return;
    const es = new EventSource("/api/gp/events");
    es.addEventListener("named", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setCurrent((c) => (c && c.id === d.inspection ? { ...c, regions: d.regions } : c));
      qc.invalidateQueries({ queryKey: ["inspections", id] });
    });
    return () => es.close();
  }, [id, qc]);

  const shown = useMemo(
    () => (list.data ?? []).filter((i) => filter === "all" || i.decision === filter),
    [list.data, filter],
  );
  const cur = current ?? list.data?.[0] ?? null;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
      <section aria-label="Image" className="min-w-0">
        {cur ? (
          <InspectionViewer image={cur.image_url} overlay={cur.overlay_url} regions={cur.regions} />
        ) : (
          <div className="flex aspect-square items-center justify-center rounded-sm border border-dashed border-rule text-ink-dim">
            Inspect a part to see it here.
          </div>
        )}
      </section>

      <section aria-label="Decision" className="flex flex-col gap-5">
        {!api.demo && (
          <div className="flex flex-wrap gap-2">
            <button onClick={() => fileRef.current?.click()} disabled={inspect.isPending}
                    className="rounded-sm bg-steel px-4 py-3 text-lg font-semibold text-tag-ink disabled:opacity-60">
              {inspect.isPending ? "Inspecting…" : "Inspect a photo"}
            </button>
            <button onClick={() => setCamera((c) => !c)} className="rounded-sm border border-rule px-4 py-3 text-lg">
              {camera ? "Close camera" : "Use camera"}
            </button>
            <input ref={fileRef} type="file" accept="image/*" hidden
                   onChange={(e) => e.target.files?.[0] && inspect.mutate(e.target.files[0])} />
          </div>
        )}
        {camera && <Camera onCapture={(f) => inspect.mutate(f)} busy={inspect.isPending} />}
        {inspect.isError && <p className="text-stop">Inspection failed: {(inspect.error as Error).message}</p>}

        {cur && (
          <>
            <DecisionTag decision={cur.decision} stampKey={cur.id} />
            <p className="text-lg leading-snug">{cur.reason}</p>
            <div className="flex flex-wrap items-center gap-3">
              <ComputeBadge device={cur.device} ms={cur.latency_ms} />
              <span className="text-sm text-ink-dim">score {cur.score.toFixed(2)}</span>
              {cur.truth && <span className="text-sm text-ink-dim">ground truth: {cur.truth}</span>}
            </div>
            {cur.regions.length > 0 && (
              <ol className="flex flex-col gap-3">
                {cur.regions.map((r, i) => (
                  <li key={i} className={`border-l-4 bg-housing px-4 py-3 ${r.verdict === "out_of_tolerance" ? "border-stop" : "border-hold"}`}>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-display text-xl font-semibold capitalize">
                        {i + 1}. {r.name?.label ?? "naming…"}
                      </span>
                      <span className="text-sm text-ink-dim">
                        {r.length_mm != null ? `${r.length_mm.toFixed(1)} mm long` : `${Math.round(r.length_px)} px long`}
                        {r.zone ? `, ${r.zone}` : ""}
                      </span>
                    </div>
                    {r.name?.description && <p className="mt-1 text-[15px]">{r.name.description}</p>}
                    <p className="mt-1 text-sm text-ink-dim">
                      {r.reason}
                      {r.name?.source && r.name.source !== "template" && ` Named by ${r.name.model ?? r.name.source}.`}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </section>

      <section aria-label="Recent inspections" className="lg:col-span-2">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-4 font-display text-2xl font-semibold">Recent parts</h2>
          {FILTERS.map((f) => (
            <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
                    className={`rounded-sm px-3 py-1.5 text-[15px] capitalize ${filter === f ? "bg-housing-2 text-ink" : "text-ink-dim hover:text-ink"}`}>
              {f}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
          {shown.map((i) => (
            <button key={i.id} onClick={() => setCurrent(i)}
                    className={`group relative aspect-square overflow-hidden rounded-sm border-2 ${cur?.id === i.id ? "border-steel" : "border-transparent"}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={i.overlay_url} alt={`Part ${i.id}, ${i.decision}`} className="h-full w-full object-cover" loading="lazy" />
              <span className="absolute bottom-1 left-1"><DecisionTag decision={i.decision} size="sm" /></span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
