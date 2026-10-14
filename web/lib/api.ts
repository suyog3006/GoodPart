// Data access for GoodPart. Live mode talks to the GPU service through our own server-side proxy
// (/api/gp/*), which holds the API token. Demo mode reads recorded results from /demo/*.

export type Decision = "pass" | "review" | "reject";

export type Region = {
  bbox: [number, number, number, number];
  area_px: number;
  length_px: number;
  elongation: number;
  peak: number;
  zone: string | null;
  length_mm: number | null;
  area_mm2: number | null;
  verdict: "noted" | "out_of_tolerance";
  reason: string;
  name?: { label: string; description: string; source: string; latency_s?: number; model?: string } | null;
};

export type Inspection = {
  id: string;
  station: string;
  created: number;
  score: number;
  z: Record<string, number>;
  decision: Decision;
  band: Decision;
  reason: string;
  regions: Region[];
  device: string;
  latency_ms: number;
  image_url: string;
  overlay_url: string;
  truth?: "good" | "anomaly";
  review_label?: string | null;
  defect_type?: string | null;
};

export type Calibration = {
  alpha_target: number;
  alpha_guaranteed: number;
  review_cap: number;
  delta: number;
  t_low: number;
  t_high: number;
  n_cal: number;
  review_certified: boolean;
  review_share_cal: number;
};

export type PodFit = {
  ok: boolean;
  a90?: number;
  a90_95?: number;
  n: number;
  hit_rate: number | null;
  curve: { size: number[]; pod: number[]; lower95: number[] };
};

export type StationSummary = {
  id: string;
  name: string;
  status: string;
  mm_per_px: number | null;
  counts: Partial<Record<Decision, number>>;
  meta: Record<string, unknown>;
};

export type StationDetail = StationSummary & {
  zones: Zone[];
  station?: {
    active: string[];
    selection: Record<string, number>;
    calibration: Calibration;
    guarantee: string;
    pod: PodFit;
    mm_per_px: number | null;
    a90_95_mm: number | null;
    scores: { calibration: number[]; synthetic: number[] };
    timings: Record<string, number>;
  };
};

export type Zone = {
  name: string;
  polygon: [number, number][];
  max_length_mm?: number | null;
  max_area_mm2?: number | null;
  max_count?: number | null;
};

export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "1";

async function demo<T>(path: string): Promise<T> {
  const r = await fetch(`/demo/${path}`);
  if (!r.ok) throw new Error(`Recorded data missing: ${path}`);
  return r.json();
}

