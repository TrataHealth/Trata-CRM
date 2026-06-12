import React from "react";

// Tiny purpose-built markdown renderer shared by the dashboards' AI insight panels.
// Handles only what /api/{dashboard,agent}/ai-insights returns: `## heading`, `- bullet`, **bold**, paragraphs.
export function renderInsightsMarkdown(md) {
  const lines = (md || "").split(/\r?\n/);
  const out = [];
  let listBuf = [];
  const flushList = () => {
    if (listBuf.length) {
      out.push(
        <ul key={`ul-${out.length}`} className="list-disc pl-5 space-y-1 my-2 text-[#42526E]">
          {listBuf.map((item, i) => <li key={i}>{renderInline(item)}</li>)}
        </ul>
      );
      listBuf = [];
    }
  };
  lines.forEach((raw, idx) => {
    const line = raw.trim();
    if (!line) { flushList(); return; }
    if (line.startsWith("## ")) {
      flushList();
      out.push(<h3 key={`h-${idx}`} className="font-heading font-bold text-[#091E42] mt-3 first:mt-0 text-sm uppercase tracking-wide">{line.slice(3)}</h3>);
      return;
    }
    if (line.startsWith("- ") || line.startsWith("* ")) {
      listBuf.push(line.slice(2));
      return;
    }
    flushList();
    out.push(<p key={`p-${idx}`} className="text-[#42526E] my-1.5">{renderInline(line)}</p>);
  });
  flushList();
  return <>{out}</>;
}

function renderInline(text) {
  const parts = (text || "").split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return <strong key={i} className="text-[#091E42] font-semibold">{p.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={i}>{p}</React.Fragment>;
  });
}

export const RANGE_OPTIONS = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "12m", label: "12M" },
  { value: "all", label: "All" },
];
