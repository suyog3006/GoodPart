"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Honest about compute: every screen shows whether results are live from the GPU or recorded.
export function ModeBadge() {
  const h = useQuery({ queryKey: ["health"], queryFn: api.health });
  if (api.demo)
    return (
      <span className="hatch rounded border border-hold/60 px-2.5 py-1 text-sm text-hold">
        Demo mode: recorded results from {h.data?.device ?? "the AMD GPU"}
      </span>
    );
  if (h.isError) return <span className="rounded border border-stop px-2.5 py-1 text-sm text-stop">GPU service offline</span>;
  return (
    <span className="rounded border border-pass/60 px-2.5 py-1 text-sm text-pass">
      Live on {h.data?.device ?? "…"}
    </span>
  );
}
