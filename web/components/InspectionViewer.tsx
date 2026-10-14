"use client";
import { useState } from "react";
import type { Region } from "@/lib/api";

// Image with heatmap overlay (opacity slider) and outlined regions labelled with size and zone.
export function InspectionViewer({ image, overlay, regions, size = 768 }: {
  image: string; overlay: string; regions: Region[]; size?: number;
}) {
  const [opacity, setOpacity] = useState(0.7);
  const [showRegions, setShowRegions] = useState(true);
  return (
    <figure className="w-full">
      <div className="relative aspect-square w-full overflow-hidden rounded-sm border border-rule bg-black">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={image} alt="Inspected part" className="absolute inset-0 h-full w-full object-contain" />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={overlay} alt="" aria-hidden className="absolute inset-0 h-full w-full object-contain"
             style={{ opacity }} />
        {showRegions && (
          <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 h-full w-full">
            {regions.map((r, i) => {
              const [x, y, w, h] = r.bbox;
              const out = r.verdict === "out_of_tolerance";
              const label = `${i + 1}${r.length_mm != null ? `, ${r.length_mm.toFixed(1)} mm` : ""}${r.zone ? `, ${r.zone}` : ""}`;
              return (
                <g key={i}>
                  <rect x={x - 4} y={y - 4} width={w + 8} height={h + 8} fill="none"
                        stroke={out ? "var(--stop)" : "var(--hold)"} strokeWidth={3} />
                  <rect x={x - 4} y={Math.max(0, y - 30)} width={Math.max(40, label.length * 10)} height={24}
                        fill={out ? "var(--stop)" : "var(--hold)"} />
                  <text x={x + 2} y={Math.max(17, y - 12)} fontSize={18} fontWeight={600} fill="var(--tag-ink)">{label}</text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <figcaption className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-dim">
        <label className="flex items-center gap-3">
          Heatmap
          <input type="range" min={0} max={1} step={0.05} value={opacity}
                 onChange={(e) => setOpacity(+e.target.value)} className="w-40 accent-[var(--steel)]" />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={showRegions} onChange={(e) => setShowRegions(e.target.checked)} />
          Region outlines
        </label>
      </figcaption>
    </figure>
  );
}
