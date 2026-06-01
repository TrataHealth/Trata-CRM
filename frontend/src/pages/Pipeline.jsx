import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { PIPELINE_STAGES, typeLabel, fmtCurrency } from "../lib/constants";
import { Avatar } from "./Contacts";
import { GripVertical } from "lucide-react";

export default function Pipeline() {
  const [data, setData] = useState(null);
  const [drag, setDrag] = useState(null);
  const navigate = useNavigate();

  const load = async () => {
    const { data } = await api.get("/pipeline");
    setData(data);
  };
  useEffect(() => { load(); }, []);

  const onDrop = async (stage) => {
    if (!drag || drag.stage === stage) return;
    await api.patch(`/contacts/${drag.id}`, { pipeline_stage: stage });
    setDrag(null);
    load();
  };

  if (!data) return <div className="p-8 text-sm text-[#5E6C84]">Loading…</div>;

  const totals = {};
  PIPELINE_STAGES.forEach((s) => {
    totals[s.value] = (data.items_by_stage[s.value] || []).reduce((acc, x) => acc + (x.deal_value || 0), 0);
  });

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-5 lg:space-y-6" data-testid="pipeline-page">
      <div>
        <div className="overline">Provider Acquisition</div>
        <h1 className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-[#091E42] mt-1">Pipeline</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Drag providers between stages. Hospitals, doctors, ambulances, paramedics & labs only.</p>
      </div>

      <div className="flex lg:grid gap-3 lg:grid-cols-6 overflow-x-auto scrollbar-thin -mx-4 px-4 sm:mx-0 sm:px-0 pb-3 min-h-[60vh] snap-x" data-testid="pipeline-board">
        {PIPELINE_STAGES.map((s) => {
          const items = data.items_by_stage[s.value] || [];
          return (
            <div
              key={s.value}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(s.value)}
              className="bg-[#F8F9FA] border border-[#DFE1E6] rounded-md flex flex-col w-[78vw] sm:w-[60vw] md:w-[40vw] lg:w-auto shrink-0 snap-start"
              data-testid={`stage-column-${s.value}`}
            >
              <div className="p-3 border-b border-[#DFE1E6]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                    <span className="text-xs uppercase tracking-wider font-semibold text-[#091E42]">{s.label}</span>
                  </div>
                  <span className="text-xs font-mono text-[#5E6C84]">{items.length}</span>
                </div>
                <div className="text-[11px] text-[#5E6C84] mt-1 font-mono">{fmtCurrency(totals[s.value])}</div>
              </div>
              <div className="flex-1 p-2 space-y-2 overflow-auto scrollbar-thin max-h-[70vh]">
                {items.map((it) => (
                  <div
                    key={it.id}
                    draggable
                    onDragStart={() => setDrag({ id: it.id, stage: s.value })}
                    onClick={() => navigate(`/contacts/${it.id}`)}
                    data-testid={`pipeline-card-${it.id}`}
                    className="bg-white border border-[#DFE1E6] rounded-md p-2.5 cursor-grab active:cursor-grabbing hover:border-[#0052CC] hover:shadow-sm transition-all"
                  >
                    <div className="flex items-start gap-2">
                      <Avatar name={it.name} src={it.avatar} size={28} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold text-[#091E42] truncate">{it.name}</div>
                        <div className="text-[11px] text-[#5E6C84] truncate">{typeLabel(it.type)} · {it.city}</div>
                        {it.specialization && <div className="text-[11px] text-[#42526E] truncate mt-0.5">{it.specialization}</div>}
                      </div>
                      <GripVertical className="h-3.5 w-3.5 text-[#B3BAC5] mt-1" />
                    </div>
                    {it.deal_value > 0 && (
                      <div className="mt-2 text-[11px] font-mono text-[#36B37E] font-semibold">{fmtCurrency(it.deal_value)}</div>
                    )}
                  </div>
                ))}
                {items.length === 0 && (
                  <div className="text-[11px] text-[#5E6C84] text-center py-6">Drag cards here</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
