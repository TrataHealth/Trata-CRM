import React, { useEffect, useState } from "react";
import { Clock, AlertTriangle } from "lucide-react";
import { slaInfo } from "../lib/constants";

/** Live-updating SLA chip. Re-renders every minute. */
export default function SlaChip({ since, threshold = 24, prefix = "Pending", testid }) {
  const [, force] = useState(0);
  useEffect(() => {
    if (!since) return;
    const t = setInterval(() => force((n) => n + 1), 60000);
    return () => clearInterval(t);
  }, [since]);
  if (!since) return null;
  const info = slaInfo(since, threshold);
  const Icon = info.urgency === "overdue" ? AlertTriangle : Clock;
  const label = info.urgency === "overdue" ? "OVERDUE" : prefix;
  return (
    <span
      data-testid={testid}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-semibold rounded uppercase tracking-wider whitespace-nowrap"
      style={{
        background: info.urgency === "overdue" ? `${info.color}` : `${info.color}22`,
        color: info.urgency === "overdue" ? "#fff" : info.color,
        border: `1px solid ${info.color}${info.urgency === "overdue" ? "" : "55"}`,
      }}
      title={`Since ${new Date(since).toLocaleString()}`}
    >
      <Icon className="h-3 w-3" />
      {label} {info.label}
    </span>
  );
}
