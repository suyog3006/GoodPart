import type { Inspection } from "@/lib/api";
import { DecisionTag } from "@/components/DecisionTag";
import { ComputeBadge } from "@/components/ComputeBadge";

// Decision, reason, compute badge and the list of unusual regions with their names.
export function InspectionResult({ r, note }: { r: Inspection; note?: string | null }) {
  return (
    <div className="flex flex-col gap-5">
      <DecisionTag decision={r.decision} stampKey={r.id} />
      <p className="text-lg leading-snug">{r.reason}</p>
      <div className="flex flex-wrap items-center gap-3">
        <ComputeBadge device={r.device} ms={r.latency_ms} />
        <span className="text-sm text-ink-dim">score {r.score.toFixed(2)}</span>
        {r.truth && <span className="text-sm text-ink-dim">ground truth: {r.truth}</span>}
        {note && <span className="text-sm text-ink-dim">{note}</span>}
      </div>
      {r.regions.length > 0 && (
        <ol className="flex flex-col gap-3">
          {r.regions.map((g, i) => (
            <li key={i} className={`border-l-4 bg-housing px-4 py-3 ${g.verdict === "out_of_tolerance" ? "border-stop" : "border-hold"}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-display text-xl font-semibold capitalize">
                  {i + 1}. {g.name?.label ?? "naming…"}
                </span>
                <span className="text-sm text-ink-dim">
                  {g.length_mm != null ? `${g.length_mm.toFixed(1)} mm long` : `${Math.round(g.length_px)} px long`}
                  {g.zone ? `, ${g.zone}` : ""}
                </span>
              </div>
              {g.name?.description && <p className="mt-1 text-[15px]">{g.name.description}</p>}
              <p className="mt-1 text-sm text-ink-dim">
                {g.reason}
                {g.name?.source && g.name.source !== "template" && ` Named by ${g.name.model ?? g.name.source}.`}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
