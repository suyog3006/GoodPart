"use client";
import { useState } from "react";

// One photo in: drop it, choose it, or (on a phone) take it with the camera.
export function PhotoDrop({ onFile, busy, title, hint }: {
  onFile: (f: File) => void; busy: boolean; title: string; hint?: React.ReactNode;
}) {
  const [drag, setDrag] = useState(false);
  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f && !busy) onFile(f); }}
      className={`flex min-h-40 cursor-pointer flex-col items-center justify-center border-2 border-dashed px-4 py-8 text-center ${drag ? "border-steel bg-housing" : "border-rule hover:border-steel"} ${busy ? "cursor-wait" : ""}`}>
      <span className="font-display text-2xl font-semibold">{busy ? "Inspecting on the AMD GPU…" : title}</span>
      {hint && <span className="mt-1 max-w-[60ch] text-sm text-ink-dim">{hint}</span>}
      <input type="file" accept="image/*" hidden disabled={busy}
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
    </label>
  );
}
