import type { Decision } from "@/lib/api";

const STYLE: Record<Decision, { bg: string; word: string; icon: string; hint: string }> = {
  pass: { bg: "bg-pass", word: "Pass", icon: "✓", hint: "Ship it" },
  review: { bg: "bg-hold", word: "Review", icon: "?", hint: "Hold for an inspector" },
  reject: { bg: "bg-stop", word: "Reject", icon: "✕", hint: "Do not ship" },
};

// The decision as a QC hang tag: colour, icon and word together, readable for colour-blind users
// and from across a bright workshop.
export function DecisionTag({ decision, size = "lg", stampKey }: { decision: Decision; size?: "lg" | "sm"; stampKey?: string }) {
  const s = STYLE[decision];
  if (size === "sm")
    return (
      <span className={`qc-tag inline-flex items-center gap-1.5 py-0.5 pl-6 pr-2.5 font-display text-base font-semibold ${s.bg}`}>
        <span aria-hidden>{s.icon}</span>
        {s.word}
      </span>
    );
  return (
    <div key={stampKey} className={`qc-tag qc-tag-stamp flex items-center gap-5 py-5 pl-20 pr-8 ${s.bg}`} role="status">
      <span aria-hidden className="font-display text-6xl font-bold leading-none">{s.icon}</span>
      <div>
        <div className="font-display text-6xl font-bold leading-none tracking-tight sm:text-7xl">{s.word}</div>
        <div className="mt-1 text-lg font-medium opacity-80">{s.hint}</div>
      </div>
    </div>
  );
}
