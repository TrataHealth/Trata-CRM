import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { statusColor, relativeTime } from "../lib/constants";
import { Plus, Trash2, Loader2 } from "lucide-react";

export default function Tasks() {
  const [list, setList] = useState([]);
  const [team, setTeam] = useState([]);
  const [tab, setTab] = useState("all");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: "", description: "", assigned_to: "", priority: "medium", due_date: "" });

  const load = async () => {
    setLoading(true);
    const [t, tm] = await Promise.all([
      api.get("/tasks", { params: { status: tab === "all" ? undefined : tab, limit: 200 } }),
      api.get("/team"),
    ]);
    setList(t.data.items); setTeam(tm.data.items); setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tab]);

  const create = async () => {
    if (!form.title.trim()) return;
    setCreating(true);
    try {
      await api.post("/tasks", { ...form, due_date: form.due_date ? new Date(form.due_date).toISOString() : null });
      setForm({ title: "", description: "", assigned_to: "", priority: "medium", due_date: "" });
      load();
    } finally { setCreating(false); }
  };

  const setStatus = async (id, status) => {
    await api.patch(`/tasks/${id}`, { status });
    load();
  };
  const del = async (id) => {
    await api.delete(`/tasks/${id}`);
    load();
  };

  return (
    <div className="p-6 lg:p-8 space-y-6" data-testid="tasks-page">
      <div>
        <div className="overline">Daily Operations</div>
        <h1 className="font-heading text-3xl font-black tracking-tight text-[#091E42] mt-1">Tasks</h1>
        <p className="text-sm text-[#5E6C84] mt-1">Assign work to your team and track follow-ups across contacts.</p>
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md p-4" data-testid="task-create-form">
        <div className="overline mb-2">Quick add</div>
        <div className="grid grid-cols-1 md:grid-cols-12 gap-2">
          <input
            data-testid="task-title-input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Task title…"
            className="md:col-span-4 px-3 py-2 text-sm border border-[#DFE1E6] rounded-md focus:border-[#4C9AFF] outline-none"
          />
          <select
            data-testid="task-assignee-select"
            value={form.assigned_to}
            onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}
            className="md:col-span-3 px-2 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white"
          >
            <option value="">Unassigned</option>
            {team.map((m) => <option key={m.id} value={m.id}>{m.name} — {m.role}</option>)}
          </select>
          <select
            data-testid="task-priority-select"
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: e.target.value })}
            className="md:col-span-2 px-2 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white"
          >
            {["low", "medium", "high", "critical"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <input
            data-testid="task-due-input"
            type="date"
            value={form.due_date}
            onChange={(e) => setForm({ ...form, due_date: e.target.value })}
            className="md:col-span-2 px-2 py-2 text-sm border border-[#DFE1E6] rounded-md bg-white"
          />
          <button
            data-testid="task-create-btn"
            onClick={create}
            disabled={creating}
            className="md:col-span-1 flex items-center justify-center gap-1 px-3 py-2 text-sm font-semibold bg-[#0052CC] text-white rounded-md hover:bg-[#0747A6] disabled:opacity-60"
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Plus className="h-4 w-4" /> Add</>}
          </button>
        </div>
      </div>

      <div className="flex gap-1.5 border-b border-[#DFE1E6] pb-3" data-testid="task-tabs">
        {[
          { v: "all", l: "All" },
          { v: "open", l: "Open" },
          { v: "in_progress", l: "In Progress" },
          { v: "done", l: "Done" },
        ].map((t) => (
          <button
            key={t.v}
            data-testid={`task-tab-${t.v}`}
            onClick={() => setTab(t.v)}
            className={`px-3 py-1.5 text-sm font-medium rounded-md ${tab === t.v ? "bg-[#091E42] text-white" : "text-[#42526E] hover:bg-[#F1F2F4]"}`}
          >{t.l}</button>
        ))}
      </div>

      <div className="bg-white border border-[#DFE1E6] rounded-md">
        {loading && <div className="p-10 text-center text-sm text-[#5E6C84]">Loading…</div>}
        {!loading && list.length === 0 && <div className="p-10 text-center text-sm text-[#5E6C84]">No tasks here.</div>}
        <ul className="divide-y divide-[#F1F2F4]" data-testid="tasks-list">
          {list.map((t) => {
            const assignee = team.find((m) => m.id === t.assigned_to);
            const overdue = t.due_date && new Date(t.due_date) < new Date() && t.status !== "done";
            return (
              <li key={t.id} className="p-3 flex items-center gap-3" data-testid={`task-row-${t.id}`}>
                <select
                  value={t.status}
                  onChange={(e) => setStatus(t.id, e.target.value)}
                  data-testid={`task-status-${t.id}`}
                  className="text-xs uppercase tracking-wider font-semibold px-2 py-1 rounded border border-[#DFE1E6] bg-white"
                  style={{ color: statusColor(t.status) }}
                >
                  <option value="open">Open</option>
                  <option value="in_progress">In Progress</option>
                  <option value="done">Done</option>
                </select>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-[#091E42]">{t.title}</div>
                  {t.description && <div className="text-xs text-[#5E6C84] mt-0.5">{t.description}</div>}
                </div>
                <span className="text-xs uppercase font-semibold" style={{ color: t.priority === "critical" ? "#FF5630" : t.priority === "high" ? "#FFAB00" : "#5E6C84" }}>
                  {t.priority}
                </span>
                <span className="text-xs text-[#5E6C84] w-32 truncate">{assignee?.name || "Unassigned"}</span>
                <span className={`text-xs w-24 ${overdue ? "text-[#FF5630] font-semibold" : "text-[#5E6C84]"}`}>
                  {t.due_date ? relativeTime(t.due_date) : "—"}
                </span>
                <button onClick={() => del(t.id)} className="p-1.5 hover:bg-[#FFEBE6] text-[#5E6C84] hover:text-[#FF5630] rounded" data-testid={`task-delete-${t.id}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
