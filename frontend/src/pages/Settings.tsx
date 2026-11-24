import { BrainCircuit, Gauge, Plug, Unlock, Users } from "lucide-react";
import { useEffect, useState } from "react";
import {
  Badge, Button, Card, CardHeader, ErrorState, Field, Input, Select, Spinner, Table, Toggle, PageHeader, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { IntegrationStatus, Page, Settings, User } from "@/lib/types";
import { DiagnosticsPanel, ThresholdsPanel } from "./SettingsPanels";

function SettingsForm() {
  const toast = useToast();
  const { data, error, reload } = useApi<Settings>("/api/settings");
  const [form, setForm] = useState<Settings | null>(null);
  const [watch, setWatch] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (data) {
      setForm(data);
      setWatch(data.monitoring.process_watchlist.join(", "));
    }
  }, [data]);
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!form) return <Spinner />;

  const setM = (k: keyof Settings["monitoring"], v: any) => setForm({ ...form, monitoring: { ...form.monitoring, [k]: v } });
  const setML = (k: keyof Settings["ml"], v: any) => setForm({ ...form, ml: { ...form.ml, [k]: v } });

  async function save() {
    setErr("");
    const m = form!.monitoring;
    if (m.interval_seconds < 1 || m.interval_seconds > 3600) return setErr("Collection interval must be 1–3600 seconds");
    if (m.container_poll_interval_seconds < 5) return setErr("Container poll interval must be at least 5 seconds");
    if (form!.ml.contamination <= 0 || form!.ml.contamination > 0.5) return setErr("Contamination must be between 0 and 0.5");
    setSaving(true);
    try {
      await api("/api/settings", { method: "PUT", body: { ...form, monitoring: { ...m, process_watchlist: watch.split(",").map((s) => s.trim()).filter(Boolean) } } });
      toast({ tone: "good", title: "Settings saved", message: "New intervals apply from the next collection cycle." });
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? (e.fieldErrors[0] ? `${e.fieldErrors[0].field}: ${e.fieldErrors[0].message}` : e.message) : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title="Monitoring" subtitle="Collection intervals and retention" icon={<Gauge className="size-4" />} />
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <Field label="Metric collection interval (seconds)" htmlFor="s-int"><Input id="s-int" type="number" min={1} max={3600} value={form.monitoring.interval_seconds} onChange={(e) => setM("interval_seconds", Number(e.target.value))} /></Field>
          <Field label="Container / VM poll interval (seconds)" htmlFor="s-cint"><Input id="s-cint" type="number" min={5} value={form.monitoring.container_poll_interval_seconds} onChange={(e) => setM("container_poll_interval_seconds", Number(e.target.value))} /></Field>
          <Field label="Metric retention (days)" htmlFor="s-ret"><Input id="s-ret" type="number" min={1} max={365} value={form.monitoring.retention_days} onChange={(e) => setM("retention_days", Number(e.target.value))} /></Field>
          <div className="sm:col-span-2">
            <Field label="Process watchlist" htmlFor="s-watch" hint="Comma-separated process names that raise a high-severity alert when running (e.g. nc.exe, ncat, xmrig).">
              <Input id="s-watch" value={watch} onChange={(e) => setWatch(e.target.value)} placeholder="nc.exe, ncat" />
            </Field>
          </div>
        </div>
      </Card>
      <Card>
        <CardHeader title="Machine learning" subtitle="Isolation Forest anomaly detection" icon={<BrainCircuit className="size-4" />} />
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <label className="flex items-center gap-3 text-sm text-ink-2 sm:col-span-2"><Toggle checked={form.ml.enabled} onChange={(v) => setML("enabled", v)} label="Enable live scoring" /> Score live metrics with the trained model</label>
          <label className="flex items-center gap-3 text-sm text-ink-2 sm:col-span-2"><Toggle checked={form.ml.auto_alert} onChange={(v) => setML("auto_alert", v)} label="Raise alerts" /> Raise alerts for consecutive anomalies</label>
          <Field label="Contamination (expected outlier share)" htmlFor="s-cont" hint="0.01–0.1 typical"><Input id="s-cont" type="number" step="0.005" min={0.001} max={0.5} value={form.ml.contamination} onChange={(e) => setML("contamination", Number(e.target.value))} /></Field>
          <Field label="Minimum training samples" htmlFor="s-min"><Input id="s-min" type="number" min={50} value={form.ml.min_training_samples} onChange={(e) => setML("min_training_samples", Number(e.target.value))} /></Field>
          <Field label="Z-score guard threshold (σ)" htmlFor="s-z" hint="Flags values this many standard deviations from normal"><Input id="s-z" type="number" step="0.5" min={2} max={20} value={form.ml.z_threshold} onChange={(e) => setML("z_threshold", Number(e.target.value))} /></Field>
        </div>
      </Card>
      <div className="flex items-center justify-end gap-3 xl:col-span-2">
        {err && <p className="text-sm text-critical" role="alert">{err}</p>}
        <Button variant="primary" loading={saving} onClick={save}>Save settings</Button>
      </div>
    </div>
  );
}

