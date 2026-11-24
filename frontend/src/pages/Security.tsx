import clsx from "clsx";
import { KeyRound, ListChecks, Pencil, ScrollText, Search } from "lucide-react";
import { useEffect, useState } from "react";
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Pagination, Select, SeverityBadge, Spinner, Table, Toggle, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { LoginAttempt, Page, Rule, SecurityEvent, Severity } from "@/lib/types";

function RuleEditor({ rule, onClose, onSaved }: { rule: Rule; onClose: () => void; onSaved: () => void }) {
  const [severity, setSeverity] = useState<Severity>(rule.severity);
  const [params, setParams] = useState<Record<string, string>>(Object.fromEntries(Object.entries(rule.params).map(([k, v]) => [k, String(v)])));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function save() {
    const parsed: Record<string, number | string> = {};
    for (const [k, v] of Object.entries(params)) {
      if (typeof rule.params[k] === "number") {
        const n = Number(v);
        if (v.trim() === "" || Number.isNaN(n) || n < 0) return setError(`"${titleCase(k)}" must be a positive number`);
        parsed[k] = n;
      } else parsed[k] = v;
    }
    setSaving(true);
    try {
      await api(`/api/security/rules/${rule.id}`, { method: "PATCH", body: { severity, params: parsed } });
      toast({ tone: "good", title: "Rule updated", message: rule.name });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open onClose={onClose} title={`Edit rule · ${rule.name}`}>
      <div className="space-y-4">
        <p className="text-sm text-ink-2">{rule.description}</p>
        <Field label="Severity" htmlFor="sev">
          <Select id="sev" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
            {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
        </Field>
        {Object.keys(params).length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(params).map(([k, v]) => (
              <Field key={k} label={titleCase(k)} htmlFor={`p-${k}`}>
                <Input id={`p-${k}`} value={v} onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))} />
              </Field>
            ))}
          </div>
        )}
        {error && <p className="text-sm text-critical" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={saving} onClick={save}>Save changes</Button>
        </div>
      </div>
    </Modal>
  );
}

function RulesTab() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload, setData } = useApi<Rule[]>("/api/security/rules");
  const [editing, setEditing] = useState<Rule | null>(null);

  async function toggle(r: Rule, enabled: boolean) {
    setData((rs) => rs?.map((x) => (x.id === r.id ? { ...x, enabled } : x)) ?? null);
    try {
      await api(`/api/security/rules/${r.id}`, { method: "PATCH", body: { enabled } });
    } catch (e) {
      toast({ tone: "critical", title: "Update failed", message: (e as Error).message });
      reload();
    }
  }

  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (loading || !data) return <Spinner />;
  const groups = Array.from(new Set(data.map((r) => r.category)));
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <Card key={g}>
          <div className="border-b border-line px-5 py-3 text-xs font-semibold uppercase tracking-wide text-muted">{titleCase(g)}</div>
          <ul className="divide-y divide-line">
            {data.filter((r) => r.category === g).map((r) => (
              <li key={r.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
                <Toggle checked={r.enabled} onChange={(v) => toggle(r, v)} label={`Enable ${r.name}`} disabled={!isAdmin} />
                <div className="min-w-[260px] flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className={clsx("text-sm font-medium", r.enabled ? "text-ink" : "text-muted")}>{r.name}</p>
                    <SeverityBadge severity={r.severity} />
                  </div>
                  <p className="mt-1 text-xs text-ink-2">{r.description}</p>
                  <p className="mt-2 inline-block rounded-md bg-surface-2 px-2 py-1 font-mono text-[11px] text-ink-2">IF {r.condition}</p>
                  <p className="mt-2 text-xs text-muted"><span className="font-medium text-ink-2">Response:</span> {r.recommended_response}</p>
                </div>
                {isAdmin && <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(r)}>Tune</Button>}
              </li>
            ))}
          </ul>
        </Card>
      ))}
      {editing && <RuleEditor rule={editing} onClose={() => setEditing(null)} onSaved={reload} />}
    </div>
  );
}

function EventsTab() {
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  useEffect(() => { const t = setTimeout(() => setQd(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => setPage(1), [category, qd]);
  const { data, error, loading, reload } = useApi<Page<SecurityEvent>>("/api/security/events", { query: { page, page_size: 25, category, q: qd }, interval: 20000 });
  return (
    <Card>
      <div className="flex flex-wrap gap-2 border-b border-line p-3">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search events…" className="pl-8" aria-label="Search events" />
        </div>
        <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-44" aria-label="Category">
          <option value="">All categories</option>
          {["authentication", "system", "network", "container", "virtualization", "integrity", "infrastructure", "anomaly"].map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
        </Select>
      </div>
      {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? (
        <EmptyState title="No security events" message="Events are recorded for every detection and authentication failure." />
      ) : (
        <>
          <Table head={["Time", "Severity", "Type", "Message", "Resource"]}>
            {data.items.map((e) => (
              <tr key={e.id} className="hover:bg-surface-2">
                <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted">{formatDateTime(e.created_at)}</td>
                <td className="px-4 py-2.5"><SeverityBadge severity={e.severity} /></td>
                <td className="px-4 py-2.5 font-mono text-xs text-ink-2">{e.event_type}</td>
                <td className="max-w-lg px-4 py-2.5 text-ink">{e.message}</td>
                <td className="max-w-[160px] truncate px-4 py-2.5 text-xs text-ink-2">{e.resource}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}

function LoginsTab() {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const { data, error, loading, reload } = useApi<Page<LoginAttempt>>("/api/security/login-attempts", { query: { page, page_size: 25, success: filter }, interval: 20000 });
  return (
    <Card>
      <div className="flex gap-2 border-b border-line p-3">
        <Select value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }} className="w-48" aria-label="Result">
          <option value="">All attempts</option><option value="false">Failed only</option><option value="true">Successful only</option>
        </Select>
      </div>
      {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? <EmptyState title="No login attempts recorded" /> : (
        <>
          <Table head={["Time", "Result", "Account", "Source IP", "Reason", "Client"]}>
            {data.items.map((a) => (
              <tr key={a.id}>
                <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted">{formatDateTime(a.created_at)}</td>
                <td className="px-4 py-2.5"><Badge tone={a.success ? "good" : "critical"} dot>{a.success ? "Success" : "Failed"}</Badge></td>
                <td className="px-4 py-2.5 text-ink">{a.identifier}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-ink-2">{a.ip_address}</td>
                <td className="px-4 py-2.5 text-xs text-ink-2">{titleCase(a.reason)}</td>
                <td className="max-w-[240px] truncate px-4 py-2.5 text-xs text-muted">{a.user_agent}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}

export default function Security() {
  const { isAdmin } = useAuth();
  const [tab, setTab] = useState<"rules" | "events" | "logins">("rules");
  const tabs = [
    { id: "rules" as const, label: "Detection rules", icon: ListChecks },
    ...(isAdmin ? [{ id: "events" as const, label: "Security events", icon: ScrollText }, { id: "logins" as const, label: "Login attempts", icon: KeyRound }] : []),
  ];
  return (
    <div className="space-y-6">
      <PageHeader title="Detection & Events" description="Transparent, configurable rule-based detection. Every rule states exactly what it detects — no black-box malware claims." />
      <div className="flex gap-1 border-b border-line">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={clsx("-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm", tab === id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink")}>
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>
      {tab === "rules" ? <RulesTab /> : tab === "events" ? <EventsTab /> : <LoginsTab />}
    </div>
  );
}
