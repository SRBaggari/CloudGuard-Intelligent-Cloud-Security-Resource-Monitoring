import clsx from "clsx";
import {
  ArrowLeft, Check, CircleDot, ClipboardList, Hammer, Link2, MessageSquarePlus, Pencil, ShieldAlert, Zap,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Modal, Select, SeverityBadge, Spinner,
  useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, timeAgo, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Incident, IncidentStatus, Page, User } from "@/lib/types";
import { STAGES, STAGE_TONE, useUserNames } from "./Incidents";

const ACTIONS = [
  { v: "manual", l: "Record a manual action", target: "", admin: false },
  { v: "container_stop", l: "Stop container", target: "Container name or ID", admin: true },
  { v: "container_restart", l: "Restart container", target: "Container name or ID", admin: true },
  { v: "vm_stop", l: "Shut down VM", target: "VM UUID", admin: true },
  { v: "user_disable", l: "Disable user account", target: "Username or email", admin: true },
  { v: "user_revoke_sessions", l: "Revoke user sessions", target: "Username or email", admin: true },
  { v: "user_unlock", l: "Unlock user account", target: "Username or email", admin: true },
  { v: "fim_rebaseline", l: "Re-baseline monitored directory", target: "Directory ID or path", admin: true },
];

const EVENT_ICON: Record<string, typeof CircleDot> = {
  created: ShieldAlert, alert_linked: Link2, note: MessageSquarePlus, action: Zap, status_changed: Check,
  reopened: CircleDot, assigned: ClipboardList, severity_changed: ShieldAlert, updated: Pencil,
};

