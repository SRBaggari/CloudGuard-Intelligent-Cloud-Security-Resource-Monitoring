import clsx from "clsx";
import { CheckCircle2, Gauge, Info, TrendingUp, TriangleAlert } from "lucide-react";
import { useState } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Badge, Banner, Card, CardHeader, EmptyState, ErrorState, PageHeader, Select, Spinner, Table } from "@/components/ui";
import { formatBytes, formatPercent, formatRate } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Point { timestamp: string; kind: "measured" | "estimate"; value: number; max?: number; lower?: number; upper?: number }
interface MetricReport {
  metric: string; label: string; unit: "percent" | "bytes_per_second";
  measured: { current: number; average: number; p95: number; max: number; samples: number };
  trend: { slope_per_day: number; r2: number; residual_std: number; fitted_now: number; confidence: "low" | "medium" | "high" };
  thresholds: { warning: number | null; critical: number | null };
  estimate: {
    value_at_horizon: number; days_to_warning: number | null; days_to_critical: number | null;
    capacity?: { total_bytes: number; measured_used_bytes: number; projected_used_bytes: number; required_total_bytes_to_stay_below_warning: number };
  };
  status: "exceeding" | "approaching" | "stable"; summary: string; history: Point[]; forecast: Point[];
}
interface CapacityReport {
  status: "ready" | "insufficient_data"; message: string; method: string; samples: number; span_hours: number;
  bucket_minutes: number; lookback_days: number; horizon_days: number; metrics: MetricReport[];
  containers: { name: string; cpu_percent: number; memory_percent: number; cpu_threshold: number; memory_threshold: number; status: string }[];
}

const STATUS = {
  exceeding: { tone: "critical" as const, icon: TriangleAlert, label: "Exceeding threshold" },
  approaching: { tone: "warning" as const, icon: TrendingUp, label: "Approaching threshold" },
  stable: { tone: "good" as const, icon: CheckCircle2, label: "Stable" },
};
const axis = { tickLine: false, axisLine: false, fontSize: 11 } as const;

function fmt(v: number | null | undefined, unit: MetricReport["unit"]) {
  if (v === null || v === undefined) return "—";
  return unit === "percent" ? formatPercent(v) : formatRate(v);
}

