"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Inspection } from "@/lib/api";

// Inspect one photo against a saved product. Defect names are added by the vision-language model a
// few seconds after the decision, so they are fetched again shortly afterwards.
export function useInspect(productId: string | null) {
  const qc = useQueryClient();
  const [result, setResult] = useState<Inspection | null>(null);
  const mutation = useMutation({
    mutationFn: (f: File) => {
      if (!productId) throw new Error("Choose a product first.");
      return api.inspect(productId, f);
    },
    onMutate: () => setResult(null),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["inspections", productId] });
      qc.invalidateQueries({ queryKey: ["stations"] });
      if (!r.regions.length || !productId) return;
      [2500, 6000, 12000].forEach((ms) =>
        setTimeout(async () => {
          const rows = await api.inspections(productId);
          const hit = rows.find((x) => x.id === r.id);
          if (hit) setResult((c) => (c && c.id === r.id ? { ...c, regions: hit.regions } : c));
        }, ms),
      );
    },
  });
  return { result, setResult, inspect: mutation.mutate, pending: mutation.isPending, error: mutation.error as Error | null };
}