function Stepper({ status }: { status: IncidentStatus }) {
  const idx = STAGES.indexOf(status);
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Incident stage">
      {STAGES.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={clsx("flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1",
            i < idx ? "bg-good/12 text-good ring-good/30" : i === idx ? "bg-accent text-white ring-accent" : "text-muted ring-line-strong")}
            aria-current={i === idx ? "step" : undefined}>
            {i < idx ? <Check className="size-3" /> : <span className="tabular">{i + 1}</span>} {titleCase(s)}
          </span>
          {i < STAGES.length - 1 && <span className={clsx("h-px w-6", i < idx ? "bg-good" : "bg-line-strong")} aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

export default function IncidentDetail() {
  const { id } = useParams();
  const { user, isAdmin } = useAuth();
  const toast = useToast();
  const name = useUserNames();
  const { data: inc, error, loading, reload, setData } = useApi<Incident>(`/api/incidents/${id}`);
  const users = useApi<Page<User>>(isAdmin ? "/api/users" : null, { query: { page_size: 200 } });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const [rootCause, setRootCause] = useState<string | null>(null);
  const [action, setAction] = useState({ type: "manual", target: "", description: "", force: false });
  const [actionError, setActionError] = useState("");

  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (loading || !inc) return <Spinner />;
  const canRespond = isAdmin || inc.assignee_id === user?.id;
  const next: IncidentStatus[] = inc.status === "resolved" ? ["investigating"]
    : STAGES.filter((s) => STAGES.indexOf(s) > STAGES.indexOf(inc.status));

  async function run<T>(key: string, fn: () => Promise<T>, ok: string) {
    setBusy(key);
    try {
      const r = await fn();
      toast({ tone: "good", title: ok });
      return r;
    } catch (e) {
      toast({ tone: "critical", title: "Action failed", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  const setStatus = async (s: IncidentStatus, resolution_summary = "") => {
    const r = await run(s, () => api<Incident>(`/api/incidents/${inc.id}/status`, { method: "POST", body: { status: s, resolution_summary } }),
      s === "investigating" && inc.status === "resolved" ? "Incident reopened" : `Moved to ${s}`);
    if (r) { setData(r); setResolveOpen(false); }
  };

  async function addNote(e: FormEvent) {
    e.preventDefault();
    if (!note.trim()) return;
    if (await run("note", () => api(`/api/incidents/${inc!.id}/notes`, { method: "POST", body: { message: note } }), "Note added")) {
      setNote("");
      reload();
    }
  }

  async function submitAction(e: FormEvent) {
    e.preventDefault();
    setActionError("");
    const def = ACTIONS.find((a) => a.v === action.type)!;
    if (action.type === "manual" && !action.description.trim()) return setActionError("Describe what was done");
    if (def.target && !action.target.trim()) return setActionError(`Enter the ${def.target.toLowerCase()}`);
    if (action.type !== "manual" && !confirm(`Execute "${def.l}" on ${action.target}? This acts on real infrastructure.`)) return;
    setBusy("action");
    try {
      const r = await api<{ status: string; result: string }>(`/api/incidents/${inc!.id}/actions`, {
        method: "POST", body: { action_type: action.type, target: action.target, description: action.description, force: action.force },
      });
      toast({ tone: r.status === "failed" ? "critical" : "good", title: `Action ${r.status}`, message: r.result });
      setAction({ type: action.type, target: "", description: "", force: false });
      reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const patch = (body: Record<string, unknown>, ok: string) =>
    run("patch", () => api<Incident>(`/api/incidents/${inc.id}`, { method: "PATCH", body }), ok).then((r) => r && setData(r));

  return (
    <div className="space-y-6">
      <Link to="/incidents" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> Incidents</Link>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-muted">{inc.reference} · detected {formatDateTime(inc.detected_at)}</p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">{inc.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={inc.severity} />
            <Badge tone={STAGE_TONE[inc.status]} dot>{titleCase(inc.status)}</Badge>
            {inc.is_demo && <Badge tone="info">Demonstration data</Badge>}
            <span className="text-xs text-muted">Assignee: {name(inc.assignee_id)}</span>
          </div>
        </div>
        {canRespond && (
          <div className="flex flex-wrap gap-2">
            {next.map((s) => s === "resolved" ? (
              <Button key={s} variant="primary" onClick={() => { setSummary(inc.resolution_summary); setResolveOpen(true); }}>Resolve…</Button>
            ) : (
              <Button key={s} loading={busy === s} onClick={() => setStatus(s)}>
                {inc.status === "resolved" ? "Reopen" : `Mark ${s}`}
              </Button>
            ))}
          </div>
        )}
      </div>
      <Stepper status={inc.status} />
      {!canRespond && <Banner title="Read-only">Only administrators or the assignee can update this incident.</Banner>}

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="Investigation" icon={<ClipboardList className="size-4" />} />
            <div className="space-y-4 p-5 text-sm">
              <div>
                <p className="text-xs font-medium text-muted">Description</p>
                <p className="mt-1 whitespace-pre-wrap text-ink-2">{inc.description || "No description."}</p>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-muted">Root cause</p>
                  {canRespond && rootCause === null && <button className="text-xs text-accent hover:underline" onClick={() => setRootCause(inc.root_cause)}>Edit</button>}
                </div>
                {rootCause === null ? (
                  <p className="mt-1 whitespace-pre-wrap text-ink-2">{inc.root_cause || "Not yet determined."}</p>
                ) : (
                  <div className="mt-1 space-y-2">
                    <textarea aria-label="Root cause" rows={3} value={rootCause} onChange={(e) => setRootCause(e.target.value)}
                      className="w-full rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-sm focus:border-accent focus:outline-none" />
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="ghost" onClick={() => setRootCause(null)}>Cancel</Button>
                      <Button size="sm" variant="primary" onClick={async () => { await patch({ root_cause: rootCause }, "Root cause saved"); setRootCause(null); }}>Save</Button>
                    </div>
                  </div>
                )}
              </div>
              {inc.resolution_summary && (
                <div className="rounded-lg border border-good/30 bg-good/8 p-3">
                  <p className="text-xs font-medium text-good">Resolution</p>
                  <p className="mt-1 whitespace-pre-wrap text-ink-2">{inc.resolution_summary}</p>
                </div>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="Timeline" subtitle={`${inc.timeline.length} entries · immutable record`} icon={<CircleDot className="size-4" />} />
            {canRespond && (
              <form onSubmit={addNote} className="flex gap-2 border-b border-line p-4">
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an investigation note…" aria-label="Investigation note" maxLength={10000} />
                <Button type="submit" loading={busy === "note"} disabled={!note.trim()} icon={<MessageSquarePlus className="size-4" />}>Add</Button>
              </form>
            )}
            <ol className="relative space-y-0 p-5">
              {[...inc.timeline].reverse().map((e, i, arr) => {
                const Icon = EVENT_ICON[e.event_type] ?? CircleDot;
                return (
                  <li key={e.id} className="relative flex gap-3 pb-5">
                    {i < arr.length - 1 && <span className="absolute top-7 left-3.5 h-[calc(100%-1.25rem)] w-px bg-line-strong" aria-hidden />}
                    <span className={clsx("relative grid size-7 shrink-0 place-items-center rounded-full ring-1",
                      e.event_type === "note" ? "bg-accent/12 text-accent ring-accent/30" : e.event_type === "action" ? "bg-warning/12 text-warning ring-warning/30" : "bg-surface-2 text-muted ring-line-strong")}>
                      <Icon className="size-3.5" />
                    </span>
                    <div className="min-w-0 pt-0.5">
                      <p className={clsx("text-sm whitespace-pre-wrap", e.event_type === "note" ? "text-ink" : "text-ink-2")}>{e.message}</p>
                      <p className="mt-0.5 text-[11px] text-muted" title={formatDateTime(e.created_at)}>
                        {titleCase(e.event_type)} · {name(e.user_id)} · {timeAgo(e.created_at)}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </Card>
        </div>

        <div className="space-y-4">
          {isAdmin && (
            <Card>
              <CardHeader title="Assignment & severity" icon={<Pencil className="size-4" />} />
              <div className="grid gap-3 p-5">
                <Field label="Assignee" htmlFor="d-assignee">
                  <Select id="d-assignee" value={inc.assignee_id ?? ""} onChange={(e) =>
                    patch(e.target.value ? { assignee_id: Number(e.target.value) } : { unassign: true }, "Assignment updated")}>
                    <option value="">Unassigned</option>
                    {users.data?.items.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                  </Select>
                </Field>
                <Field label="Severity" htmlFor="d-sev">
                  <Select id="d-sev" value={inc.severity} onChange={(e) => patch({ severity: e.target.value }, "Severity updated")}>
                    {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
                  </Select>
                </Field>
              </div>
            </Card>
          )}

          {canRespond && inc.status !== "resolved" && (
            <Card>
              <CardHeader title="Response action" subtitle="Executed through CloudGuard's authorised integrations, or recorded" icon={<Hammer className="size-4" />} />
              <form onSubmit={submitAction} className="space-y-3 p-5">
                <Field label="Action" htmlFor="act-type">
                  <Select id="act-type" value={action.type} onChange={(e) => setAction({ ...action, type: e.target.value, target: "" })}>
                    {ACTIONS.filter((a) => isAdmin || !a.admin).map((a) => <option key={a.v} value={a.v}>{a.l}</option>)}
                  </Select>
                </Field>
                {ACTIONS.find((a) => a.v === action.type)!.target && (
                  <Field label={ACTIONS.find((a) => a.v === action.type)!.target} htmlFor="act-target">
                    <Input id="act-target" value={action.target} onChange={(e) => setAction({ ...action, target: e.target.value })} maxLength={255} />
                  </Field>
                )}
                {action.type === "vm_stop" && (
                  <label className="flex items-center gap-2 text-xs text-ink-2">
                    <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={action.force} onChange={(e) => setAction({ ...action, force: e.target.checked })} />
                    Hard power-off (instead of ACPI shutdown)
                  </label>
                )}
                <Field label={action.type === "manual" ? "What was done" : "Note (optional)"} htmlFor="act-desc">
                  <Input id="act-desc" value={action.description} onChange={(e) => setAction({ ...action, description: e.target.value })} maxLength={5000} />
                </Field>
                {actionError && <p className="text-xs text-critical" role="alert">{actionError}</p>}
                <Button type="submit" variant={action.type === "manual" ? "secondary" : "danger"} className="w-full" loading={busy === "action"}>
                  {action.type === "manual" ? "Record action" : "Execute action"}
                </Button>
              </form>
            </Card>
          )}

          <Card>
            <CardHeader title="Response actions" subtitle={`${inc.actions.length} recorded`} icon={<Zap className="size-4" />} />
            {!inc.actions.length ? <EmptyState title="No actions yet" /> : (
              <ul className="divide-y divide-line">
                {[...inc.actions].reverse().map((a) => (
                  <li key={a.id} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-ink">{a.action_type}</span>
                      <Badge tone={a.status === "completed" ? "good" : a.status === "failed" ? "critical" : "neutral"}>{a.status}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-ink-2">{a.result}</p>
                    <p className="mt-0.5 text-[11px] text-muted">{a.mode} · {a.target && `${a.target} · `}{name(a.performed_by_id)} · {timeAgo(a.created_at)}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Linked alerts" subtitle={`${inc.alerts.length} alert(s)`} icon={<Link2 className="size-4" />} />
            {!inc.alerts.length ? <EmptyState title="No linked alerts" /> : (
              <ul className="divide-y divide-line">
                {inc.alerts.map((a) => (
                  <li key={a.id}>
                    <Link to={`/alerts?id=${a.id}`} className="flex items-center gap-2 px-5 py-2.5 hover:bg-surface-2">
                      <SeverityBadge severity={a.severity} />
                      <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{a.title}</span>
                      <Badge tone={a.status === "resolved" ? "good" : "warning"}>{a.status}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Modal open={resolveOpen} onClose={() => setResolveOpen(false)} title={`Resolve ${inc.reference}`}>
        <form onSubmit={(e) => { e.preventDefault(); if (summary.trim()) setStatus("resolved", summary); }} className="space-y-4">
          <Field label="Resolution summary (required)" htmlFor="res-sum" hint="What was done and why the incident is closed. Linked alerts will be resolved.">
            <textarea id="res-sum" rows={4} value={summary} onChange={(e) => setSummary(e.target.value)} autoFocus
              className="w-full rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-sm focus:border-accent focus:outline-none" />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setResolveOpen(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!summary.trim()} loading={busy === "resolved"}>Resolve incident</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