function ForecastChart({ m }: { m: MetricReport }) {
  const data = [
    ...m.history.map((p) => ({ t: new Date(p.timestamp).getTime(), measured: p.value })),
    // bridge: start the estimate at the last measured point so the lines connect
    ...(m.history.length ? [{ t: new Date(m.history[m.history.length - 1].timestamp).getTime(), estimate: m.history[m.history.length - 1].value }] : []),
    ...m.forecast.map((p) => ({ t: new Date(p.timestamp).getTime(), estimate: p.value, band: [p.lower ?? p.value, p.upper ?? p.value] })),
  ];
  const isPct = m.unit === "percent";
  const yFmt = (v: number) => (isPct ? `${v}%` : formatBytes(v, 0));
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} {...axis}
            tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: "short", day: "numeric" })} minTickGap={40} />
          <YAxis {...axis} width={isPct ? 40 : 64} tickFormatter={yFmt} domain={isPct ? [0, 100] : [0, "auto"]} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as { measured?: number; estimate?: number; band?: [number, number] };
              return (
                <div className="rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-xs shadow-xl">
                  <p className="mb-1 font-medium text-ink-2">{new Date(label as number).toLocaleString()}</p>
                  {row.measured !== undefined && <p className="text-ink">Measured: <b className="tabular">{fmt(row.measured, m.unit)}</b></p>}
                  {row.estimate !== undefined && row.band && (
                    <p className="text-ink">Estimate: <b className="tabular">{fmt(row.estimate, m.unit)}</b>
                      <span className="text-muted"> (range {fmt(row.band[0], m.unit)} – {fmt(row.band[1], m.unit)})</span></p>
                  )}
                </div>
              );
            }} />
          <Area dataKey="band" stroke="none" fill="var(--series-2)" fillOpacity={0.14} isAnimationActive={false} connectNulls />
          <Line dataKey="measured" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          <Line dataKey="estimate" stroke="var(--series-2)" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} connectNulls />
          {m.thresholds.warning !== null && (
            <ReferenceLine y={m.thresholds.warning} stroke="var(--warning)" strokeDasharray="3 3"
              label={{ value: `Warning ${fmt(m.thresholds.warning, m.unit)}`, position: "insideTopLeft", fill: "var(--muted)", fontSize: 10 }} />
          )}
          {m.thresholds.critical !== null && (
            <ReferenceLine y={m.thresholds.critical} stroke="var(--critical)" strokeDasharray="3 3"
              label={{ value: `Critical ${fmt(m.thresholds.critical, m.unit)}`, position: "insideTopLeft", fill: "var(--muted)", fontSize: 10 }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function MetricCard({ m, horizon }: { m: MetricReport; horizon: number }) {
  const s = STATUS[m.status];
  const Icon = s.icon;
  return (
    <Card className="animate-fade-up">
      <CardHeader title={m.label} subtitle={m.summary}
        actions={<Badge tone={s.tone}><Icon className="size-3" /> {s.label}</Badge>} />
      <div className="grid gap-4 p-5 lg:grid-cols-[1fr_260px]">
        <div>
          <ForecastChart m={m} />
          <div className="mt-2 flex flex-wrap gap-4 text-xs text-ink-2">
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-[var(--series-1)]" /> Measured (bucket average)</span>
            <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t-2 border-dashed border-[var(--series-2)]" /> Estimate (linear trend)</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-[var(--series-2)] opacity-25" /> ~95% range</span>
          </div>
        </div>
        <div className="space-y-3 text-sm">
          <div className="rounded-lg border border-line p-3">
            <p className="mb-1.5 text-[11px] font-semibold tracking-wide text-ink-2 uppercase">Measured</p>
            {[["Current", m.measured.current], ["Average", m.measured.average], ["95th percentile", m.measured.p95], ["Peak", m.measured.max]].map(([k, v]) => (
              <div key={k as string} className="flex justify-between"><span className="text-muted">{k}</span><span className="tabular text-ink">{fmt(v as number, m.unit)}</span></div>
            ))}
          </div>
          <div className="rounded-lg border border-dashed border-[var(--series-2)]/60 p-3">
            <p className="mb-1.5 text-[11px] font-semibold tracking-wide text-ink-2 uppercase">Estimate · {m.trend.confidence} confidence</p>
            <div className="flex justify-between"><span className="text-muted">Trend</span><span className="tabular text-ink">{m.unit === "percent" ? `${m.trend.slope_per_day >= 0 ? "+" : ""}${m.trend.slope_per_day.toFixed(2)}%/day` : `${formatRate(m.trend.slope_per_day)} per day`}</span></div>
            <div className="flex justify-between"><span className="text-muted">In {horizon} days</span><span className="tabular text-ink">{fmt(m.estimate.value_at_horizon, m.unit)}</span></div>
            <div className="flex justify-between"><span className="text-muted">Warning reached</span><span className="tabular text-ink">{m.estimate.days_to_warning === null ? "not projected" : m.estimate.days_to_warning === 0 ? "now" : `~${m.estimate.days_to_warning.toFixed(0)} days`}</span></div>
            {m.thresholds.critical !== null && (
              <div className="flex justify-between"><span className="text-muted">Critical reached</span><span className="tabular text-ink">{m.estimate.days_to_critical === null ? "not projected" : m.estimate.days_to_critical === 0 ? "now" : `~${m.estimate.days_to_critical.toFixed(0)} days`}</span></div>
            )}
            <div className="flex justify-between"><span className="text-muted">Fit (R²)</span><span className="tabular text-ink">{m.trend.r2.toFixed(2)}</span></div>
            {m.estimate.capacity && (
              <p className="mt-2 border-t border-line pt-2 text-xs text-ink-2">
                Projected use {formatBytes(m.estimate.capacity.projected_used_bytes)} of {formatBytes(m.estimate.capacity.total_bytes)}.
                To stay below the warning threshold you would need about <b className="text-ink">{formatBytes(m.estimate.capacity.required_total_bytes_to_stay_below_warning)}</b>.
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function Capacity() {
  const [lookback, setLookback] = useState(7);
  const [horizon, setHorizon] = useState(30);
  const { data, error, loading, reload } = useApi<CapacityReport>("/api/capacity", { query: { lookback_days: lookback, horizon_days: horizon }, interval: 120000 });

  return (
    <div className="space-y-6">
      <PageHeader title="Capacity Planning"
        description="Utilisation trends from measured history and estimated future requirements for this host."
        actions={<>
          <Select value={lookback} onChange={(e) => setLookback(Number(e.target.value))} className="w-44" aria-label="History window">
            {[1, 7, 30, 90].map((d) => <option key={d} value={d}>History: {d} day{d > 1 ? "s" : ""}</option>)}
          </Select>
          <Select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className="w-44" aria-label="Planning horizon">
            {[7, 30, 90, 180].map((d) => <option key={d} value={d}>Horizon: {d} days</option>)}
          </Select>
        </>} />

      <Banner title="Estimates are not measurements" icon={<Info className="size-4" />}>
        {data?.method ?? "Projections extend the observed linear trend and assume it continues."} Short or noisy history gives low-confidence estimates.
      </Banner>

      {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : data?.status === "insufficient_data" ? (
        <Card><EmptyState icon={<Gauge className="size-5" />} title="Not enough history yet" message={data.message} /></Card>
      ) : data ? (
        <>
          <p className="text-xs text-muted">Based on {data.samples.toLocaleString()} measured samples over {data.span_hours.toFixed(1)} h · {data.bucket_minutes}-minute buckets.</p>
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {data.metrics.map((m) => {
              const s = STATUS[m.status];
              return (
                <a key={m.metric} href={`#cap-${m.metric}`} className={clsx("rounded-xl border bg-surface p-3 hover:bg-surface-2", m.status === "stable" ? "border-line" : m.status === "approaching" ? "border-warning/40" : "border-critical/40")}>
                  <p className="text-xs text-muted">{m.label}</p>
                  <p className="mt-1 text-lg font-semibold tabular">{fmt(m.measured.current, m.unit)} <span className="text-xs font-normal text-muted">measured</span></p>
                  <Badge tone={s.tone}>{s.label}</Badge>
                </a>
              );
            })}
          </div>
          {data.metrics.map((m) => <div key={m.metric} id={`cap-${m.metric}`}><MetricCard m={m} horizon={data.horizon_days} /></div>)}
          <Card>
            <CardHeader title="Containers near their limits" subtitle="Measured CPU/memory at ≥ 80% of the container resource rule thresholds" />
            {!data.containers.length ? <EmptyState title="No containers near their limits" /> : (
              <Table head={["Container", "CPU (measured)", "Memory (measured)", "Status"]}>
                {data.containers.map((c) => (
                  <tr key={c.name}>
                    <td className="px-4 py-2.5 text-ink">{c.name}</td>
                    <td className="px-4 py-2.5 tabular">{formatPercent(c.cpu_percent)} <span className="text-xs text-muted">/ {c.cpu_threshold}%</span></td>
                    <td className="px-4 py-2.5 tabular">{formatPercent(c.memory_percent)} <span className="text-xs text-muted">/ {c.memory_threshold}%</span></td>
                    <td className="px-4 py-2.5"><Badge tone={c.status === "exceeding" ? "critical" : "warning"}>{c.status}</Badge></td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
