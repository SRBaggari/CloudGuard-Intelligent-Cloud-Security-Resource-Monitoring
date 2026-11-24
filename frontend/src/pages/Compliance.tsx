import clsx from "clsx";
import {
  CheckCircle2, CircleDashed, CircleHelp, ClipboardCheck, FileDown, MinusCircle, Play, Plus, ShieldCheck, Trash2, TriangleAlert, XCircle,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { TimeSeriesChart } from "@/components/charts";
import {
  Banner, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, SeverityBadge, Spinner,
  Toggle, useToast,
} from "@/components/ui";
import { api, ApiError, downloadFile } from "@/lib/api";
import { formatDateTime, timeAgo, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page, Report, Severity } from "@/lib/types";

interface Check {
  id: number; key: string; title: string; description: string; category: string; severity: Severity;
  check_type: "automated" | "manual"; reference: string; remediation: string; enabled: boolean; is_custom: boolean;
  manual_status: string | null; manual_evidence: string; assessed_at: string | null;
  last_status: string; last_evidence: string; last_checked_at: string | null;
}
interface Run { id: number; score: number; grade: string; counts: Record<string, number>; created_at: string }

const STATUS: Record<string, { icon: typeof CheckCircle2; cls: string; label: string }> = {
  pass: { icon: CheckCircle2, cls: "text-good", label: "Pass" },
  fail: { icon: XCircle, cls: "text-critical", label: "Fail" },
  warning: { icon: TriangleAlert, cls: "text-warning", label: "Warning" },
  not_applicable: { icon: MinusCircle, cls: "text-muted", label: "Not applicable" },
  unknown: { icon: CircleHelp, cls: "text-muted", label: "Unknown" },
  not_assessed: { icon: CircleDashed, cls: "text-muted", label: "Not assessed" },
};
const GRADE_COLOR: Record<string, string> = { A: "var(--good)", B: "var(--good)", C: "var(--warning)", D: "var(--serious)", F: "var(--critical)" };

function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.unknown;
  const Icon = s.icon;
  return <span className={clsx("inline-flex items-center gap-1 text-xs font-semibold", s.cls)}><Icon className="size-3.5" /> {s.label}</span>;
}

function AssessModal({ check, onClose, onSaved }: { check: Check; onClose: () => void; onSaved: () => void }) {
  const [status, setStatus] = useState(check.manual_status ?? "pass");
  const [evidence, setEvidence] = useState(check.manual_evidence);
  const [err, setErr] = useState("");
  const toast = useToast();
  async function save(e: FormEvent) {
    e.preventDefault();
    if (evidence.trim().length < 3) return setErr("Describe the evidence for this assessment");
    try {
      await api(`/api/compliance/checks/${check.id}/assess`, { method: "POST", body: { status, evidence } });
      toast({ tone: "good", title: "Assessment recorded" });
      onSaved();
      onClose();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
    }
  }
  return (
    <Modal open onClose={onClose} title={`Assess · ${check.title}`}>
      <form onSubmit={save} className="space-y-4">
        <p className="text-sm text-ink-2">{check.description}</p>
        <Field label="Result" htmlFor="as-status">
          <Select id="as-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {["pass", "warning", "fail", "not_applicable"].map((s) => <option key={s} value={s}>{STATUS[s].label}</option>)}
          </Select>
        </Field>
        <Field label="Evidence" htmlFor="as-ev" error={err} hint="E.g. where the backup log is, who verified it and when">
          <textarea id="as-ev" rows={4} value={evidence} onChange={(e) => setEvidence(e.target.value)}
            className="w-full rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-sm focus:border-accent focus:outline-none" />
        </Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary">Save assessment</Button>
        </div>
      </form>
    </Modal>
  );
}

function AddCheckModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ title: "", description: "", severity: "medium", remediation: "" });
  const [err, setErr] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    if (form.title.trim().length < 3) return setErr("Title must have at least 3 characters");
    try {
      await api("/api/compliance/checks", { method: "POST", body: form });
      onSaved();
      onClose();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
    }
  }
  return (
    <Modal open onClose={onClose} title="Add custom checklist item">
      <form onSubmit={save} className="space-y-4">
        <Field label="Title" htmlFor="ac-title" error={err}><Input id="ac-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label="Description" htmlFor="ac-desc"><Input id="ac-desc" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Severity" htmlFor="ac-sev">
            <Select id="ac-sev" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
              {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
          </Field>
          <Field label="Remediation" htmlFor="ac-rem"><Input id="ac-rem" value={form.remediation} onChange={(e) => setForm({ ...form, remediation: e.target.value })} /></Field>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary">Add item</Button>
        </div>
      </form>
    </Modal>
  );
}

export default function Compliance() {
  const toast = useToast();
  const checks = useApi<Check[]>("/api/compliance/checks");
  const posture = useApi<Run | null>("/api/compliance/posture");
  const runs = useApi<Page<Run>>("/api/compliance/runs", { query: { page_size: 30 } });
  const [busy, setBusy] = useState<string | null>(null);
  const [assessing, setAssessing] = useState<Check | null>(null);
  const [adding, setAdding] = useState(false);
  const [filter, setFilter] = useState("");
  const reloadAll = () => { checks.reload(); posture.reload(); runs.reload(); };

  async function runNow() {
    setBusy("run");
    try {
      const r = await api<Run>("/api/compliance/run", { method: "POST" });
      toast({ tone: "good", title: `Posture score ${r.score.toFixed(1)} (grade ${r.grade})` });
      reloadAll();
    } catch (e) {
      toast({ tone: "critical", title: "Run failed", message: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function report() {
    setBusy("report");
    try {
      const now = new Date();
      const r = await api<Report>("/api/reports/generate", { method: "POST", body: {
        title: "CloudGuard Security Posture Report", format: "pdf", sections: ["posture", "health", "incidents"],
        start_date: new Date(now.getTime() - 7 * 86400000).toISOString(), end_date: now.toISOString() } });
      await downloadFile(`/api/reports/${r.id}/download`, r.file_name);
      reloadAll();
    } catch (e) {
      toast({ tone: "critical", title: "Report failed", message: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function patch(c: Check, body: Record<string, unknown>) {
    try {
      await api(`/api/compliance/checks/${c.id}`, { method: "PATCH", body });
      checks.reload();
    } catch (e) {
      toast({ tone: "critical", title: "Update failed", message: (e as Error).message });
    }
  }

  if (checks.error) return <ErrorState message={checks.error.message} onRetry={reloadAll} />;
  const p = posture.data;
  const categories = Array.from(new Set((checks.data ?? []).map((c) => c.category)));
  const shown = (checks.data ?? []).filter((c) => !filter || (filter === "problems" ? ["fail", "warning"].includes(c.last_status) : c.last_status === filter));
  const history = [...(runs.data?.items ?? [])].reverse().map((r) => ({ timestamp: r.created_at, score: r.score }));

  return (
    <div className="space-y-6">
      <PageHeader title="Security Audit & Compliance"
        description="Configurable security checklist with automated checks of this installation and manually assessed organisational items."
        actions={<>
          <Button icon={<FileDown className="size-4" />} loading={busy === "report"} onClick={report}>Posture report (PDF)</Button>
          <Button variant="primary" icon={<Play className="size-4" />} loading={busy === "run"} onClick={runNow}>Run checks now</Button>
        </>} />

      <Banner title="CIS-inspired, not a certification" icon={<ShieldCheck className="size-4" />}>
        Checks are basic, read-only verifications inspired by CIS Controls v8 and CIS Benchmarks (Docker, Windows/Linux). Passing them does not mean
        the system is CIS certified or formally benchmarked.
      </Banner>

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <Card className="p-5">
          {!p ? (
            <EmptyState icon={<ClipboardCheck className="size-5" />} title="No posture assessment yet" message="Run the checklist to calculate a score." />
          ) : (
            <div className="flex items-center gap-5">
              <div className="grid size-24 shrink-0 place-items-center rounded-full ring-4" style={{ boxShadow: `inset 0 0 0 4px ${GRADE_COLOR[p.grade]}` }}>
                <div className="text-center">
                  <p className="text-3xl font-bold" style={{ color: GRADE_COLOR[p.grade] }}>{p.grade}</p>
                  <p className="text-xs tabular text-muted">{p.score.toFixed(1)}/100</p>
                </div>
              </div>
              <div className="space-y-1 text-sm">
                <p className="font-semibold text-ink">Security posture</p>
                {(["pass", "warning", "fail", "not_assessed", "not_applicable", "unknown"] as const).filter((k) => p.counts[k]).map((k) => (
                  <p key={k} className="flex items-center justify-between gap-6"><StatusPill status={k} /> <span className="tabular text-ink-2">{p.counts[k]}</span></p>
                ))}
                <p className="pt-1 text-[11px] text-muted">Assessed {timeAgo(p.created_at)} · weighted by severity</p>
              </div>
            </div>
          )}
        </Card>
        <Card>
          <CardHeader title="Posture score history" subtitle={`${runs.data?.total ?? 0} assessments`} />
          <div className="p-4">
            {history.length < 2 ? <EmptyState title="Run the checklist at least twice to see a trend" /> : (
              <TimeSeriesChart data={history} height={170} yDomain={[0, 100]} xFormat={(v) => new Date(v).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                series={[{ key: "score", label: "Posture score", format: (v) => v.toFixed(1) }]} />
            )}
          </div>
        </Card>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
          <Select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-52" aria-label="Filter by result">
            <option value="">All checks</option><option value="problems">Failing or warning</option>
            {Object.keys(STATUS).map((s) => <option key={s} value={s}>{STATUS[s].label}</option>)}
          </Select>
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setAdding(true)}>Add checklist item</Button>
        </div>
        {!checks.data ? <Spinner /> : categories.map((cat) => {
          const items = shown.filter((c) => c.category === cat);
          if (!items.length) return null;
          return (
            <div key={cat}>
              <p className="border-b border-line bg-surface-2 px-5 py-2 text-[11px] font-semibold tracking-wide text-muted uppercase">{titleCase(cat)}</p>
              <ul className="divide-y divide-line">
                {items.map((c) => (
                  <li key={c.id} className={clsx("flex flex-wrap items-start gap-4 px-5 py-3.5", !c.enabled && "opacity-50")}>
                    <Toggle checked={c.enabled} onChange={(v) => patch(c, { enabled: v })} label={`Enable ${c.title}`} />
                    <div className="min-w-[260px] flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-ink">{c.title}</p>
                        <SeverityBadge severity={c.severity} />
                        <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-medium text-muted uppercase">{c.check_type}{c.is_custom ? " · custom" : ""}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-ink-2">{c.description}</p>
                      {c.last_evidence && <p className="mt-1 text-xs text-muted"><span className="font-medium text-ink-2">Evidence:</span> {c.last_evidence}</p>}
                      {["fail", "warning"].includes(c.last_status) && c.remediation && (
                        <p className="mt-1 text-xs text-muted"><span className="font-medium text-ink-2">Remediation:</span> {c.remediation}</p>
                      )}
                      {c.reference && <p className="mt-1 text-[11px] text-muted italic">{c.reference}</p>}
                    </div>
                    <div className="flex flex-col items-end gap-1.5">
                      <StatusPill status={c.last_status} />
                      <span className="text-[11px] text-muted">{c.last_checked_at ? formatDateTime(c.last_checked_at) : "never"}</span>
                      <div className="flex gap-1">
                        {c.check_type === "manual" && <Button size="sm" variant="ghost" onClick={() => setAssessing(c)}>Assess</Button>}
                        {c.is_custom && (
                          <Button size="sm" variant="ghost" aria-label={`Delete ${c.title}`}
                            onClick={async () => { if (confirm("Delete this custom item?")) { await api(`/api/compliance/checks/${c.id}`, { method: "DELETE" }); checks.reload(); } }}>
                            <Trash2 className="size-3.5 text-critical" />
                          </Button>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </Card>
      {assessing && <AssessModal check={assessing} onClose={() => setAssessing(null)} onSaved={checks.reload} />}
      {adding && <AddCheckModal onClose={() => setAdding(false)} onSaved={checks.reload} />}
    </div>
  );
}
