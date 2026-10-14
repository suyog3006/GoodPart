"use client";
import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, type StationSummary } from "@/lib/api";
import { useInspect } from "@/lib/useInspect";
import { InspectionViewer } from "@/components/InspectionViewer";
import { InspectionResult } from "@/components/InspectionResult";
import { PhotoDrop } from "@/components/PhotoDrop";
import { Camera } from "@/components/Camera";

type Sample = { src: string; truth: "good" | "defective"; source: string };
const REMEMBER = "goodpart.product";
const ADD_NEW = "__add__";

function remembered(): string | null {
  try {
    return localStorage.getItem(REMEMBER);
  } catch {
    return null;
  }
}

function remember(id: string) {
  try {
    localStorage.setItem(REMEMBER, id);
  } catch {}
}

function summary(p: StationSummary) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- meta is free-form JSON from the service
  const m = p.meta as Record<string, any>;
  const a = m.calibration?.alpha_guaranteed;
  const parts = [`learned from ${m.n_build ?? "?"} good photos`];
  if (typeof a === "number") parts.push(`good parts wrongly rejected at most ${(a * 100).toFixed(a < 0.1 ? 1 : 0)}% of the time`);
  return parts.join(", ");
}

function Inspect() {
  const router = useRouter();
  const params = useSearchParams();
  const products = useQuery({ queryKey: ["stations"], queryFn: api.stations });
  const samples = useQuery({
    queryKey: ["samples"],
    queryFn: async () => ((await (await fetch("/samples/samples.json")).json()) as Record<string, Sample[]>),
  });
  const ready = useMemo(() => (products.data ?? []).filter((p) => p.status === "ready"), [products.data]);
  const learning = useMemo(() => (products.data ?? []).filter((p) => p.status !== "ready"), [products.data]);

  const [selected, setSelected] = useState<string | null>(null);
  // Choose: the product in the link, else the last one used on this device, else the first ready one.
  useEffect(() => {
    if (!products.data) return;
    const fromLink = params.get("product");
    if (selected && (!fromLink || fromLink === selected)) return;
    const all = products.data.map((p) => p.id);
    const want = [params.get("product"), remembered(), ready[0]?.id].find((x) => x && all.includes(x));
    if (want) setSelected(want);
  }, [products.data, params, ready, selected]);

  // Remember the product however it was chosen (dropdown, link or a product page button).
  useEffect(() => {
    if (selected) remember(selected);
  }, [selected]);

  const product = products.data?.find((p) => p.id === selected) ?? null;
  const { result, setResult, inspect, pending, error } = useInspect(product?.status === "ready" ? product.id : null);
  const [camera, setCamera] = useState(false);
  const [sampleTruth, setSampleTruth] = useState<string | null>(null);

  function choose(id: string) {
    if (id === ADD_NEW) return router.push("/setup");
    setSelected(id);
    setResult(null);
    setSampleTruth(null);
    router.replace(`/?product=${id}`, { scroll: false });
  }

  function send(f: File, truth: string | null = null) {
    setSampleTruth(truth);
    inspect(f);
  }

  async function sendSample(sm: Sample) {
    const blob = await (await fetch(sm.src)).blob();
    send(new File([blob], "sample.jpg", { type: "image/jpeg" }), sm.truth);
  }

  // "Candle (VisA sample)" -> "Candle" for use inside sentences.
  const productName = (product?.name ?? "part").replace(/\s*\(.*\)\s*$/, "");

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <h1 className="font-display text-4xl font-bold">Inspect a part</h1>
        <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
          <label className="flex flex-col gap-1">
            <span className="text-[15px] text-ink-dim">Product</span>
            <select value={selected ?? ""} onChange={(e) => choose(e.target.value)} disabled={products.isLoading}
                    className="min-w-72 rounded-sm border border-rule bg-housing px-3 py-3 font-display text-2xl font-semibold">
              {!selected && <option value="" disabled>{products.isLoading ? "Loading products…" : "Choose a product"}</option>}
              {ready.length > 0 && (
                <optgroup label="Ready to inspect">
                  {ready.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </optgroup>
              )}
              {learning.length > 0 && (
                <optgroup label="Still needs good photos">
                  {learning.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </optgroup>
              )}
              {!api.demo && <option value={ADD_NEW}>+ Add a new product…</option>}
            </select>
          </label>
          {product?.status === "ready" && (
            <p className="pb-3 text-[15px] text-ink-dim">
              Saved product, {summary(product)}.{" "}
              <Link href={`/stations/${product.id}`} className="text-steel underline">History and settings</Link>
            </p>
          )}
        </div>
        {products.isError && <p className="text-stop">Could not load products: {(products.error as Error).message}</p>}
        {products.data && products.data.length === 0 && (
          <p className="text-ink-dim">
            No products saved yet. <Link href="/setup" className="text-steel underline">Add your first product</Link> with
            about 30 photos of good parts; after that, one photo is all it takes to inspect.
          </p>
        )}
      </section>

      {product && product.status !== "ready" && (
        <section className="border-l-4 border-hold bg-housing px-5 py-4">
          <p className="font-display text-2xl font-semibold">{product.name} is not ready to inspect yet.</p>
          <p className="mt-1 text-ink-dim">
            {product.status === "building"
              ? "It is learning from its good photos on the GPU right now. This takes about a minute."
              : (product.n_usable ?? 0) === 0
                ? "It has no good photos yet. Add about 30 photos of good ones and train it once; after that you only ever upload one photo."
                : `It has ${product.n_usable} usable good photos saved. Add more if you have them (30 or more is best) and train it once; after that you only ever upload one photo.`}
          </p>
          {product.status !== "building" && (
            <Link href={`/setup?station=${product.id}`} className="mt-3 inline-block rounded-sm bg-steel px-4 py-2.5 font-semibold text-tag-ink">
              Add good photos of {product.name}
            </Link>
          )}
        </section>
      )}

      {product?.status === "ready" && (
        <section className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="min-w-0">
            {result ? (
              <InspectionViewer image={result.image_url} overlay={result.overlay_url} regions={result.regions} />
            ) : api.demo ? (
              <p className="hatch border border-hold/50 p-4 text-[15px] text-hold">
                The GPU service is switched off right now, so new photos cannot be inspected. Recorded results for{" "}
                {product.name} are on its <Link href={`/stations/${product.id}`} className="underline">history page</Link>.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                <PhotoDrop onFile={(f) => send(f)} busy={pending}
                           title={`Take or choose one photo of a ${productName}`}
                           hint={<>Photograph it the same way as the good photos: same camera distance, lighting and background. Photos are kept in this product&apos;s history.</>} />
                <button onClick={() => setCamera((c) => !c)} className="self-start rounded-sm border border-rule px-3 py-2 text-[15px]">
                  {camera ? "Close camera" : "Use this device's camera"}
                </button>
                {camera && <Camera onCapture={(f) => send(f)} busy={pending} />}
                {samples.data?.[product.id] && (
                  <div>
                    <p className="mb-1.5 text-sm text-ink-dim">No {productName} at hand? Try one of these photos it has never seen:</p>
                    <div className="flex flex-wrap gap-2">
                      {samples.data[product.id].map((sm) => (
                        <button key={sm.src} onClick={() => sendSample(sm)} disabled={pending}
                                className="h-16 w-16 overflow-hidden rounded-sm border border-rule hover:border-steel disabled:opacity-50">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={sm.src} alt={`Sample photo of a ${productName}`} className="h-full w-full object-cover" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-col gap-4">
            {error && <p className="text-stop">Inspection failed: {error.message}</p>}
            {result ? (
              <>
                <InspectionResult r={result} note={sampleTruth ? `This sample photo is known to be ${sampleTruth}.` : null} />
                <button onClick={() => { setResult(null); setSampleTruth(null); }}
                        className="self-start rounded-sm bg-steel px-4 py-3 text-lg font-semibold text-tag-ink">
                  Inspect another {productName}
                </button>
              </>
            ) : (
              !api.demo && (
                <p className="text-ink-dim">
                  The answer appears here: pass, review (an inspector should look) or reject, with any unusual areas outlined and named.
                </p>
              )
            )}
          </div>
        </section>
      )}
    </div>
  );
}

export default function InspectPage() {
  return (
    <Suspense fallback={<p className="text-ink-dim">Loading…</p>}>
      <Inspect />
    </Suspense>
  );
}
