import clsx from "clsx";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowUpFromLine, Boxes, BrainCircuit, Cpu, HardDrive, KeyRound,
  MemoryStick, MonitorCog, Server, ShieldAlert, ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Legend, TimeSeriesChart } from "@/components/charts";
import {
  Badge, Card, CardHeader, EmptyState, ErrorState, Meter, PageHeader, SeverityBadge, Skeleton, StatTile, severityColor, statusTone,
} from "@/components/ui";
import { api } from "@/lib/api";
import { formatBytes, formatPercent, formatRate, timeAgo, titleCase } from "@/lib/format";
import { useApi, useLiveChannel } from "@/lib/hooks";
import type { DashboardSummary, Metric, Severity } from "@/lib/types";

const MAX_POINTS = 180;

export function useLiveMetrics(minutes = 15) {
  const [series, setSeries] = useState<Metric[]>([]);
  const [latest, setLatest] = useState<Metric | null>(null);
  useEffect(() => {
    api<Metric[]>("/api/monitoring/history", { query: { minutes, max_points: MAX_POINTS } })
      .then((h) => {
        setSeries(h);
        if (h.length) setLatest(h[h.length - 1]);
      })
      .catch(() => {});
  }, [minutes]);
  const connected = useLiveChannel("monitoring", (msg) => {
    if (msg.type !== "metric") return;
    const m: Metric = msg.metric;
    setLatest(m);
    setSeries((s) => (s.length && s[s.length - 1].id === m.id ? s : [...s, m].slice(-MAX_POINTS)));
  });
  return { series, latest, connected };
}

const HEALTH_STYLE = {
  healthy: { tone: "good" as const, icon: ShieldCheck, label: "Healthy" },
  degraded: { tone: "warning" as const, icon: AlertTriangle, label: "Degraded" },
  critical: { tone: "critical" as const, icon: ShieldAlert, label: "Critical" },
  unknown: { tone: "neutral" as const, icon: MonitorCog, label: "Unknown" },
};

function HealthCard({ s }: { s: DashboardSummary }) {
  const h = HEALTH_STYLE[s.health.status] ?? HEALTH_STYLE.unknown;
  const Icon = h.icon;
  const ring = { good: "var(--good)", warning: "var(--warning)", critical: "var(--critical)", neutral: "var(--muted)" }[h.tone];
  const score = s.health.score ?? 0;
  return (
    <Card className="flex flex-col">
      <CardHeader title="Infrastructure health" subtitle="Host utilisation and open high-severity alerts" icon={<MonitorCog className="size-4" />} />
      <div className="flex flex-1 items-center gap-5 p-5">
        <div className="relative grid size-24 shrink-0 place-items-center">
          <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90" aria-hidden>
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--surface-3)" strokeWidth="3" />
            <circle cx="18" cy="18" r="15.5" fill="none" stroke={ring} strokeWidth="3" strokeLinecap="round"
              strokeDasharray={`${(score / 100) * 97.4} 97.4`} className="transition-all duration-700" />
          </svg>
          <div className="text-center">
            <p className="text-2xl font-semibold tabular">{s.health.score ?? "—"}</p>
            <p className="text-[10px] uppercase tracking-wide text-muted">score</p>
          </div>
        </div>
        <div className="min-w-0 space-y-2">
          <Badge tone={h.tone}><Icon className="size-3" /> {h.label}</Badge>
          {s.health.issues.length ? (
            <ul className="space-y-1 text-xs text-ink-2">
              {s.health.issues.slice(0, 4).map((i) => <li key={i}>• {i}</li>)}
            </ul>
          ) : (
            <p className="text-xs text-ink-2">All monitored resources are within thresholds.</p>
          )}
        </div>
      </div>
    </Card>
  );
}

