"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type SavedPhoto } from "@/lib/api";

type Step = "name" | "photos" | "build" | "ready";

const STEPS: [Step, string][] = [
  ["name", "Name the product"],
  ["photos", "Add good photos"],
  ["build", "Build and stress-test"],
  ["ready", "Ready to inspect"],
];

// Photos are sent a few at a time: serverless hosting rejects requests over 4.5 MB, and each batch
// is saved on the server as soon as it arrives, so an interrupted upload loses nothing.
const BATCH = 3;

function Setup() {
  const router = useRouter();
  const params = useSearchParams();
  const resumeId = params.get("station");
  const [step, setStep] = useState<Step>(resumeId ? "photos" : "name");
  const [name, setName] = useState("");
  const [sid, setSid] = useState<string | null>(resumeId);
  const [saved, setSaved] = useState<SavedPhoto[]>([]);
  const [wasReady, setWasReady] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [drag, setDrag] = useState(false);

  // Resume: load the station and the photos already saved for it.
  useEffect(() => {
    if (!resumeId || api.demo) return;
    (async () => {
      try {
        const [st, imgs] = await Promise.all([api.station(resumeId), api.listGood(resumeId)]);
        setName(st.name);
        setSaved(imgs.images);
        setWasReady(st.status === "ready");
        if (st.status === "building") setStep("build");
      } catch (e) {
        setError(`Could not load this station: ${(e as Error).message}`);
      }
    })();
  }, [resumeId]);

  useEffect(() => {
    if (step !== "build" || !sid) return;
    const es = new EventSource("/api/gp/events");
    es.addEventListener("build", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      if (d.station !== sid) return;
      if (d.stage === "log") setLog((l) => [...l, d.msg.trim()]);
    });
    // Streaming connections can be cut by the host, so also poll the station status.
    const t = setInterval(async () => {
      try {
        const st = await api.station(sid);
        if (st.status === "ready") setStep("ready");
        if (st.status === "error") setError(`Build failed: ${(st.meta as { error?: string }).error ?? "unknown error"}`);
      } catch {}
    }, 3000);
    return () => {
      es.close();
      clearInterval(t);
    };
  }, [step, sid]);

  if (api.demo)
    return (
      <p className="max-w-[60ch] text-ink-dim">
        Setting up a station needs the live GPU service, which is switched off right now. You can explore the recorded
        stations on the <Link href="/" className="text-steel underline">Stations</Link> page.
      </p>
    );

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.createStation(name.trim());
      setSid(r.id);
      router.replace(`/setup?station=${r.id}`);
      setStep("photos");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addFiles(files: File[]) {
    if (!sid || !files.length) return;
    setBusy(true);
    setError(null);
    setProgress({ done: 0, total: files.length });
    const bad: string[] = [];
    for (let i = 0; i < files.length; i += BATCH) {
      const chunk = files.slice(i, i + BATCH);
      try {
        const r = await api.uploadGood(sid, chunk);
        r.uploaded.filter((u) => u.flags.length).forEach((u) => bad.push(`${u.file}: ${u.flags.join(", ")}`));
        setSaved((s) => [...s, ...r.uploaded.flatMap((u) => (u.id ? [{ id: u.id, flags: u.flags, sharpness: u.sharpness, scale: u.scale }] : []))]);
      } catch (e) {
        chunk.forEach((f) => bad.push(`${f.name}: not uploaded (${(e as Error).message})`));
      }
      setProgress({ done: Math.min(i + BATCH, files.length), total: files.length });
    }
    setSkipped((s) => [...s, ...bad]);
    setBusy(false);
  }

  async function build() {
    if (!sid) return;
    setBusy(true);
    setError(null);
    try {
      await api.build(sid);
      setLog([]);
      setStep("build");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const usable = saved.filter((u) => !u.flags.length).length;
  const scaleFound = saved.some((u) => u.scale);
  const idx = STEPS.findIndex(([s]) => s === step);

  return (
    <div className="max-w-[900px]">
      <h1 className="font-display text-4xl font-bold">{resumeId && name ? name : "Set up a station"}</h1>
      <ol className="mb-8 mt-4 flex flex-wrap gap-x-6 gap-y-2 text-[15px]">
        {STEPS.map(([k, l], i) => (
          <li key={k} className={i === idx ? "font-semibold text-ink" : i < idx ? "text-pass" : "text-ink-dim"}>
            {i + 1}. {l}
          </li>
        ))}
      </ol>

      {step === "name" && (
        <form className="flex max-w-[480px] flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create(); }}>
          <label className="block">
            <span className="text-[15px]">Product name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. Housing cover, black ABS"
                   className="mt-1 w-full rounded-sm border border-rule bg-housing px-3 py-2.5 text-lg" />
          </label>
          <button disabled={busy || !name.trim()} className="self-start rounded-sm bg-steel px-5 py-3 font-semibold text-tag-ink disabled:opacity-60">
            Create station
          </button>
          <p className="text-sm text-ink-dim">
            Stations are saved with their photos and trained memory. To add photos to an existing product, open it from
            the <Link href="/" className="text-steel underline">Stations</Link> page instead.
          </p>
        </form>
      )}

      {step === "photos" && (
        <div className="flex flex-col gap-5">
          <p className="max-w-[65ch] text-ink-dim">
            {saved.length
              ? `${saved.length} photos are already saved for this product. Add more, or build with what is here.`
              : "Add photos of good parts, taken the same way production photos will be: same camera, lighting and fixture."}{" "}
            30 photos give a working station; 60 or more give a tighter false-reject guarantee and a certified review band.
            Include the <a href="/scale-marker.png" download className="text-steel underline">printed scale marker</a>{" "}
            (print at 100%; the black square is 20 mm) in the frame so defects can be measured in millimetres.
          </p>
          <label onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
                 onDrop={(e) => { e.preventDefault(); setDrag(false); if (!busy) addFiles([...e.dataTransfer.files]); }}
                 className={`flex min-h-44 cursor-pointer flex-col items-center justify-center border-2 border-dashed p-8 text-center ${drag ? "border-steel bg-housing" : "border-rule"}`}>
            <span className="font-display text-2xl font-semibold">
              {progress && busy ? `Uploading ${progress.done} of ${progress.total}…` : "Drop photos here, or click to choose"}
            </span>
            <span className="mt-1 text-ink-dim">Each photo is saved and checked for blur, exposure and the scale marker.</span>
            <input type="file" accept="image/*" multiple hidden disabled={busy}
                   onChange={(e) => { addFiles([...(e.target.files ?? [])]); e.target.value = ""; }} />
          </label>
          {progress && busy && (
            <div className="h-2 w-full bg-housing-2">
              <div className="h-2 bg-steel" style={{ width: `${(progress.done / progress.total) * 100}%` }} />
            </div>
          )}
          {saved.length > 0 && (
            <div>
              <p className="text-[15px]">
                {usable} of {saved.length} saved photos are usable.{" "}
                {scaleFound ? <span className="text-pass">Scale marker found.</span> : <span className="text-hold">No scale marker found yet; sizes will be in pixels.</span>}
              </p>
              <div className="mt-2 flex max-h-40 flex-wrap gap-1 overflow-auto">
                {saved.map((p) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img key={p.id} src={`/api/gp/stations/${sid}/images/${p.id}`} alt={p.flags.length ? `Left out: ${p.flags.join(", ")}` : "Saved good photo"}
                       className={`h-14 w-14 border object-cover ${p.flags.length ? "border-hold opacity-50" : "border-rule"}`} loading="lazy" />
                ))}
              </div>
              {skipped.length > 0 && (
                <ul className="mt-2 max-h-40 overflow-auto text-sm text-hold">
                  {skipped.map((m, i) => <li key={i}>{m}. It will be left out.</li>)}
                </ul>
              )}
            </div>
          )}
          <button disabled={busy || usable < 8} onClick={build}
                  className="self-start rounded-sm bg-steel px-5 py-3 font-semibold text-tag-ink disabled:opacity-60">
            {wasReady ? `Rebuild station from ${usable} photos` : `Build station from ${usable} photos`}
          </button>
          {usable < 8 && <p className="text-sm text-ink-dim">At least 8 usable photos are needed. With 30, false rejects are bounded near 7%; with 60, near 3.6%; with 100, near 2%.</p>}
          {wasReady && sid && (
            <Link href={`/stations/${sid}`} className="text-[15px] text-steel underline">Keep the current station and start inspecting</Link>
          )}
        </div>
      )}

      {step === "build" && (
        <div>
          <p className="text-lg">Building on the GPU: extracting features, filling both memory banks, then stress-testing with synthetic defects. This takes about a minute.</p>
          <ul className="mt-4 flex flex-col gap-1 font-mono text-sm text-ink-dim">
            {log.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </div>
      )}

      {step === "ready" && sid && (
        <div className="flex flex-col gap-3">
          <p className="font-display text-3xl font-semibold text-pass">Station ready and saved.</p>
          <p className="text-ink-dim">It stays on the Stations page; you will not need to upload these photos again.</p>
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

export default function SetupPage() {
  return (
    <Suspense fallback={<p className="text-ink-dim">Loading…</p>}>
      <Setup />
    </Suspense>
  );
}
