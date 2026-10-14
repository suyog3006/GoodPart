"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, readOnly, type Zone } from "@/lib/api";

const SIZE = 768;
const ZONE_FILLS = ["var(--series-good)", "var(--series-defect)", "var(--steel)"];

export default function Zones() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["station", id], queryFn: () => api.station(id) });
  const [zones, setZones] = useState<Zone[]>([]);
  const [draft, setDraft] = useState<[number, number][]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [mm, setMm] = useState<string>("");
  const svg = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (q.data) {
      setZones(q.data.zones ?? []);
      setMm(q.data.mm_per_px ? String(q.data.mm_per_px) : "");
    }
  }, [q.data]);

  const save = useMutation({ mutationFn: () => api.saveZones(id, zones, mm ? +mm : null) });

  function point(e: React.MouseEvent): [number, number] {
    const r = svg.current!.getBoundingClientRect();
    return [Math.round(((e.clientX - r.left) / r.width) * SIZE), Math.round(((e.clientY - r.top) / r.height) * SIZE)];
  }

  function finish() {
    if (draft.length < 3) return;
    const name = `Zone ${String.fromCharCode(65 + zones.length)}`;
    setZones((z) => [...z, { name, polygon: draft, max_length_mm: 1.0, max_area_mm2: null, max_count: null }]);
    setSel(zones.length);
    setDraft([]);
  }

  function update(i: number, patch: Partial<Zone>) {
    setZones((z) => z.map((zz, j) => (j === i ? { ...zz, ...patch } : zz)));
  }

  const ref = api.demo ? `/demo/reference_${id}.jpg` : `/api/gp/stations/${id}/reference`;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0">
        <p className="mb-2 text-[15px] text-ink-dim">
          Click to place corners of a zone on the reference part, then press Enter or click the first corner to close it.
        </p>
        <div className="relative aspect-square w-full overflow-hidden border border-rule bg-black"
             onKeyDown={(e) => { if (e.key === "Enter") finish(); if (e.key === "Escape") setDraft([]); }} tabIndex={0}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={ref} alt="Reference part" className="absolute inset-0 h-full w-full object-contain" />
          <svg ref={svg} viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 h-full w-full cursor-crosshair"
               onClick={(e) => {
                 const p = point(e);
                 if (draft.length >= 3 && Math.hypot(p[0] - draft[0][0], p[1] - draft[0][1]) < 14) finish();
                 else setDraft((d) => [...d, p]);
               }}>
            {zones.map((z, i) => (
              <g key={i} onClick={(e) => { e.stopPropagation(); setSel(i); }}>
                <polygon points={z.polygon.map((p) => p.join(",")).join(" ")} fill={ZONE_FILLS[i % 3]} fillOpacity={sel === i ? 0.35 : 0.2}
                         stroke={ZONE_FILLS[i % 3]} strokeWidth={sel === i ? 4 : 2} />
                <text x={z.polygon[0][0] + 6} y={z.polygon[0][1] + 22} fill="var(--ink)" fontSize={20} fontWeight={600}>{z.name}</text>
              </g>
            ))}
            {draft.length > 0 && (
              <>
                <polyline points={draft.map((p) => p.join(",")).join(" ")} fill="none" stroke="var(--hold)" strokeWidth={3} />
                {draft.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={i === 0 ? 9 : 6} fill="var(--hold)" />)}
              </>
            )}
          </svg>
        </div>
      </div>

      <aside className="flex flex-col gap-5">
        <label className="block">
          <span className="text-[15px]">Scale (mm per pixel at 768 px)</span>
          <input value={mm} onChange={(e) => setMm(e.target.value)} inputMode="decimal" placeholder="Detected from the printed marker"
                 className="mt-1 w-full rounded-sm border border-rule bg-housing px-3 py-2" />
        </label>
        {zones.length === 0 && <p className="text-ink-dim">No zones yet. Without zones, every anomaly is judged only by its score.</p>}
        {zones.map((z, i) => (
          <fieldset key={i} onFocus={() => setSel(i)}
                    className={`border-l-4 bg-housing px-4 py-3 ${sel === i ? "border-steel" : "border-rule"}`}>
            <div className="flex items-center gap-2">
              <input value={z.name} onChange={(e) => update(i, { name: e.target.value })} aria-label="Zone name"
                     className="w-full bg-transparent font-display text-xl font-semibold" />
              <button onClick={() => setZones((zz) => zz.filter((_, j) => j !== i))} className="text-sm text-stop">Remove</button>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-sm">
              {([["max_length_mm", "Max length mm"], ["max_area_mm2", "Max area mm²"], ["max_count", "Max count"]] as const).map(([k, l]) => (
                <label key={k} className="block">
                  <span className="text-ink-dim">{l}</span>
                  <input value={z[k] ?? ""} inputMode="decimal" placeholder="any"
                         onChange={(e) => update(i, { [k]: e.target.value === "" ? null : +e.target.value })}
                         className="mt-1 w-full rounded-sm border border-rule bg-graphite px-2 py-1.5" />
                </label>
              ))}
            </div>
          </fieldset>
        ))}
        {!readOnly(id) ? (
          <button onClick={() => save.mutate()} disabled={save.isPending}
                  className="rounded-sm bg-steel px-4 py-3 text-lg font-semibold text-tag-ink disabled:opacity-60">
            {save.isPending ? "Saving…" : "Save zones"}
          </button>
        ) : (
          <p className="hatch p-2 text-sm text-hold">{api.demo ? "Demo mode: nothing is saved." : "Showcase station: zones are not saved."}</p>
        )}
        {save.isSuccess && <p className="text-pass">Zones saved. New inspections use them.</p>}
        {save.isError && <p className="text-stop">Could not save zones: {(save.error as Error).message}</p>}
      </aside>
    </div>
  );
}
