"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { resolveMode } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1 } } }));
  const [ready, setReady] = useState(false);
  useEffect(() => {
    resolveMode().then(() => setReady(true));
  }, []);
  return (
    <QueryClientProvider client={client}>
      {ready ? children : <p className="p-6 text-ink-dim">Connecting to the GPU service…</p>}
    </QueryClientProvider>
  );
}