async function live<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/gp/${path}`, init);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

function withUrls(i: Omit<Inspection, "image_url" | "overlay_url"> & Partial<Inspection>): Inspection {
  return {
    ...i,
    image_url: i.image_url ?? `/api/gp/inspections/${i.id}/image`,
    overlay_url: i.overlay_url ?? `/api/gp/inspections/${i.id}/image?overlay=true`,
  } as Inspection;
}

export const api = {
  demo: DEMO,
  health: () => (DEMO ? demo<{ device: string }>("health.json") : live<{ device: string }>("health")),
  stations: () => (DEMO ? demo<StationSummary[]>("stations.json") : live<StationSummary[]>("stations")),
  station: (id: string) => (DEMO ? demo<StationDetail>(`station_${id}.json`) : live<StationDetail>(`stations/${id}`)),
  inspections: async (id: string) =>
    (DEMO ? await demo<Inspection[]>(`inspections_${id}.json`) : await live<Inspection[]>(`stations/${id}/inspections`)).map(
      withUrls,
    ),
  inspect: async (id: string, file: File): Promise<Inspection & { overlay_png?: string; image_png?: string }> => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await live<Inspection & { overlay_png: string; image_png: string }>(`stations/${id}/inspect`, {
      method: "POST",
      body: fd,
    });
    return { ...r, image_url: `data:image/png;base64,${r.image_png}`, overlay_url: `data:image/png;base64,${r.overlay_png}` };
  },
  review: (iid: string, label: "good" | "defect", defect_type?: string) =>
    DEMO
      ? Promise.resolve({ ok: true })
      : live<{ ok: boolean; guarantee?: string }>(`inspections/${iid}/review`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ label, defect_type }),
        }),
  calibrate: (id: string, alpha: number, review_cap: number) =>
    live<{ calibration: Calibration; guarantee: string; expected_review_share: number; synthetic_miss_rate: number }>(
      `stations/${id}/calibrate`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ alpha, review_cap }) },
    ),
  createStation: (name: string) =>
    live<{ id: string }>("stations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  uploadGood: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return live<{ uploaded: { id: string; file: string; flags: string[]; sharpness: number; scale: unknown }[] }>(
      `stations/${id}/images`,
      { method: "POST", body: fd },
    );
  },
  build: (id: string) => live<{ status: string }>(`stations/${id}/build`, { method: "POST" }),
  saveZones: (id: string, zones: Zone[], mm_per_px?: number | null) =>
    live<{ ok: boolean }>(`stations/${id}/zones`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ zones, mm_per_px }),
    }),
  evaluation: () => demo<EvalBundle>("eval.json"),
};

export type EvalBundle = {
  results: Record<string, number | string | boolean | null>[];
  baselines: Record<string, number | string | null>[];
  zeroshot: Record<string, number | string | null>[];
  benchmark: { rows: Record<string, number | string>[]; gpu_hour_usd: number } | null;
  fewshot: Record<string, number | string>[];
  failures: { category: string; file: string; kind: string; score: number; image: string; overlay: string }[];
};

// Same pass/review/reject rule as the backend, for live slider previews.
export function band(score: number, tLow: number, tHigh: number): Decision {
  if (score > tHigh) return "reject";
  if (score < tLow) return "pass";
  return "review";
}

// Split-conformal threshold, mirrored from goodpart/calibrate/stats.py for instant slider feedback.
export function conformal(cal: number[], alpha: number): number {
  const s = [...cal].sort((a, b) => a - b);
  const r = Math.ceil((s.length + 1) * (1 - alpha));
  return r > s.length ? Infinity : s[r - 1];
}

function logGamma(x: number): number {
  // Lanczos approximation
  const g = 7;
  const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
    12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - logGamma(1 - x);
  x -= 1;
  let a = c[0];
  const t = x + g + 0.5;
  for (let i = 1; i < g + 2; i++) a += c[i] / (x + i);
  return 0.5 * Math.log(2 * Math.PI) + (x + 0.5) * Math.log(t) - t + Math.log(a);
}

export function binomCdf(k: number, n: number, p: number): number {
  let s = 0;
  for (let i = 0; i <= k; i++) {
    s += Math.exp(logGamma(n + 1) - logGamma(i + 1) - logGamma(n - i + 1) + i * Math.log(p) + (n - i) * Math.log(1 - p));
  }
  return Math.min(1, s);
}

// Learn-then-Test pass threshold, mirrored from goodpart/calibrate/stats.py.
export function learnThenTest(cal: number[], tHigh: number, cap: number, delta = 0.1, synth?: number[]) {
  const n = cal.length;
  const top = Number.isFinite(tHigh) ? tHigh : Math.max(...cal);
  const cands = [...new Set([...cal.filter((s) => s <= top), top])].sort((a, b) => b - a);
  const admissible: number[] = [];
  for (const t of cands) {
    const k = cal.filter((s) => s >= t && s <= top).length;
    if (binomCdf(k, n, cap) > delta) break;
    admissible.push(t);
  }
  if (!admissible.length) return { tLow: top, certified: false };
  if (!synth) return { tLow: admissible.at(-1)!, certified: true };
  let best = admissible[0];
  let bestMiss = Infinity;
  for (const t of admissible) {
    const miss = synth.filter((s) => s < t).length;
    if (miss < bestMiss || (miss === bestMiss && t > best)) {
      best = t;
      bestMiss = miss;
    }
  }
  return { tLow: best, certified: true };
}