function ThreatSummary({ s }: { s: DashboardSummary }) {
  const sev: Severity[] = ["critical", "high", "medium", "low"];
  const max = Math.max(1, ...sev.map((k) => s.alerts.by_severity[k]));
  return (
    <Card>
      <CardHeader title="Threat detection summary" subtitle="Active alerts by severity · last 24 hours activity" icon={<ShieldAlert className="size-4" />}
        actions={<Link to="/alerts" className="text-xs font-medium text-accent hover:underline">Alert Center</Link>} />
      <div className="space-y-2.5 p-5">
        {sev.map((k) => (
          <div key={k} className="grid grid-cols-[84px_1fr_32px] items-center gap-3">
            <SeverityBadge severity={k} />
            <div className="h-2 overflow-hidden rounded-full bg-surface-3">
              <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${(s.alerts.by_severity[k] / max) * 100}%`, background: severityColor[k] }} />
            </div>
            <span className="text-right text-sm font-semibold tabular">{s.alerts.by_severity[k]}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 divide-x divide-line border-t border-line">
        {[
          { label: "Security events", value: s.threats.events_24h, icon: Activity },
          { label: "Failed logins", value: s.threats.failed_logins_24h, icon: KeyRound },
          { label: "ML anomalies", value: s.threats.ml_model_ready ? s.threats.anomalies_24h : "—", icon: BrainCircuit },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="px-4 py-3">
            <p className="flex items-center gap-1.5 text-[11px] text-muted"><Icon className="size-3" /> {label}</p>
            <p className="mt-1 text-lg font-semibold tabular">{value}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Dashboard() {
  const { data: s, error, loading, reload } = useApi<DashboardSummary>("/api/dashboard/summary", { interval: 15000 });
  const { series, latest, connected } = useLiveMetrics(15);
  const m = latest ?? s?.metric ?? null;

  useLiveChannel("alerts", () => reload());

  if (error && !s) return <ErrorState message={error.message} onRetry={reload} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security Operations Dashboard"
        description="Live overview of monitored infrastructure, workloads and detected threats."
        actions={
          <span className="flex items-center gap-2 text-xs text-muted">
            <span className={clsx("size-2 rounded-full", connected ? "live-dot bg-good" : "bg-muted")} />
            {connected ? "Live stream connected" : "Connecting to live stream…"}
          </span>
        }
      />

      {loading && !s ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : s ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Monitored devices" value={s.devices.total} icon={<Server className="size-4" />}
              sub={`${s.devices.hosts} host · ${s.vms.total} VMs · ${s.containers.total} containers`} />
            <StatTile label="Active virtual machines" value={s.vms.available ? `${s.vms.running} / ${s.vms.total}` : "—"} icon={<MonitorCog className="size-4" />}
              sub={s.vms.available ? (s.vms.mode === "mock" ? "Demo mode (simulated)" : "VirtualBox connected") : <Link to="/vms" className="text-warning hover:underline">VirtualBox not connected</Link>} />
            <StatTile label="Running containers" value={s.containers.available ? `${s.containers.running} / ${s.containers.total}` : "—"} icon={<Boxes className="size-4" />}
              tone={s.containers.unhealthy ? "critical" : "accent"}
              sub={s.containers.available ? (s.containers.unhealthy ? `${s.containers.unhealthy} unhealthy` : s.containers.mode === "mock" ? "Demo mode (simulated)" : "Docker Engine connected") : <Link to="/containers" className="text-warning hover:underline">Docker not connected</Link>} />
            <StatTile label="Active security alerts" value={s.alerts.active} icon={<ShieldAlert className="size-4" />}
              tone={s.alerts.by_severity.critical ? "critical" : s.alerts.by_severity.high ? "warning" : "good"}
              sub={`${s.alerts.by_severity.critical} critical · ${s.alerts.by_severity.high} high`} />
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="CPU utilisation" value={formatPercent(m?.cpu_percent)} icon={<Cpu className="size-4" />} sub={`${m?.process_count ?? "—"} processes`}>
              <Meter value={m?.cpu_percent ?? 0} warn={75} crit={90} />
            </StatTile>
            <StatTile label="RAM utilisation" value={formatPercent(m?.memory_percent)} icon={<MemoryStick className="size-4" />} sub={m ? `${formatBytes(m.memory_used)} of ${formatBytes(m.memory_total)}` : "—"}>
              <Meter value={m?.memory_percent ?? 0} warn={80} crit={92} />
            </StatTile>
            <StatTile label="Disk utilisation" value={formatPercent(m?.disk_percent)} icon={<HardDrive className="size-4" />} sub={m ? `${formatBytes(m.disk_used)} of ${formatBytes(m.disk_total)}` : "—"}>
              <Meter value={m?.disk_percent ?? 0} warn={85} crit={95} />
            </StatTile>
            <StatTile label="Network traffic" value={<span className="flex items-baseline gap-3 text-xl">
              <span className="flex items-center gap-1"><ArrowDownToLine className="size-4 text-[var(--series-1)]" />{formatRate(m?.net_recv_rate)}</span>
            </span>} icon={<Activity className="size-4" />}
              sub={<span className="flex items-center gap-1"><ArrowUpFromLine className="size-3 text-[var(--series-2)]" /> {formatRate(m?.net_send_rate)} upload · {m?.connection_count ?? 0} connections</span>} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Resource utilisation" subtitle="Last 15 minutes · live" icon={<Cpu className="size-4" />}
                actions={<Legend series={[{ key: "cpu_percent", label: "CPU" }, { key: "memory_percent", label: "Memory" }, { key: "disk_percent", label: "Disk" }]} />} />
              <div className="p-4">
                {series.length < 2 ? (
                  <EmptyState title="Collecting metrics…" message="The chart fills as samples arrive from the collector." />
                ) : (
                  <TimeSeriesChart data={series} yDomain={[0, 100]} yFormat={(v) => `${v}%`}
                    series={[
                      { key: "cpu_percent", label: "CPU", format: (v) => formatPercent(v) },
                      { key: "memory_percent", label: "Memory", format: (v) => formatPercent(v) },
                      { key: "disk_percent", label: "Disk", format: (v) => formatPercent(v) },
                    ]} />
                )}
              </div>
            </Card>
            <HealthCard s={s} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Network throughput" subtitle="Bytes per second · live" icon={<Activity className="size-4" />}
                actions={<Legend series={[{ key: "net_recv_rate", label: "Download" }, { key: "net_send_rate", label: "Upload" }]} />} />
              <div className="p-4">
                {series.length < 2 ? (
                  <EmptyState title="Collecting metrics…" />
                ) : (
                  <TimeSeriesChart data={series} area yFormat={(v) => formatBytes(v, 0)} height={200}
                    series={[
                      { key: "net_recv_rate", label: "Download", format: formatRate },
                      { key: "net_send_rate", label: "Upload", format: formatRate },
                    ]} />
                )}
              </div>
            </Card>
            <ThreatSummary s={s} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Recent security alerts" subtitle="Most recent open and acknowledged alerts" icon={<ShieldAlert className="size-4" />}
                actions={<Link to="/alerts" className="text-xs font-medium text-accent hover:underline">View all</Link>} />
              {s.alerts.recent.length === 0 ? (
                <EmptyState icon={<ShieldCheck className="size-5 text-good" />} title="No active alerts" message="Detection rules are running. New alerts appear here in real time." />
              ) : (
                <ul className="divide-y divide-line">
                  {s.alerts.recent.map((a) => (
                    <li key={a.id}>
                      <Link to={`/alerts?id=${a.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2">
                        <SeverityBadge severity={a.severity} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-ink">{a.title}</p>
                          <p className="text-xs text-muted">{titleCase(a.category)} · {a.resource_name}{a.occurrences > 1 ? ` · ×${a.occurrences}` : ""}</p>
                        </div>
                        <Badge tone={statusTone(a.status)}>{titleCase(a.status)}</Badge>
                        <span className="hidden w-16 text-right text-xs text-muted sm:block">{timeAgo(a.last_seen_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <CardHeader title="Recent activity" subtitle="Audit trail of user and system actions" icon={<Activity className="size-4" />} />
              {s.activity.length === 0 ? (
                <EmptyState title="No activity to show" message="Audit entries are visible to administrators." />
              ) : (
                <ul className="divide-y divide-line">
                  {s.activity.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate font-mono text-xs text-ink">{a.action}</p>
                        <p className="truncate text-[11px] text-muted">{a.resource_type} {a.resource_id}</p>
                      </div>
                      <span className="shrink-0 text-[11px] text-muted">{timeAgo(a.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
