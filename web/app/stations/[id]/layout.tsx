"use client";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const TABS = [
  ["", "Inspect"],
  ["/review", "Review queue"],
  ["/calibrate", "Calibration"],
  ["/stress", "Stress test"],
  ["/zones", "Zones"],
] as const;

export default function StationLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const path = usePathname();
  const s = useQuery({ queryKey: ["station", id], queryFn: () => api.station(id) });
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <h1 className="font-display text-4xl font-bold">{s.data?.name ?? "Station"}</h1>
        {s.data?.station && <p className="text-ink-dim">{s.data.station.guarantee}</p>}
      </div>
      <nav className="mb-6 flex flex-wrap gap-1 border-b border-rule" aria-label="Station sections">
        {TABS.map(([suffix, label]) => {
          const href = `/stations/${id}${suffix}`;
          const active = path === href;
          return (
            <Link key={label} href={href} aria-current={active ? "page" : undefined}
                  className={`-mb-px border-b-[3px] px-4 py-2.5 text-[15px] ${active ? "border-steel font-semibold text-ink" : "border-transparent text-ink-dim hover:text-ink"}`}>
              {label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