function Integrations() {
  const { data } = useApi<{ mode: string; docker: IntegrationStatus; virtualbox: IntegrationStatus; database: string; prometheus: boolean }>("/api/settings/integrations");
  if (!data) return <Spinner />;
  const rows: [string, boolean, string][] = [
    ["Host metrics (psutil)", true, "Always active"],
    ["Docker Engine", data.docker.available, data.docker.available ? `${data.docker.mode === "mock" ? "Mock adapter" : "Engine " + data.docker.version}` : data.docker.message ?? ""],
    ["VirtualBox", data.virtualbox.available, data.virtualbox.available ? `${data.virtualbox.mode === "mock" ? "Mock adapter" : "VBoxManage " + data.virtualbox.version}` : "Not installed"],
    ["Database", true, data.database === "postgresql" ? "PostgreSQL" : "SQLite (local fallback)"],
    ["Prometheus exporter", data.prometheus, data.prometheus ? "Exposed at /metrics" : "Disabled"],
  ];
  return (
    <Card>
      <CardHeader title="Integrations" subtitle={`Integration mode: ${data.mode}`} icon={<Plug className="size-4" />} />
      <ul className="divide-y divide-line">
        {rows.map(([name, ok, detail]) => (
          <li key={name} className="flex items-center justify-between gap-4 px-5 py-3">
            <span className="text-sm text-ink">{name}</span>
            <span className="flex items-center gap-2 text-right text-xs text-muted"><span className="max-w-xs truncate">{detail}</span><Badge tone={ok ? "good" : "warning"} dot>{ok ? "Connected" : "Unavailable"}</Badge></span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function UsersAdmin() {
  const { user: me } = useAuth();
  const toast = useToast();
  const { data, error, reload } = useApi<Page<User>>("/api/users", { query: { page_size: 200 } });
  async function update(u: User, body: Record<string, unknown>, path = "") {
    try {
      await api(`/api/users/${u.id}${path}`, { method: path ? "POST" : "PATCH", body: path ? undefined : body });
      toast({ tone: "good", title: "User updated", message: u.username });
      reload();
    } catch (e) {
      toast({ tone: "critical", title: "Update failed", message: (e as Error).message });
    }
  }
  if (error) return <ErrorState message={error.message} />;
  return (
    <Card>
      <CardHeader title="Users & roles" subtitle="Role-based access control" icon={<Users className="size-4" />} />
      {!data ? <Spinner /> : (
        <Table head={["User", "Role", "Status", "Last login", "Created", ""]}>
          {data.items.map((u) => (
            <tr key={u.id}>
              <td className="px-4 py-3"><p className="text-ink">{u.username}{u.id === me?.id && <span className="ml-1 text-xs text-muted">(you)</span>}</p><p className="text-xs text-muted">{u.email}</p></td>
              <td className="px-4 py-3">
                <Select value={u.role_name} disabled={u.id === me?.id} onChange={(e) => update(u, { role: e.target.value })} className="h-8 w-28 text-xs" aria-label={`Role of ${u.username}`}>
                  <option value="admin">Admin</option><option value="user">User</option>
                </Select>
              </td>
              <td className="px-4 py-3"><Toggle checked={u.is_active} disabled={u.id === me?.id} onChange={(v) => update(u, { is_active: v })} label={`Active ${u.username}`} /></td>
              <td className="px-4 py-3 text-xs text-muted">{formatDateTime(u.last_login_at)}</td>
              <td className="px-4 py-3 text-xs text-muted">{formatDateTime(u.created_at)}</td>
              <td className="px-4 py-3 text-right"><Button size="sm" variant="ghost" icon={<Unlock className="size-3.5" />} onClick={() => update(u, {}, "/unlock")}>Unlock</Button></td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Monitoring intervals, security thresholds, machine learning, integration health, system diagnostics, users and roles. Appearance is set per user in Profile." />
      <SettingsForm />
      <ThresholdsPanel />
      <DiagnosticsPanel />
      <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr]">
        <Integrations />
        <UsersAdmin />
      </div>
    </div>
  );
}
