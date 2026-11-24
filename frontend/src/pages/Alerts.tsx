import { CheckCheck, CheckCircle2, Eye, Search, ShieldAlert, ShieldCheck, Siren, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Badge, Button, Card, EmptyState, ErrorState, Input, Modal, PageHeader, Pagination, Select, SeverityBadge, Spinner, Table, statusTone, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, timeAgo, titleCase } from "@/lib/format";
import { useApi, useLiveChannel } from "@/lib/hooks";
import type { Alert, IncidentSummary, Page, Severity } from "@/lib/types";
import { CreateIncidentModal } from "./Incidents";

const CATEGORIES = ["authentication", "system", "network", "container", "virtualization", "integrity", "infrastructure", "anomaly"];

function AlertDetail({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data: a, error, reload } = useApi<Alert>(`/api/security/alerts/${id}`);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const linked = useApi<Page<IncidentSummary>>("/api/incidents", { query: { alert_id: id, include_demo: true } });

  async function transition(action: "acknowledge" | "resolve") {
    setBusy(action);
    try {
      await api(`/api/security/alerts/${id}/${action}`, { method: "POST", body: { note } });
      toast({ tone: "good", title: action === "resolve" ? "Alert resolved" : "Alert acknowledged" });
      setNote("");
      reload();
      onChanged();
    } catch (e) {
      toast({ tone: "critical", title: "Action failed", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal open onClose={onClose} title={`Alert #${id}`} wide>
      {error ? <ErrorState message={error.message} /> : !a ? <Spinner /> : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={a.severity} />
            <Badge tone={statusTone(a.status)} dot>{titleCase(a.status)}</Badge>
            <Badge>{titleCase(a.category)}</Badge>
            {a.occurrences > 1 && <Badge tone="info">Seen {a.occurrences}×</Badge>}
          </div>
          <div>
            <h3 className="text-base font-semibold text-ink">{a.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-ink-2">{a.description}</p>
          </div>
          <div className="grid gap-3 text-sm sm:grid-cols-3">
            {[["Affected resource", `${a.resource_type}: ${a.resource_name}`], ["First detected", formatDateTime(a.created_at)], ["Last seen", formatDateTime(a.last_seen_at)],
              ["Acknowledged", a.acknowledged_at ? formatDateTime(a.acknowledged_at) : "—"], ["Resolved", a.resolved_at ? formatDateTime(a.resolved_at) : "—"], ["Rule ID", a.rule_id ?? "—"]].map(([k, v]) => (
              <div key={k as string} className="rounded-lg bg-surface-2 px-3 py-2">
                <p className="text-[11px] text-muted">{k}</p>
                <p className="mt-0.5 truncate text-ink">{v}</p>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-accent/25 bg-accent/6 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold text-ink"><Wrench className="size-4 text-accent" /> Recommended response</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-2">{a.recommended_action || "Investigate the affected resource."}</p>
          </div>
          {Object.keys(a.details ?? {}).length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted">Evidence</p>
              <pre className="max-h-48 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-xs break-all whitespace-pre-wrap text-ink-2">{JSON.stringify(a.details, null, 2)}</pre>
            </div>
          )}
          {a.resolution_note && <p className="text-sm text-ink-2"><span className="text-muted">Note:</span> {a.resolution_note}</p>}
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm">
            <Siren className="size-4 text-muted" />
            <span className="text-ink-2">Incidents:</span>
            {linked.data?.items.length ? linked.data.items.map((i) => (
              <Link key={i.id} to={`/incidents/${i.id}`} className="font-mono text-xs text-accent hover:underline">{i.reference} ({i.status})</Link>
            )) : <span className="text-xs text-muted">not part of an incident</span>}
            {isAdmin && (
              <Button size="sm" variant="ghost" className="ml-auto" icon={<Siren className="size-3.5" />} onClick={() => setCreating(true)}>Create incident</Button>
            )}
          </div>
          {isAdmin && a.status !== "resolved" && (
            <div className="space-y-2 border-t border-line pt-4">
              <Input placeholder="Optional note (investigation findings, remediation taken…)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} aria-label="Note" />
              <div className="flex justify-end gap-2">
                {a.status === "open" && <Button loading={busy === "acknowledge"} icon={<Eye className="size-4" />} onClick={() => transition("acknowledge")}>Acknowledge</Button>}
                <Button variant="primary" loading={busy === "resolve"} icon={<CheckCheck className="size-4" />} onClick={() => transition("resolve")}>Resolve</Button>
              </div>
            </div>
          )}
          {!isAdmin && a.status !== "resolved" && <p className="text-xs text-muted">Only administrators can acknowledge or resolve alerts.</p>}
        </div>
      )}
      {a && <CreateIncidentModal open={creating} onClose={() => setCreating(false)} initialAlerts={[a]} />}
    </Modal>
  );
}

export default function Alerts() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const selectedId = params.get("id") ? Number(params.get("id")) : null;

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [status, severity, category, qDebounced, start, end]);

  const query = {
    status, severity, category, q: qDebounced, page, page_size: 20,
    start: start ? new Date(start).toISOString() : undefined,
    end: end ? new Date(end + "T23:59:59").toISOString() : undefined,
  };
  const { data, error, loading, reload } = useApi<Page<Alert>>("/api/security/alerts", { query });
  const stats = useApi<{ by_status: Record<string, number>; active_by_severity: Record<Severity, number> }>("/api/security/alerts/stats");
  const live = useLiveChannel("alerts", () => {
    reload();
    stats.reload();
  });

  return (
    <div className="space-y-6">
      <PageHeader title="Alert Center" description="Real-time security alerts from the detection engine, with triage and remediation workflow."
        actions={<span className="flex items-center gap-2 text-xs text-muted"><span className={`size-2 rounded-full ${live ? "live-dot bg-good" : "bg-muted"}`} />{live ? "Receiving live alerts" : "Connecting…"}</span>} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {(["critical", "high", "medium", "low"] as Severity[]).map((s) => (
          <button key={s} onClick={() => { setSeverity(severity === s ? "" : s); setStatus("active"); }}
            className={`rounded-xl border bg-surface p-3 text-left transition-colors hover:bg-surface-2 ${severity === s ? "border-accent" : "border-line"}`}>
            <SeverityBadge severity={s} />
            <p className="mt-2 text-xl font-semibold tabular">{stats.data?.active_by_severity[s] ?? "—"}</p>
            <p className="text-[11px] text-muted">active</p>
          </button>
        ))}
        {(["open", "acknowledged", "resolved"] as const).map((s) => (
          <button key={s} onClick={() => setStatus(status === s ? "active" : s)}
            className={`rounded-xl border bg-surface p-3 text-left transition-colors hover:bg-surface-2 ${status === s ? "border-accent" : "border-line"}`}>
            <Badge tone={statusTone(s)} dot>{titleCase(s)}</Badge>
            <p className="mt-2 text-xl font-semibold tabular">{stats.data?.by_status[s] ?? "—"}</p>
            <p className="text-[11px] text-muted">total</p>
          </button>
        ))}
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted" />
            <Input placeholder="Search title, description or resource…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" aria-label="Search alerts" />
          </div>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-36" aria-label="Status">
            <option value="active">Active</option><option value="">All statuses</option><option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option><option value="resolved">Resolved</option>
          </Select>
          <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-36" aria-label="Severity">
            <option value="">All severities</option>{["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
          <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-40" aria-label="Category">
            <option value="">All categories</option>{CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
          </Select>
          <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="w-38" aria-label="From date" />
          <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="w-38" aria-label="To date" />
        </div>
        {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? (
          <EmptyState icon={<ShieldCheck className="size-5 text-good" />} title="No alerts match these filters"
            message={status === "active" ? "There are no active alerts. CloudGuard will notify you in real time when a rule fires." : "Try widening the filters."} />
        ) : (
          <>
            <Table head={["Severity", "Alert", "Category", "Resource", "Status", "Count", "Last seen"]}>
              {data.items.map((a) => (
                <tr key={a.id} onClick={() => setParams({ id: String(a.id) })} className="cursor-pointer hover:bg-surface-2">
                  <td className="px-4 py-3"><SeverityBadge severity={a.severity} /></td>
                  <td className="max-w-md px-4 py-3"><p className="truncate text-ink">{a.title}</p><p className="truncate text-xs text-muted">{a.description}</p></td>
                  <td className="px-4 py-3 text-xs text-ink-2">{titleCase(a.category)}</td>
                  <td className="max-w-[180px] truncate px-4 py-3 text-xs text-ink-2">{a.resource_name}</td>
                  <td className="px-4 py-3"><Badge tone={statusTone(a.status)} dot>{titleCase(a.status)}</Badge></td>
                  <td className="px-4 py-3 tabular text-ink-2">{a.occurrences}</td>
                  <td className="px-4 py-3 text-xs whitespace-nowrap text-muted" title={formatDateTime(a.last_seen_at)}>{timeAgo(a.last_seen_at)}</td>
                </tr>
              ))}
            </Table>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
      {selectedId && <AlertDetail id={selectedId} onClose={() => setParams({})} onChanged={() => { reload(); stats.reload(); }} />}
      <p className="flex items-center gap-1.5 text-xs text-muted"><CheckCircle2 className="size-3.5" /><ShieldAlert className="hidden" />Duplicate detections update the existing alert's occurrence count instead of creating noise.</p>
    </div>
  );
}
