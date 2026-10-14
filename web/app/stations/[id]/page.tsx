"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Decision, type Inspection } from "@/lib/api";
import { useInspect } from "@/lib/useInspect";
import { DecisionTag } from "@/components/DecisionTag";
import { InspectionViewer } from "@/components/InspectionViewer";
import { InspectionResult } from "@/components/InspectionResult";
import { Camera } from "@/components/Camera";

type Sample = { src: string; truth: "good" | "defective"; source: string };

const FILTERS: (Decision | "all")[] = ["all", "reject", "review", "pass"];

function q_name(id: string) {
  return id.startsWith("visa-") ? `what a good ${id.slice(5).replace(/\d+$/, "")} looks like` : "what this product looks like";
}

export default function Inspect() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["inspections", id], queryFn: () => api.inspections(id) });
  const { result, setResult, inspect: run, pending } = useInspect(id);
  const [picked, setPicked] = useState<Inspection | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [camera, setCamera] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [sampleTruth, setSampleTruth] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const samples = useQuery({
    queryKey: ["samples"],
    queryFn: async () => ((await (await fetch("/samples/samples.json")).json()) as Record<string, Sample[]>),
  });
  const inspect = { isPending: pending };
  const current = picked ?? result;

  function send(f: File, truth: string | null = null) {
    setSampleTruth(truth);
    setPicked(null);
    run(f);
  }

  async function sendSample(sm: Sample) {
    const blob = await (await fetch(sm.src)).blob();
    send(new File([blob], "sample.jpg", { type: "image/jpeg" }), sm.truth);
  }

  // Live updates: defect names arrive a moment after the decision.
  useEffect(() => {
    if (api.demo) return;
    const es = new EventSource("/api/gp/events");
    es.addEventListener("named", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setResult((c) => (c && c.id === d.inspection ? { ...c, regions: d.regions } : c));
      qc.invalidateQueries({ queryKey: ["inspections", id] });
    });
    return () => es.close();
  }, [id, qc, setResult]);

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
        {api.demo ? (
          <p className="hatch border border-hold/50 p-3 text-[15px] text-hold">
            The GPU service is switched off right now, so you are seeing recorded results from the AMD MI300X.
            Uploading your own photos works while it is running.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <label
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) send(f); }}
              className={`flex cursor-pointer flex-col items-center justify-center border-2 border-dashed px-4 py-6 text-center ${drag ? "border-steel bg-housing" : "border-rule hover:border-steel"}`}>
              <span className="font-display text-2xl font-semibold">
                {inspect.isPending ? "Inspecting on the AMD GPU…" : "Drop a photo of a part, or choose one"}
              </span>
              <span className="mt-1 text-sm text-ink-dim">
                This product knows {q_name(id)}. Photos of other objects will be rejected as unusual.
                Uploaded photos are kept in this product&apos;s history.
              </span>
              <input ref={fileRef} type="file" accept="image/*" hidden disabled={inspect.isPending}
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ""; }} />
            </label>
            {samples.data?.[id] && (
              <div>
                <p className="mb-1.5 text-sm text-ink-dim">No part at hand? Inspect one of these photos it has never seen:</p>
                <div className="flex gap-2">
                  {samples.data[id].map((sm) => (
                    <button key={sm.src} onClick={() => sendSample(sm)} disabled={inspect.isPending}
                            className="h-16 w-16 overflow-hidden rounded-sm border border-rule hover:border-steel disabled:opacity-50">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={sm.src} alt="Sample part photo" className="h-full w-full object-cover" />
                    </button>
                  ))}
                </div>
              </div>
            )}
            <button onClick={() => setCamera((c) => !c)} className="self-start rounded-sm border border-rule px-3 py-2 text-[15px]">
              {camera ? "Close camera" : "Use the camera instead"}
            </button>
          </div>
        )}
        {camera && <Camera onCapture={(f) => send(f)} busy={inspect.isPending} />}
        {cur && (
          <InspectionResult r={cur} note={current && current.id === cur.id && sampleTruth ? `This sample photo is known to be ${sampleTruth}.` : null} />
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
            <button key={i.id} onClick={() => { setPicked(i); setSampleTruth(null); }}
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
