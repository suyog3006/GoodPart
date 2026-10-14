"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { InspectionViewer } from "@/components/InspectionViewer";

const TYPES = ["scratch", "crack", "chip", "stain", "contamination", "missing feature", "deformation", "other"];

type Label = { label: "good" | "defect"; type?: string };

export default function Review() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["inspections", id], queryFn: () => api.inspections(id) });
  const queue = useMemo(() => (list.data ?? []).filter((i) => i.decision === "review"), [list.data]);
  const [pos, setPos] = useState(0);
  const [labels, setLabels] = useState<Record<string, Label>>({});
  const [history, setHistory] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [started] = useState(() => Date.now());
  const cur = queue[pos];

  const label = useCallback(
    async (l: Label) => {
      if (!cur) return;
      setLabels((m) => ({ ...m, [cur.id]: l }));
      setHistory((h) => [...h, cur.id]);
      setPos((p) => Math.min(p + 1, queue.length - 1));
      try {
        const r = await api.review(cur.id, l.label, l.type);
        if ("guarantee" in r && r.guarantee) setNote(`Calibration grew. ${r.guarantee}`);
        qc.invalidateQueries({ queryKey: ["station", id] });
      } catch (e) {
        setNote(`Could not save the label: ${(e as Error).message}`);
      }
    },
    [cur, queue.length, qc, id],
  );

  const undo = useCallback(() => {
    const last = history.at(-1);
    if (!last) return;
    setHistory((h) => h.slice(0, -1));
    setLabels((m) => {
      const n = { ...m };
      delete n[last];
      return n;
    });
    setPos(queue.findIndex((q) => q.id === last));
  }, [history, queue]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      if (k === "g") label({ label: "good" });
      else if (k === "d") label({ label: "defect" });
      else if (/^[1-8]$/.test(k)) label({ label: "defect", type: TYPES[+k - 1] });
      else if (k === "arrowright") setPos((p) => Math.min(p + 1, queue.length - 1));
      else if (k === "arrowleft") setPos((p) => Math.max(p - 1, 0));
      else if (k === "z") undo();
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [label, undo, queue.length]);

  const done = Object.keys(labels).length;
  const secsPer = done ? (Date.now() - started) / 1000 / done : null;

  if (list.isLoading) return <p className="text-ink-dim">Loading the queue…</p>;
  if (!queue.length) return <p className="text-ink-dim">Nothing to review. Parts the station is unsure about will appear here.</p>;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
      <InspectionViewer image={cur.image_url} overlay={cur.overlay_url} regions={cur.regions} />
      <aside className="flex flex-col gap-5">
        <div>
          <div className="font-display text-3xl font-semibold">Part {pos + 1} of {queue.length}</div>
          <div className="mt-2 h-2 w-full bg-housing-2">
            <div className="h-2 bg-steel" style={{ width: `${(done / queue.length) * 100}%` }} />
          </div>
          <p className="mt-1 text-sm text-ink-dim">
            {done} labelled{secsPer ? `, ${secsPer.toFixed(1)} s per part` : ""}
          </p>
        </div>
        <p className="text-lg leading-snug">{cur.reason}</p>
        {labels[cur.id] && (
          <p className="text-ink-dim">
            Labelled {labels[cur.id].label}{labels[cur.id].type ? ` (${labels[cur.id].type})` : ""}. Press Z to undo.
          </p>
        )}
        <div className="grid grid-cols-2 gap-2">
          <button onClick={() => label({ label: "good" })} className="rounded-sm bg-pass px-4 py-4 font-display text-2xl font-semibold text-tag-ink">
            Good <kbd className="ml-1 text-base opacity-70">G</kbd>
          </button>
          <button onClick={() => label({ label: "defect" })} className="rounded-sm bg-stop px-4 py-4 font-display text-2xl font-semibold text-tag-ink">
            Defect <kbd className="ml-1 text-base opacity-70">D</kbd>
          </button>
        </div>
        <div>
          <p className="mb-2 text-sm text-ink-dim">Or name the defect</p>
          <div className="grid grid-cols-2 gap-1.5">
            {TYPES.map((t, i) => (
              <button key={t} onClick={() => label({ label: "defect", type: t })}
                      className="flex justify-between rounded-sm bg-housing px-3 py-2 text-left capitalize hover:bg-housing-2">
                {t} <kbd className="text-ink-dim">{i + 1}</kbd>
              </button>
            ))}
          </div>
        </div>
        <p className="text-sm text-ink-dim">Arrow keys move between parts. Parts you confirm as good join the calibration set and tighten the guarantee.</p>
        {note && <p className="text-steel">{note}</p>}
        {api.demo && <p className="hatch p-2 text-sm text-hold">Demo mode: labels are not saved.</p>}
      </aside>
    </div>
  );
}
