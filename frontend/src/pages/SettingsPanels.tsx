import clsx from "clsx";
import { Activity, CheckCircle2, CircleAlert, Info, RefreshCw, SlidersHorizontal, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, ErrorState, Input, Spinner, Table, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatBytes, formatDuration, timeAgo, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Rule } from "@/lib/types";

/** Numeric thresholds of the main detection rules, editable in one place. */
const THRESHOLD_FIELDS: Record<string, { label: string; unit: string }[]> = {
  cpu_threshold: [{ label: "warning", unit: "%" }, { label: "critical", unit: "%" }, { label: "consecutive", unit: "samples" }],
  memory_threshold: [{ label: "warning", unit: "%" }, { label: "critical", unit: "%" }, { label: "consecutive", unit: "samples" }],
  disk_threshold: [{ label: "warning", unit: "%" }, { label: "critical", unit: "%" }],
  network_traffic: [{ label: "mbps", unit: "MB/s" }, { label: "consecutive", unit: "samples" }],
  network_connections: [{ label: "max_connections", unit: "conns" }],
  container_resource: [{ label: "cpu", unit: "%" }, { label: "memory", unit: "%" }],
  auth_bruteforce: [{ label: "max_failures", unit: "fails" }, { label: "window_minutes", unit: "min" }, { label: "lockout_minutes", unit: "min" }],
};

