import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatTime } from "@/lib/format";

export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export interface SeriesDef {
  key: string;
  label: string;
  color?: string;
  format?: (v: number) => string;
}

/* Tooltip: values in ink, a coloured swatch carries identity. */
export function ChartTooltip({ active, payload, label, series, labelFormat }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-xs shadow-xl">
      <p className="mb-1 font-medium text-ink-2">{labelFormat ? labelFormat(label) : label}</p>
      {payload.map((p: any) => {
        const def: SeriesDef | undefined = series?.find((s: SeriesDef) => s.key === p.dataKey);
        return (
          <div key={p.dataKey} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-ink-2">
              <span className="h-0.5 w-3 rounded" style={{ background: p.color }} aria-hidden />
              {def?.label ?? p.name}
            </span>
            <span className="tabular font-semibold text-ink">{def?.format ? def.format(p.value) : p.value}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Legend({ series }: { series: SeriesDef[] }) {
  if (series.length < 2) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
      {series.map((s, i) => (
        <span key={s.key} className="flex items-center gap-1.5">
          <span className="h-0.5 w-3.5 rounded" style={{ background: s.color ?? SERIES[i] }} aria-hidden />
          {s.label}
        </span>
      ))}
    </div>
  );
}

const axisProps = { tickLine: false, axisLine: false, fontSize: 11 } as const;

/** Time-series line chart (single y-axis). Data items must contain `timestamp` (ISO). */
export function TimeSeriesChart({
  data, series, height = 240, yDomain, yFormat, area = false, xKey = "timestamp", xFormat = formatTime,
}: {
  data: Record<string, any>[];
  series: SeriesDef[];
  height?: number;
  yDomain?: [number | string, number | string];
  yFormat?: (v: number) => string;
  area?: boolean;
  xKey?: string;
  xFormat?: (v: string) => string;
}) {
  const Chart = area ? AreaChart : LineChart;
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            {series.map((s, i) => (
              <linearGradient key={s.key} id={`grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color ?? SERIES[i]} stopOpacity={0.28} />
                <stop offset="100%" stopColor={s.color ?? SERIES[i]} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="0" />
          <XAxis dataKey={xKey} tickFormatter={xFormat} minTickGap={48} {...axisProps} />
          <YAxis domain={yDomain ?? ["auto", "auto"]} tickFormatter={yFormat} width={yFormat ? 64 : 36} {...axisProps} />
          <Tooltip
            content={<ChartTooltip series={series} labelFormat={xFormat} />}
            cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
            isAnimationActive={false}
          />
          {series.map((s, i) =>
            area ? (
              <Area key={s.key} type="monotone" dataKey={s.key} stroke={s.color ?? SERIES[i]} strokeWidth={2}
                fill={`url(#grad-${s.key})`} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                isAnimationActive={false} />
            ) : (
              <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.color ?? SERIES[i]} strokeWidth={2} dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} isAnimationActive={false} />
            ),
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}
