import clsx from "clsx";
import { BarChart3, BrainCircuit, Clock, Database, FlaskConical, Info, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import { ChartTooltip, Legend, TimeSeriesChart } from "@/components/charts";
import {
  Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Select, Spinner, StatTile, Table, severityColor, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatPercent, formatTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Severity } from "@/lib/types";

interface Overview {
  days: number; samples: number; bucket_minutes: number;
  timeline: { time: string; cpu_avg: number; cpu_max: number; memory_avg: number; disk_avg: number }[];
  alerts_per_day: ({ date: string } & Record<Severity, number>)[];
  alerts_by_category: Record<string, number>;
  top_resources: { resource: string; count: number }[];
  mean_time_to_resolve_minutes: number | null;
  total_alerts: number;
}

interface AnomalyResp {
  status: "insufficient_data" | "not_trained" | "ready";
  message: string;
  samples_available: number;
  samples_required: number;
  settings: { contamination: number; z_threshold: number; enabled: boolean };
  model: null | {
    version: string; algorithm: string; trained_at: string; n_samples: number; contamination: number; z_threshold: number;
    data_start: string; data_end: string;
    evaluation: { holdout_samples: number; holdout_outlier_rate: number; training_outlier_rate: number; expected_outlier_rate: number; score_p5: number; score_median: number; score_p95: number };
  };
  series: { timestamp: string; score: number; is_anomaly: boolean; cpu_percent: number; memory_percent: number; explanation?: string; detected_by?: string }[];
  anomaly_rate?: number;
  records: { id: number; timestamp: string; score: number; explanation: string; model_version: string }[];
}

const SEVS: Severity[] = ["critical", "high", "medium", "low"];
const axis = { tickLine: false, axisLine: false, fontSize: 11 } as const;

function OverviewSection() {
  const [days, setDays] = useState(7);
  const { data, error, loading, reload } = useApi<Overview>("/api/analytics/overview", { query: { days } });
  const fmtX = (iso: string) => {
    const d = new Date(iso);
    return days > 1 ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.getHours() + "h" : formatTime(iso).slice(0, 5);
  };
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink"><BarChart3 className="size-4 text-muted" /> Security & resource analytics</h2>
        <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-8 w-36 text-xs" aria-label="Period">
          <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </Select>
      </div>
      {error ? <ErrorState message={error.message} onRetry={reload} /> : loading || !data ? <Spinner /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Metric samples" value={data.samples.toLocaleString()} icon={<Database className="size-4" />} sub={`${data.bucket_minutes}-minute aggregation`} />
            <StatTile label="Alerts raised" value={data.total_alerts} icon={<BarChart3 className="size-4" />} tone="warning" />
            <StatTile label="Mean time to resolve" value={data.mean_time_to_resolve_minutes !== null ? `${data.mean_time_to_resolve_minutes} min` : "—"} icon={<Clock className="size-4" />} tone="good" sub="From detection to resolution" />
            <StatTile label="Peak CPU" value={data.timeline.length ? formatPercent(Math.max(...data.timeline.map((t) => t.cpu_max))) : "—"} icon={<Sparkles className="size-4" />} />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Average utilisation" subtitle="Bucketed averages over the period"
                actions={<Legend series={[{ key: "a", label: "CPU" }, { key: "b", label: "Memory" }, { key: "c", label: "Disk" }]} />} />
              <div className="p-4">
                {data.timeline.length < 2 ? <EmptyState title="Not enough data for this period" /> : (
                  <TimeSeriesChart data={data.timeline} xKey="time" xFormat={fmtX} yDomain={[0, 100]} yFormat={(v) => `${v}%`} height={230}
                    series={[{ key: "cpu_avg", label: "CPU", format: (v) => formatPercent(v) }, { key: "memory_avg", label: "Memory", format: (v) => formatPercent(v) }, { key: "disk_avg", label: "Disk", format: (v) => formatPercent(v) }]} />
                )}
              </div>
            </Card>
            <Card>
              <CardHeader title="Alerts per day" subtitle="Stacked by severity"
                actions={<div className="flex gap-3 text-xs text-ink-2">{SEVS.map((s) => <span key={s} className="flex items-center gap-1.5"><span className="size-2 rounded-sm" style={{ background: severityColor[s] }} />{titleCase(s)}</span>)}</div>} />
              <div className="h-[262px] p-4">
                {!data.alerts_per_day.length ? <EmptyState title="No alerts in this period" /> : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.alerts_per_day} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid vertical={false} />
                      <XAxis dataKey="date" {...axis} tickFormatter={(d) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" })} />
                      <YAxis allowDecimals={false} width={30} {...axis} />
                      <Tooltip cursor={{ fill: "var(--surface-2)" }} content={<ChartTooltip series={SEVS.map((s) => ({ key: s, label: titleCase(s) }))} />} />
                      {SEVS.map((s, i) => (
                        <Bar key={s} dataKey={s} stackId="a" fill={severityColor[s]} stroke="var(--surface)" strokeWidth={2} maxBarSize={36}
                          radius={i === 0 ? [4, 4, 0, 0] : 0} isAnimationActive={false} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </Card>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title="Alerts by category" />
              {!Object.keys(data.alerts_by_category).length ? <EmptyState title="No alerts" /> : (
                <ul className="space-y-2.5 p-5">
                  {Object.entries(data.alerts_by_category).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
                    const max = Math.max(...Object.values(data.alerts_by_category));
                    return (
                      <li key={k} className="grid grid-cols-[120px_1fr_36px] items-center gap-3 text-sm">
                        <span className="truncate text-ink-2">{titleCase(k)}</span>
                        <div className="h-2 rounded-full bg-surface-3"><div className="h-full rounded-full bg-[var(--series-1)]" style={{ width: `${(v / max) * 100}%` }} /></div>
                        <span className="text-right font-semibold tabular">{v}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
            <Card>
              <CardHeader title="Most affected resources" subtitle="By detection occurrences" />
              {!data.top_resources.length ? <EmptyState title="No affected resources" /> : (
                <Table head={["Resource", "Detections"]}>
                  {data.top_resources.map((r) => (
                    <tr key={r.resource}><td className="max-w-sm truncate px-4 py-2 font-mono text-xs text-ink">{r.resource}</td><td className="px-4 py-2 tabular">{r.count}</td></tr>
                  ))}
                </Table>
              )}
            </Card>
          </div>
        </>
      )}
    </section>
  );
}

function MLSection() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useApi<AnomalyResp>("/api/analytics/anomalies", { query: { points: 400 }, interval: 30000 });
  const [training, setTraining] = useState(false);

  async function train() {
    setTraining(true);
    try {
      const r = await api<{ n_samples: number; version: string }>("/api/analytics/anomalies/train", { method: "POST" });
      toast({ tone: "good", title: "Model trained", message: `Isolation Forest ${r.version} trained on ${r.n_samples} samples.` });
      reload();
    } catch (e) {
      toast({ tone: "critical", title: "Training failed", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setTraining(false);
    }
  }

  async function removeModel() {
    if (!confirm("Delete the trained model? Anomaly scoring will stop until it is retrained.")) return;
    await api("/api/analytics/anomalies/model", { method: "DELETE" });
    reload();
  }

  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (loading || !data) return <Spinner />;
  const pct = Math.min(100, (data.samples_available / data.samples_required) * 100);
  const anomalies = data.series.filter((s) => s.is_anomaly);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink"><BrainCircuit className="size-4 text-muted" /> Intelligent anomaly detection</h2>
        {isAdmin && (
          <div className="flex gap-2">
            {data.model && <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={removeModel}>Delete model</Button>}
            <Button size="sm" variant="primary" icon={<FlaskConical className="size-3.5" />} loading={training}
              disabled={data.samples_available < data.samples_required} onClick={train}>{data.model ? "Retrain model" : "Train model"}</Button>
          </div>
        )}
      </div>

      {data.status !== "ready" ? (
        <Card className="p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-center">
            <div className="grid size-12 shrink-0 place-items-center rounded-xl bg-accent/12 text-accent"><BrainCircuit className="size-6" /></div>
            <div className="flex-1">
              <p className="font-semibold text-ink">{data.status === "insufficient_data" ? "Building a baseline of normal behaviour" : "Ready to train"}</p>
              <p className="mt-1 text-sm text-ink-2">{data.message}</p>
              <div className="mt-3 h-2 max-w-lg overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-1 text-xs text-muted tabular">{data.samples_available} / {data.samples_required} samples · no predictions are shown until a model is trained on sufficient real data</p>
            </div>
          </div>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Model" value={<span className="font-mono text-lg">{data.model!.version}</span>} icon={<BrainCircuit className="size-4" />} sub={`${data.model!.algorithm}`} />
            <StatTile label="Training samples" value={data.model!.n_samples.toLocaleString()} icon={<Database className="size-4" />} sub={`Trained ${formatDateTime(data.model!.trained_at)}`} />
            <StatTile label="Hold-out outlier rate" value={formatPercent(data.model!.evaluation.holdout_outlier_rate * 100)} icon={<FlaskConical className="size-4" />}
              sub={`expected ≈ ${formatPercent(data.model!.contamination * 100)} (contamination)`} tone="good" />
            <StatTile label="Anomalies in view" value={anomalies.length} tone={anomalies.length ? "warning" : "good"} icon={<Sparkles className="size-4" />}
              sub={`${formatPercent((data.anomaly_rate ?? 0) * 100)} of last ${data.series.length} samples`} />
          </div>
          <Card>
            <CardHeader title="Anomaly score over time" subtitle="Isolation Forest decision score — lower is more abnormal. Red markers are flagged samples."
              actions={<div className="flex gap-4 text-xs text-ink-2"><span className="flex items-center gap-1.5"><span className="h-0.5 w-3.5 bg-[var(--series-1)]" />Score</span><span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-critical" />Anomaly</span></div>} />
            <div className="h-64 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.series.map((s) => ({ ...s, anomaly: s.is_anomaly ? s.score : null }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="timestamp" tickFormatter={formatTime} minTickGap={48} {...axis} />
                  <YAxis width={44} {...axis} tickFormatter={(v) => v.toFixed(2)} />
                  <Tooltip content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const p = payload[0].payload;
                    return (
                      <div className="max-w-xs rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-xs shadow-xl">
                        <p className="font-medium text-ink-2">{formatDateTime(p.timestamp)}</p>
                        <p className="mt-1 text-ink">Score <b className="tabular">{p.score.toFixed(3)}</b> · CPU {formatPercent(p.cpu_percent)} · RAM {formatPercent(p.memory_percent)}</p>
                        {p.is_anomaly && <p className="mt-1 text-critical">{p.explanation}</p>}
                      </div>
                    );
                  }} />
                  <Line dataKey="score" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Scatter dataKey="anomaly" fill="var(--critical)" stroke="var(--surface)" strokeWidth={2} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Detected anomalies" subtitle="Stored anomaly records with explanations" />
              {!data.records.length ? <EmptyState title="No anomalies recorded" message="Live samples are scored as they arrive; anomalous ones are stored here." /> : (
                <Table head={["Time", "Score", "Explanation"]}>
                  {data.records.map((r) => (
                    <tr key={r.id}>
                      <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted">{formatDateTime(r.timestamp)}</td>
                      <td className="px-4 py-2.5 tabular">{r.score.toFixed(3)}</td>
                      <td className="px-4 py-2.5 text-xs text-ink-2">{r.explanation}</td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>
            <Card>
              <CardHeader title="Model evaluation" icon={<Info className="size-4" />} />
              <dl className="divide-y divide-line px-5 py-2 text-sm">
                {[["Training window", `${formatDateTime(data.model!.data_start)} → ${formatDateTime(data.model!.data_end)}`],
                  ["Hold-out samples (last 20%)", data.model!.evaluation.holdout_samples],
                  ["Training outlier rate", formatPercent(data.model!.evaluation.training_outlier_rate * 100, 2)],
                  ["Score p5 / median / p95", `${data.model!.evaluation.score_p5.toFixed(3)} / ${data.model!.evaluation.score_median.toFixed(3)} / ${data.model!.evaluation.score_p95.toFixed(3)}`],
                  ["Statistical guard", `|z| ≥ ${data.model!.z_threshold}σ`]].map(([k, v]) => (
                  <div key={k as string} className="flex justify-between gap-3 py-1.5"><dt className="text-muted">{k}</dt><dd className="text-right text-ink">{v}</dd></div>
                ))}
              </dl>
              <p className="border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">
                Features: CPU, memory, disk, upload/download rates, process and connection counts. Explanations list features more than 2σ from the learned mean. Isolation Forest cannot extrapolate beyond its training range, so a z-score guard also flags extreme values.
              </p>
            </Card>
          </div>
        </>
      )}
      {!data.settings.enabled && <Banner tone="warning" title="Live anomaly scoring is disabled">Enable it in Settings → Machine learning.</Banner>}
    </section>
  );
}

export default function Analytics() {
  const [tab, setTab] = useState<"ml" | "overview">("overview");
  return (
    <div className="space-y-6">
      <PageHeader title="Analytics & Machine Learning" description="Trends across resources and alerts, and unsupervised anomaly detection trained on this host's own history." />
      <div className="flex gap-1 border-b border-line">
        {[{ id: "overview" as const, label: "Analytics overview" }, { id: "ml" as const, label: "Anomaly detection" }].map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={clsx("-mb-px border-b-2 px-3 py-2 text-sm", tab === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink")}>{t.label}</button>
        ))}
      </div>
      {tab === "overview" ? <OverviewSection /> : <MLSection />}
      <Badge tone="neutral">All figures are computed from data collected on this installation.</Badge>
    </div>
  );
}
