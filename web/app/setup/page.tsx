"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Upload = { id: string; file: string; flags: string[]; sharpness: number; scale: unknown };
type Step = "name" | "photos" | "build" | "ready";

const STEPS: [Step, string][] = [
  ["name", "Name the product"],
  ["photos", "Add good photos"],
  ["build", "Build and stress-test"],
  ["ready", "Ready to inspect"],
];

export default function Setup() {
  const [step, setStep] = useState<Step>("name");
  const [name, setName] = useState("");
  const [sid, setSid] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    if (step !== "build" || !sid) return;
    const es = new EventSource("/api/gp/events");
    es.addEventListener("build", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (d.station !== sid) return;
      if (d.stage === "log") setLog((l) => [...l, d.msg.trim()]);
      if (d.stage === "done") setStep("ready");
      if (d.stage === "error") setError(`Build failed: ${d.error}`);
    });
    return () => es.close();
  }, [step, sid]);

  if (api.demo)
    return (
      <p className="max-w-[60ch] text-ink-dim">
        Setting up a station needs the live GPU service. In demo mode you can explore the two recorded stations on the{" "}
        <Link href="/" className="text-steel underline">Stations</Link> page.
      </p>
    );

  async function run<T>(f: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      return await f();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addFiles(files: File[]) {
    if (!sid || !files.length) return;
    const r = await run(() => api.uploadGood(sid, files));
    if (r) setUploads((u) => [...u, ...r.uploaded]);
  }

  const usable = uploads.filter((u) => !u.flags.length).length;
  const scaleFound = uploads.some((u) => u.scale);

  return (
    <div className="max-w-[900px]">
      <h1 className="font-display text-4xl font-bold">Set up a station</h1>
      <ol className="mb-8 mt-4 flex flex-wrap gap-x-6 gap-y-2 text-[15px]">
        {STEPS.map(([k, l], i) => {
          const idx = STEPS.findIndex(([s]) => s === step);
          return (
            <li key={k} className={i === idx ? "font-semibold text-ink" : i < idx ? "text-pass" : "text-ink-dim"}>
              {i + 1}. {l}
            </li>
          );
        })}
      </ol>

      {step === "name" && (
        <form className="flex max-w-[480px] flex-col gap-3"
              onSubmit={async (e) => {
                e.preventDefault();
                const r = await run(() => api.createStation(name.trim()));
                if (r) { setSid(r.id); setStep("photos"); }
              }}>
          <label className="block">
            <span className="text-[15px]">Product name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. Housing cover, black ABS"
                   className="mt-1 w-full rounded-sm border border-rule bg-housing px-3 py-2.5 text-lg" />
          </label>
          <button disabled={busy || !name.trim()} className="self-start rounded-sm bg-steel px-5 py-3 font-semibold text-tag-ink disabled:opacity-60">
            Create station
          </button>
        </form>
      )}

      {step === "photos" && (
        <div className="flex flex-col gap-5">
          <p className="max-w-[65ch] text-ink-dim">
            Add photos of good parts, taken the same way production photos will be: same camera, lighting and fixture.
            30 photos give a working station; 60 or more give a tighter false-reject guarantee and a certified review band.
            Include a printed scale marker in the frame so defects can be measured in millimetres.
          </p>
          <label onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
                 onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles([...e.dataTransfer.files]); }}
                 className={`flex min-h-48 cursor-pointer flex-col items-center justify-center border-2 border-dashed p-8 text-center ${drag ? "border-steel bg-housing" : "border-rule"}`}>
            <span className="font-display text-2xl font-semibold">{busy ? "Checking photos…" : "Drop photos here, or click to choose"}</span>
            <span className="mt-1 text-ink-dim">Each photo is checked for blur, exposure and the scale marker.</span>
            <input type="file" accept="image/*" multiple hidden onChange={(e) => addFiles([...(e.target.files ?? [])])} />
          </label>
          {uploads.length > 0 && (
            <div>
              <p className="text-[15px]">
                {usable} of {uploads.length} photos usable.{" "}
                {scaleFound ? <span className="text-pass">Scale marker found.</span> : <span className="text-hold">No scale marker found yet; sizes will be in pixels.</span>}
              </p>
              <ul className="mt-2 max-h-56 overflow-auto text-sm">
                {uploads.filter((u) => u.flags.length).map((u) => (
                  <li key={u.id} className="text-hold">{u.file}: {u.flags.join(", ")}. It will be left out.</li>
                ))}
              </ul>
            </div>
          )}
          <button disabled={busy || usable < 8} onClick={async () => { const r = await run(() => api.build(sid!)); if (r) setStep("build"); }}
                  className="self-start rounded-sm bg-steel px-5 py-3 font-semibold text-tag-ink disabled:opacity-60">
            Build station from {usable} photos
          </button>
          {usable < 8 && <p className="text-sm text-ink-dim">At least 8 usable photos are needed. With 30, false rejects are bounded near 7%; with 60, near 3.6%; with 100, near 2%.</p>}
        </div>
      )}

      {step === "build" && (
        <div>
          <p className="text-lg">Building on the GPU: extracting features, filling both memory banks, then stress-testing with synthetic defects.</p>
          <ul className="mt-4 flex flex-col gap-1 font-mono text-sm text-ink-dim">
            {log.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}

      {step === "ready" && sid && (
        <div className="flex flex-col gap-3">
          <p className="font-display text-3xl font-semibold text-pass">Station ready.</p>
          <div className="flex flex-wrap gap-3">
            <Link href={`/stations/${sid}/zones`} className="rounded-sm border border-rule px-4 py-2.5">Draw zones</Link>
            <Link href={`/stations/${sid}/calibrate`} className="rounded-sm border border-rule px-4 py-2.5">Check calibration</Link>
            <Link href={`/stations/${sid}`} className="rounded-sm bg-steel px-4 py-2.5 font-semibold text-tag-ink">Start inspecting</Link>
          </div>
        </div>
      )}
      {error && <p className="mt-4 text-stop">{error}</p>}
    </div>
  );
}
