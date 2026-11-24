import clsx from "clsx";
import { Plus, Search, Siren } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Pagination, Select, SeverityBadge, Spinner,
  StatTile, Table, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, timeAgo, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Alert, Incident, IncidentStatus, IncidentSummary, Page, Severity, User } from "@/lib/types";

export const STAGES: IncidentStatus[] = ["detected", "acknowledged", "investigating", "resolved"];
export const STAGE_TONE = { detected: "critical", acknowledged: "warning", investigating: "info", resolved: "good" } as const;

/** Usernames for display (admins can list users; others see ids). */
export function useUserNames() {
  const { isAdmin, user } = useAuth();
  const { data } = useApi<Page<User>>(isAdmin ? "/api/users" : null, { query: { page_size: 200 } });
  return (id: number | null | undefined) => {
    if (!id) return "—";
    if (user && id === user.id) return `${user.username} (you)`;
    return data?.items.find((u) => u.id === id)?.username ?? `user #${id}`;
  };
}

export function CreateIncidentModal({ open, onClose, initialAlerts = [] }: { open: boolean; onClose: () => void; initialAlerts?: Alert[] }) {
  const navigate = useNavigate();
  const toast = useToast();
  const users = useApi<Page<User>>(open ? "/api/users" : null, { query: { page_size: 200 } });
  const active = useApi<Page<Alert>>(open ? "/api/security/alerts" : null, { query: { status: "active", page_size: 50 } });
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<"" | Severity>("");
  const [assignee, setAssignee] = useState("");
  const [alertIds, setAlertIds] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setAlertIds(initialAlerts.map((a) => a.id));
      setTitle(initialAlerts.length === 1 ? initialAlerts[0].title : "");
      setError("");
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length < 3) return setError("Enter a title of at least 3 characters");
    if (!severity && !alertIds.length) return setError("Choose a severity or link at least one alert");
    setSaving(true);
    try {
      const inc = await api<Incident>("/api/incidents", {
        method: "POST",
        body: { title: title.trim(), description, severity: severity || undefined, alert_ids: alertIds,
          assignee_id: assignee ? Number(assignee) : undefined },
      });
      toast({ tone: "good", title: `${inc.reference} created`, message: inc.title });
      onClose();
      navigate(`/incidents/${inc.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const alertOptions = [...initialAlerts, ...(active.data?.items ?? []).filter((a) => !initialAlerts.some((i) => i.id === a.id))];
  return (
    <Modal open={open} onClose={onClose} title="Create incident" wide>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Title" htmlFor="inc-title"><Input id="inc-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} autoFocus /></Field>
        <Field label="Description" htmlFor="inc-desc">
          <textarea id="inc-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Severity" htmlFor="inc-sev" hint="Leave automatic to inherit the highest linked alert severity">
            <Select id="inc-sev" value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")}>
              <option value="">Automatic (from alerts)</option>
              {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
          </Field>
          <Field label="Assignee" htmlFor="inc-assignee">
            <Select id="inc-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">Unassigned</option>
              {users.data?.items.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </Select>
          </Field>
        </div>
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-ink-2">Linked alerts ({alertIds.length})</legend>
          <div className="max-h-52 space-y-1 overflow-y-auto rounded-lg border border-line p-2">
            {active.loading && !alertOptions.length ? <Spinner /> : !alertOptions.length ? (
              <p className="p-2 text-xs text-muted">No active alerts. You can still create a manual incident with a severity.</p>
            ) : alertOptions.map((a) => (
              <label key={a.id} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2">
                <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={alertIds.includes(a.id)}
                  onChange={(e) => setAlertIds((ids) => (e.target.checked ? [...ids, a.id] : ids.filter((x) => x !== a.id)))} />
                <SeverityBadge severity={a.severity} />
                <span className="truncate text-ink-2">#{a.id} {a.title}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {error && <p className="text-sm text-critical" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={saving}>Create incident</Button>
        </div>
      </form>
    </Modal>
  );
}

export default function Incidents() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const name = useUserNames();
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState("");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  useEffect(() => { const t = setTimeout(() => setQd(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => setPage(1), [status, severity, qd, mine]);
  const { data, error, loading, reload } = useApi<Page<IncidentSummary>>("/api/incidents", {
    query: { status, severity, q: qd, assigned_to_me: mine || undefined, page, page_size: 20 }, interval: 30000,
  });
  const stats = useApi<{ by_status: Record<IncidentStatus, number>; mean_time_to_acknowledge_minutes: number | null; mean_time_to_resolve_minutes: number | null }>(
    "/api/incidents/stats", { interval: 30000 });

  return (
    <div className="space-y-6">
      <PageHeader title="Incident Response" description="Group related alerts into incidents and track investigation, response actions and resolution."
        actions={isAdmin && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>New incident</Button>} />

      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {STAGES.map((s) => (
          <button key={s} onClick={() => setStatus(status === s ? "open" : s)}
            className={clsx("rounded-xl border bg-surface p-3 text-left transition-colors hover:bg-surface-2", status === s ? "border-accent" : "border-line")}>
            <Badge tone={STAGE_TONE[s]} dot>{titleCase(s)}</Badge>
            <p className="mt-2 text-xl font-semibold tabular">{stats.data?.by_status[s] ?? "—"}</p>
          </button>
        ))}
        <StatTile label="Mean time to acknowledge" value={stats.data?.mean_time_to_acknowledge_minutes != null ? `${stats.data.mean_time_to_acknowledge_minutes} min` : "—"} />
        <StatTile label="Mean time to resolve" value={stats.data?.mean_time_to_resolve_minutes != null ? `${stats.data.mean_time_to_resolve_minutes} min` : "—"} />
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search incidents…" className="pl-8" aria-label="Search incidents" />
          </div>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-40" aria-label="Status">
            <option value="open">Open</option><option value="">All</option>
            {STAGES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
          <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-40" aria-label="Severity">
            <option value="">All severities</option>
            {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me
          </label>
        </div>
        {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? (
          <EmptyState icon={<Siren className="size-5" />} title="No incidents match"
            message={isAdmin ? "Create an incident from the Alert Center or with “New incident”." : "Incidents assigned to you will appear here."} />
        ) : (
          <>
            <Table head={["Incident", "Severity", "Stage", "Assignee", "Detected", "Updated"]}>
              {data.items.map((i) => (
                <tr key={i.id} className="cursor-pointer hover:bg-surface-2" onClick={() => navigate(`/incidents/${i.id}`)}>
                  <td className="max-w-md px-4 py-3">
                    <p className="font-mono text-[11px] text-muted">{i.reference}{i.is_demo && <span className="ml-2"><Badge tone="info">Demo</Badge></span>}</p>
                    <p className="truncate text-ink">{i.title}</p>
                  </td>
                  <td className="px-4 py-3"><SeverityBadge severity={i.severity} /></td>
                  <td className="px-4 py-3"><Badge tone={STAGE_TONE[i.status]} dot>{titleCase(i.status)}</Badge></td>
                  <td className="px-4 py-3 text-xs text-ink-2">{name(i.assignee_id)}</td>
                  <td className="px-4 py-3 text-xs whitespace-nowrap text-muted">{formatDateTime(i.detected_at)}</td>
                  <td className="px-4 py-3 text-xs whitespace-nowrap text-muted">{timeAgo(i.updated_at)}</td>
                </tr>
              ))}
            </Table>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <CreateIncidentModal open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}
