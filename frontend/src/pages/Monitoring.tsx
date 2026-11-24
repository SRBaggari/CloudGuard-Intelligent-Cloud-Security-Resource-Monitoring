import clsx from "clsx";
import { Activity, Cpu, Network, RefreshCw, Server, TerminalSquare } from "lucide-react";
import { useState } from "react";
import { Legend, TimeSeriesChart } from "@/components/charts";
import {
  Badge, Button, Card, CardHeader, EmptyState, ErrorState, Meter, PageHeader, Spinner, Table, statusTone,
} from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDuration, formatPercent, formatRate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Health, Metric, Process } from "@/lib/types";
import { useLiveMetrics } from "./Dashboard";

const RANGES = [
  { label: "15m", minutes: 15 }, { label: "1h", minutes: 60 }, { label: "6h", minutes: 360 },
  { label: "24h", minutes: 1440 }, { label: "7d", minutes: 10080 },
];

interface SystemResp {
  device: { name: string; hostname: string; ip_address: string; os_info: string };
  metric: Metric;
  info: Record<string, any>;
  health: Health;
}

function InfoRow({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-sm">
      <dt className="text-muted">{k}</dt>
      <dd className="truncate text-right text-ink">{v}</dd>
    </div>
  );
}

export default function Monitoring() {
  const { isAdmin } = useAuth();
  const [range, setRange] = useState(60);
  const live = useLiveMetrics(15);
  const sys = useApi<SystemResp>("/api/monitoring/system", { interval: 30000 });
  const hist = useApi<Metric[]>("/api/monitoring/history", { query: { minutes: range, max_points: 400 }, interval: range <= 60 ? 15000 : 60000 });
  const net = useApi<any>("/api/monitoring/network", { interval: 15000 });
  const [sort, setSort] = useState<"cpu" | "memory">("cpu");
  const procs = useApi<Process[]>(isAdmin ? "/api/monitoring/processes" : null, { query: { sort, limit: 15 }, interval: 10000 });

  const data = range === 15 ? live.series : hist.data ?? [];
  const m = live.latest ?? sys.data?.metric;
  const fmtX = (iso: string) => {
    const d = new Date(iso);
    return range > 1440 ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit" })
      : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  };

  if (sys.error && !sys.data) return <ErrorState message={sys.error.message} onRetry={sys.reload} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Infrastructure Monitoring"
        description="Real host telemetry collected with psutil, stored historically and evaluated against detection rules."
        actions={
          <div className="flex rounded-lg border border-line-strong bg-surface p-0.5" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r.minutes} onClick={() => setRange(r.minutes)}
                className={clsx("rounded-md px-3 py-1 text-xs font-medium", range === r.minutes ? "bg-accent text-white" : "text-ink-2 hover:text-ink")}>
                {r.label}
              </button>
            ))}
          </div>
        }
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader title="Host" subtitle={sys.data?.device.name} icon={<Server className="size-4" />}
            actions={sys.data && <Badge tone={statusTone(sys.data.health.status)} dot>{sys.data.health.status}</Badge>} />
          {!sys.data ? <Spinner /> : (
            <dl className="divide-y divide-line px-5 py-2">
              <InfoRow k="Hostname" v={sys.data.info.hostname} />
              <InfoRow k="Operating system" v={`${sys.data.info.os} ${sys.data.info.os_release}`} />
              <InfoRow k="Architecture" v={sys.data.info.architecture} />
              <InfoRow k="CPU cores" v={`${sys.data.info.cpu_physical_cores} physical / ${sys.data.info.cpu_logical_cores} logical`} />
              <InfoRow k="CPU frequency" v={sys.data.info.cpu_freq_mhz ? `${sys.data.info.cpu_freq_mhz} MHz` : "—"} />
              <InfoRow k="Memory" v={formatBytes(sys.data.info.memory_total)} />
              <InfoRow k="IP address" v={<span className="font-mono text-xs">{sys.data.info.ip_address}</span>} />
              <InfoRow k="Uptime" v={formatDuration(sys.data.info.uptime_seconds)} />
              <InfoRow k="Booted" v={new Date(sys.data.info.boot_time).toLocaleString()} />
            </dl>
          )}
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader title="Current utilisation" subtitle="Updated live from the collector" icon={<Activity className="size-4" />} />
          <div className="grid gap-x-8 gap-y-5 p-5 sm:grid-cols-2">
            {[
              { label: "CPU", v: m?.cpu_percent, sub: `${m?.process_count ?? "—"} processes`, warn: 75, crit: 90 },
              { label: "Memory", v: m?.memory_percent, sub: m ? `${formatBytes(m.memory_used)} / ${formatBytes(m.memory_total)}` : "", warn: 80, crit: 92 },
              { label: "Disk (system volume)", v: m?.disk_percent, sub: m ? `${formatBytes(m.disk_used)} / ${formatBytes(m.disk_total)}` : "", warn: 85, crit: 95 },
            ].map((x) => (
              <div key={x.label}>
                <div className="flex items-baseline justify-between">
                  <span className="text-sm text-ink-2">{x.label}</span>
                  <span className="text-lg font-semibold tabular">{formatPercent(x.v)}</span>
                </div>
                <Meter value={x.v ?? 0} warn={x.warn} crit={x.crit} />
                <p className="mt-1 text-xs text-muted">{x.sub}</p>
              </div>
            ))}
            <div>
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-ink-2">Network</span>
                <span className="text-sm font-semibold tabular">↓ {formatRate(m?.net_recv_rate)} · ↑ {formatRate(m?.net_send_rate)}</span>
              </div>
              <p className="mt-3 text-xs text-muted">
                Total since boot: {formatBytes(m?.net_bytes_recv)} received, {formatBytes(m?.net_bytes_sent)} sent · {m?.connection_count ?? 0} open connections
              </p>
            </div>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="CPU, memory and disk" subtitle={`Historical metrics · ${RANGES.find((r) => r.minutes === range)?.label}`} icon={<Cpu className="size-4" />}
          actions={<Legend series={[{ key: "c", label: "CPU" }, { key: "m", label: "Memory" }, { key: "d", label: "Disk" }]} />} />
        <div className="p-4">
          {hist.loading && !data.length ? <Spinner /> : data.length < 2 ? (
            <EmptyState title="Not enough history yet" message="Keep CloudGuard running; metrics are collected at the configured interval." />
          ) : (
            <TimeSeriesChart data={data} yDomain={[0, 100]} yFormat={(v) => `${v}%`} height={280} xFormat={fmtX}
              series={[
                { key: "cpu_percent", label: "CPU", format: (v) => formatPercent(v) },
                { key: "memory_percent", label: "Memory", format: (v) => formatPercent(v) },
                { key: "disk_percent", label: "Disk", format: (v) => formatPercent(v) },
              ]} />
          )}
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Network throughput" subtitle="Bytes per second" icon={<Network className="size-4" />}
            actions={<Legend series={[{ key: "r", label: "Download" }, { key: "s", label: "Upload" }]} />} />
          <div className="p-4">
            {data.length < 2 ? <EmptyState title="Not enough history yet" /> : (
              <TimeSeriesChart data={data} area height={220} xFormat={fmtX} yFormat={(v) => formatBytes(v, 0)}
                series={[{ key: "net_recv_rate", label: "Download", format: formatRate }, { key: "net_send_rate", label: "Upload", format: formatRate }]} />
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title="Network interfaces" subtitle="Adapters reported by the operating system" icon={<Network className="size-4" />} />
          {!net.data ? <Spinner /> : (
            <Table head={["Interface", "Status", "IPv4", "Received", "Sent"]}>
              {net.data.interfaces.slice(0, 8).map((i: any) => (
                <tr key={i.name}>
                  <td className="max-w-[180px] truncate px-4 py-2.5 text-ink">{i.name}</td>
                  <td className="px-4 py-2.5"><Badge tone={i.is_up ? "good" : "neutral"} dot>{i.is_up ? "Up" : "Down"}</Badge></td>
                  <td className="px-4 py-2.5 font-mono text-xs text-ink-2">{i.ipv4.join(", ") || "—"}</td>
                  <td className="px-4 py-2.5 tabular text-ink-2">{formatBytes(i.bytes_recv)}</td>
                  <td className="px-4 py-2.5 tabular text-ink-2">{formatBytes(i.bytes_sent)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      {isAdmin && (
        <div className="grid gap-4 xl:grid-cols-3">
          <Card className="xl:col-span-2">
            <CardHeader title="Running processes" subtitle="Top processes on the host (administrators only)" icon={<TerminalSquare className="size-4" />}
              actions={
                <>
                  <div className="flex rounded-lg border border-line-strong p-0.5">
                    {(["cpu", "memory"] as const).map((k) => (
                      <button key={k} onClick={() => setSort(k)} className={clsx("rounded-md px-2.5 py-0.5 text-xs", sort === k ? "bg-surface-3 text-ink" : "text-muted")}>
                        {k === "cpu" ? "CPU" : "Memory"}
                      </button>
                    ))}
                  </div>
                  <Button size="sm" variant="ghost" onClick={procs.reload} aria-label="Refresh processes"><RefreshCw className="size-3.5" /></Button>
                </>
              } />
            {!procs.data ? <Spinner /> : (
              <Table head={["PID", "Name", "User", "CPU", "Memory", "RSS"]}>
                {procs.data.map((p) => (
                  <tr key={p.pid} className="hover:bg-surface-2">
                    <td className="px-4 py-2 font-mono text-xs text-muted">{p.pid}</td>
                    <td className="max-w-[220px] truncate px-4 py-2 text-ink">{p.name}</td>
                    <td className="max-w-[160px] truncate px-4 py-2 text-xs text-ink-2">{p.username || "—"}</td>
                    <td className="px-4 py-2 tabular">{formatPercent(p.cpu_percent)}</td>
                    <td className="px-4 py-2 tabular">{formatPercent(p.memory_percent)}</td>
                    <td className="px-4 py-2 tabular text-ink-2">{formatBytes(p.memory_rss)}</td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
          <Card>
            <CardHeader title="Connections" subtitle="Socket states and top remote peers" icon={<Network className="size-4" />} />
            {!net.data?.connections ? <Spinner /> : !net.data.connections.available ? (
              <EmptyState title="Connection details unavailable" message={net.data.connections.reason} />
            ) : (
              <div className="space-y-4 p-5">
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(net.data.connections.by_status as Record<string, number>).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                    <Badge key={k}>{k.replace("_", " ")}: {v}</Badge>
                  ))}
                </div>
                <div>
                  <p className="mb-2 text-xs font-medium text-muted">Top remote addresses</p>
                  <ul className="space-y-1">
                    {net.data.connections.top_remote.slice(0, 8).map((r: any) => (
                      <li key={r.ip} className="flex justify-between font-mono text-xs"><span className="text-ink-2">{r.ip}</span><span className="tabular text-ink">{r.connections}</span></li>
                    ))}
                  </ul>
                </div>
                <p className="text-xs text-muted">Listening ports: <span className="font-mono text-ink-2">{net.data.connections.listening.slice(0, 20).join(", ") || "none"}</span></p>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