function ThresholdRow({ rule, onSaved }: { rule: Rule; onSaved: () => void }) {
  const toast = useToast();
  const fields = THRESHOLD_FIELDS[rule.key];
  const fromRule = () => Object.fromEntries(fields.map((f) => [f.label, String(rule.params[f.label] ?? "")]));
  const [values, setValues] = useState<Record<string, string>>(fromRule);
  const [saving, setSaving] = useState(false);
  useEffect(() => setValues(fromRule()), [rule]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = fields.some((f) => values[f.label] !== String(rule.params[f.label] ?? ""));

  async function save() {
    const params: Record<string, number> = {};
    for (const f of fields) {
      const n = Number(values[f.label]);
      if (values[f.label].trim() === "" || Number.isNaN(n) || n < 0) {
        toast({ tone: "critical", title: `${titleCase(f.label)} must be a positive number` });
        return;
      }
      params[f.label] = n;
    }
    setSaving(true);
    try {
      await api(`/api/security/rules/${rule.id}`, { method: "PATCH", body: { params } });
      toast({ tone: "good", title: "Threshold saved", message: rule.name });
      onSaved();
    } catch (e) {
      toast({ tone: "critical", title: "Could not save", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr>
      <td className="px-4 py-3">
        <p className={clsx("text-sm", rule.enabled ? "text-ink" : "text-muted")}>{rule.name}</p>
        {!rule.enabled && <p className="text-[11px] text-warning">Rule disabled</p>}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-2">
          {fields.map((f) => (
            <label key={f.label} className="flex items-center gap-1.5 text-xs text-muted">
              {titleCase(f.label)}
              <Input type="number" min={0} value={values[f.label] ?? ""} onChange={(e) => setValues({ ...values, [f.label]: e.target.value })}
                className="h-8 w-20 text-xs" aria-label={`${rule.name} ${f.label}`} />
              <span>{f.unit}</span>
            </label>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <Button size="sm" variant={dirty ? "primary" : "ghost"} disabled={!dirty} loading={saving} onClick={save}>Save</Button>
      </td>
    </tr>
  );
}

export function ThresholdsPanel() {
  const { data, error, reload } = useApi<Rule[]>("/api/security/rules");
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  return (
    <Card>
      <CardHeader title="Security thresholds" subtitle="Values used by the detection engine; changes apply to the next evaluation" icon={<SlidersHorizontal className="size-4" />} />
      {!data ? <Spinner /> : (
        <Table head={["Rule", "Thresholds", ""]}>
          {data.filter((r) => r.key in THRESHOLD_FIELDS).map((r) => <ThresholdRow key={r.id} rule={r} onSaved={reload} />)}
        </Table>
      )}
    </Card>
  );
}

interface Diagnostics {
  status: "ok" | "warning" | "error"; checked_at: string;
  checks: { name: string; status: "ok" | "warning" | "error" | "info"; detail: string }[];
  application: { version: string; environment: string; integration_mode: string; python: string; platform: string; uptime_seconds: number; memory_rss_bytes: number; threads: number };
  database: { dialect: string; latency_ms: number; revision: string | null; rows: Record<string, number> };
  background_loops: Record<string, { runs: number; errors: number; last_run: string | null; last_duration_ms: number | null; last_error: string | null; interval_seconds: number; status: string }>;
  storage: { free_bytes: number; total_bytes: number; reports_bytes: number };
  realtime: Record<string, number>;
}

const DIAG = {
  ok: { icon: CheckCircle2, cls: "text-good", label: "OK" },
  warning: { icon: TriangleAlert, cls: "text-warning", label: "Warning" },
  error: { icon: CircleAlert, cls: "text-critical", label: "Error" },
  info: { icon: Info, cls: "text-muted", label: "Info" },
};

export function DiagnosticsPanel() {
  const { data, error, loading, reload } = useApi<Diagnostics>("/api/settings/diagnostics", { interval: 30000 });
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  const overall = data ? DIAG[data.status] : null;
  return (
    <Card>
      <CardHeader title="System health diagnostics" subtitle={data ? `Measured ${timeAgo(data.checked_at)}` : undefined} icon={<Activity className="size-4" />}
        actions={<>
          {overall && <Badge tone={data!.status === "ok" ? "good" : data!.status === "warning" ? "warning" : "critical"}><overall.icon className="size-3" /> {overall.label}</Badge>}
          <Button size="sm" variant="ghost" onClick={reload} aria-label="Run diagnostics again"><RefreshCw className="size-3.5" /></Button>
        </>} />
      {loading && !data ? <Spinner /> : data && (
        <div className="grid gap-4 p-5 xl:grid-cols-2">
          <ul className="space-y-2">
            {data.checks.map((c) => {
              const d = DIAG[c.status];
              return (
                <li key={c.name} className="flex items-start gap-2 text-sm">
                  <d.icon className={clsx("mt-0.5 size-4 shrink-0", d.cls)} aria-label={d.label} />
                  <span><span className="text-ink">{c.name}</span> <span className="text-xs text-muted">— {c.detail}</span></span>
                </li>
              );
            })}
          </ul>
          <div className="space-y-4 text-sm">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
              {[["Version", data.application.version], ["Environment", data.application.environment], ["Integration mode", data.application.integration_mode],
                ["Python", data.application.python], ["Uptime", formatDuration(data.application.uptime_seconds)], ["Memory (RSS)", formatBytes(data.application.memory_rss_bytes)],
                ["Database", `${data.database.dialect} · ${data.database.latency_ms} ms`], ["Migration", data.database.revision ?? "—"],
                ["Metric rows", data.database.rows.metrics?.toLocaleString()], ["Free storage", `${formatBytes(data.storage.free_bytes)} of ${formatBytes(data.storage.total_bytes)}`],
                ["Live sockets", Object.values(data.realtime).reduce((a, b) => a + b, 0)]].map(([k, v]) => (
                <div key={k as string} className="contents"><dt className="text-muted">{k}</dt><dd className="truncate text-ink">{v}</dd></div>
              ))}
            </dl>
            {Object.keys(data.background_loops).length > 0 && (
              <Table head={["Loop", "Runs", "Errors", "Last run", "Duration"]}>
                {Object.entries(data.background_loops).map(([name, l]) => (
                  <tr key={name}>
                    <td className="px-3 py-1.5 text-xs text-ink">{name}</td>
                    <td className="px-3 py-1.5 text-xs tabular">{l.runs}</td>
                    <td className={clsx("px-3 py-1.5 text-xs tabular", l.errors && "text-warning")} title={l.last_error ?? ""}>{l.errors}</td>
                    <td className="px-3 py-1.5 text-xs text-muted">{l.last_run ? timeAgo(l.last_run) : "—"}</td>
                    <td className="px-3 py-1.5 text-xs tabular text-muted">{l.last_duration_ms != null ? `${l.last_duration_ms} ms` : "—"}</td>
                  </tr>
                ))}
              </Table>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
