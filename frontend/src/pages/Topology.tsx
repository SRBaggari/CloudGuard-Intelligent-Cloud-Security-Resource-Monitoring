import clsx from "clsx";
import {
  Box, Boxes, ExternalLink, Maximize2, Minus, Network, Plus, RefreshCw, Server, ServerCog, Workflow, X,
} from "lucide-react";
import { useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { Link } from "react-router-dom";
import { Badge, Banner, Button, Card, EmptyState, ErrorState, PageHeader, Spinner } from "@/components/ui";
import { formatPercent, timeAgo, titleCase } from "@/lib/format";
import { useApi, useLiveChannel } from "@/lib/hooks";

type Health = "critical" | "warning" | "unavailable" | "stopped" | "healthy";
interface TNode { id: string; type: "host" | "docker" | "hypervisor" | "container" | "vm" | "network"; label: string; health: Health; alerts: number; details: Record<string, any>; link: string }
interface TEdge { source: string; target: string; kind: string }
interface Topology {
  nodes: TNode[]; edges: TEdge[]; summary: Record<Health, number>; demo: boolean; generated_at: string;
  integrations: { docker: { available: boolean; message?: string }; virtualbox: { available: boolean; message?: string } };
}

const HEALTH: Record<Health, { color: string; label: string }> = {
  healthy: { color: "var(--good)", label: "Healthy" },
  warning: { color: "var(--warning)", label: "Warning" },
  critical: { color: "var(--critical)", label: "Critical" },
  stopped: { color: "var(--muted)", label: "Stopped" },
  unavailable: { color: "var(--muted)", label: "Unavailable" },
};
const ICON = { host: Server, docker: Boxes, hypervisor: ServerCog, container: Box, vm: Server, network: Network };
const COLUMN: Record<TNode["type"], number> = { host: 0, docker: 1, hypervisor: 1, container: 2, vm: 2, network: 3 };
const COL_X = [90, 330, 590, 850];
const DETAIL_LABEL: Record<string, string> = {
  ip: "IP address", os: "Operating system", cpu_percent: "CPU", memory_percent: "Memory", disk_percent: "Disk",
  last_seen: "Last sample", memory_mb: "Memory (MB)", cpus: "vCPUs", uuid: "UUID", exit_code: "Exit code",
};
const ROW_H = 74;

function layout(nodes: TNode[]) {
  // within each column, keep parents grouped: docker before hypervisor, containers before VMs
  const order = (n: TNode) => ["host", "docker", "container", "hypervisor", "vm", "network"].indexOf(n.type);
  const cols: TNode[][] = [[], [], [], []];
  [...nodes].sort((a, b) => order(a) - order(b) || a.label.localeCompare(b.label)).forEach((n) => cols[COLUMN[n.type]].push(n));
  const rows = Math.max(1, ...cols.map((c) => c.length));
  const height = Math.max(300, rows * ROW_H + 60);
  const pos: Record<string, { x: number; y: number }> = {};
  cols.forEach((col, ci) => {
    const offset = (height - col.length * ROW_H) / 2 + ROW_H / 2;
    col.forEach((n, i) => (pos[n.id] = { x: COL_X[ci], y: offset + i * ROW_H }));
  });
  return { pos, width: 960, height };
}

export default function TopologyPage({ demo = false }: { demo?: boolean }) {
  const { data, error, loading, reload } = useApi<Topology>("/api/topology", { query: { include_demo: demo || undefined }, interval: 10000 });
  useLiveChannel("monitoring", (m) => m.type === "containers.synced" && reload());
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [showNetworks, setShowNetworks] = useState(true);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);

  const nodes = useMemo(() => (data?.nodes ?? []).filter((n) => showNetworks || n.type !== "network"), [data, showNetworks]);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = (data?.edges ?? []).filter((e) => ids.has(e.source) && ids.has(e.target));
  const { pos, width, height } = useMemo(() => layout(nodes), [nodes]);
  const focus = hover ?? selected;
  const neighbours = new Set(focus ? edges.flatMap((e) => (e.source === focus ? [e.target] : e.target === focus ? [e.source] : [])) : []);
  const sel = nodes.find((n) => n.id === selected);
  const isProblem = (n: TNode) => n.health !== "healthy" || n.alerts > 0;

  const onPointerDown = (e: RPointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest("[data-node]")) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (!drag.current) return;
    setView((v) => ({ ...v, x: drag.current!.vx + (e.clientX - drag.current!.x) / v.k, y: drag.current!.vy + (e.clientY - drag.current!.y) / v.k }));
  };
  const zoom = (f: number) => setView((v) => ({ ...v, k: Math.min(2.5, Math.max(0.5, v.k * f)) }));

  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;

  return (
    <div className="space-y-6">
      {!demo && <PageHeader title="Infrastructure Topology"
        description="Live map of monitored hosts, hypervisors, containers, networks and virtual machines. Colour and label show health; badges count active alerts."
        actions={<Button icon={<RefreshCw className="size-4" />} onClick={reload}>Refresh</Button>} />}

      {data && !data.integrations.docker.available && !data.demo && (
        <Banner tone="warning" title="Docker Engine not connected">Containers are not shown because Docker is unavailable. {data.integrations.docker.message}</Banner>
      )}
      {data && !data.integrations.virtualbox.available && !data.demo && (
        <Banner title="VirtualBox not connected">Virtual machines appear here once VirtualBox is installed and detected.</Banner>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-[1fr_320px]">
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-3 text-xs text-ink-2" aria-label="Legend">
              {(Object.keys(HEALTH) as Health[]).map((h) => (
                <span key={h} className="flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full ring-2 ring-offset-0" style={{ background: HEALTH[h].color, opacity: h === "unavailable" ? 0.4 : 1 }} />
                  {HEALTH[h].label} <span className="tabular text-muted">{data?.summary[h] ?? 0}</span>
                </span>
              ))}
            </div>
            <div className="flex items-center gap-3 text-xs text-ink-2">
              <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={showNetworks} onChange={(e) => setShowNetworks(e.target.checked)} /> Networks</label>
              <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} /> Highlight problems</label>
              <div className="flex rounded-lg border border-line-strong">
                <button className="p-1.5 hover:bg-surface-2" onClick={() => zoom(1.2)} aria-label="Zoom in"><Plus className="size-3.5" /></button>
                <button className="p-1.5 hover:bg-surface-2" onClick={() => zoom(1 / 1.2)} aria-label="Zoom out"><Minus className="size-3.5" /></button>
                <button className="p-1.5 hover:bg-surface-2" onClick={() => setView({ x: 0, y: 0, k: 1 })} aria-label="Reset view"><Maximize2 className="size-3.5" /></button>
              </div>
            </div>
          </div>
          {loading && !data ? <Spinner /> : !nodes.length ? (
            <EmptyState icon={<Workflow className="size-5" />} title="Nothing to map yet" message="The host appears after the first metric sample is collected." />
          ) : (
            <div className="overflow-hidden bg-[radial-gradient(circle_at_1px_1px,var(--grid)_1px,transparent_0)] [background-size:22px_22px]">
              <svg viewBox={`0 0 ${width} ${height}`} style={{ aspectRatio: `${width} / ${height}` }}
                className="max-h-[72vh] min-h-[280px] w-full cursor-grab touch-none select-none active:cursor-grabbing"
                role="img" aria-label={`Topology with ${nodes.length} resources`}
                onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => (drag.current = null)} onPointerLeave={() => (drag.current = null)}
                onWheel={(e) => zoom(e.deltaY < 0 ? 1.1 : 1 / 1.1)}>
                <g transform={`translate(${width / 2} ${height / 2}) scale(${view.k}) translate(${-width / 2 + view.x} ${-height / 2 + view.y})`}>
                  {["Hosts", "Platforms", "Workloads", showNetworks ? "Networks" : ""].map((t, i) => t && (
                    <text key={t} x={COL_X[i]} y={22} textAnchor="middle" className="fill-[var(--muted)] text-[11px] font-semibold tracking-wider uppercase">{t}</text>
                  ))}
                  {edges.map((e, i) => {
                    const a = pos[e.source], b = pos[e.target];
                    const active = focus && (e.source === focus || e.target === focus);
                    const mx = (a.x + b.x) / 2;
                    return (
                      <path key={i} d={`M${a.x + 22} ${a.y} C${mx} ${a.y}, ${mx} ${b.y}, ${b.x - 22} ${b.y}`} fill="none"
                        stroke={active ? "var(--accent)" : "var(--axis)"} strokeWidth={active ? 2 : 1.2}
                        strokeDasharray={e.kind === "attached" ? "4 4" : undefined}
                        opacity={focus && !active ? 0.25 : 1} />
                    );
                  })}
                  {nodes.map((n) => {
                    const p = pos[n.id];
                    const Icon = ICON[n.type];
                    const dim = (focus && n.id !== focus && !neighbours.has(n.id)) || (onlyProblems && !isProblem(n));
                    const color = HEALTH[n.health].color;
                    return (
                      <g key={n.id} data-node transform={`translate(${p.x} ${p.y})`} opacity={dim ? 0.3 : 1}
                        className="cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-[var(--accent)]"
                        onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onClick={() => setSelected(n.id)}
                        role="button" tabIndex={0} aria-label={`${titleCase(n.type)} ${n.label}: ${HEALTH[n.health].label}${n.alerts ? `, ${n.alerts} active alerts` : ""}`}
                        onKeyDown={(e) => e.key === "Enter" && setSelected(n.id)}>
                        <circle r={22} fill="var(--surface)" stroke={color} strokeWidth={selected === n.id ? 4 : 2.5}
                          strokeDasharray={n.health === "unavailable" ? "3 3" : undefined} />
                        {n.health === "critical" && <circle r={27} fill="none" stroke={color} strokeWidth={1.5} opacity={0.5} className="animate-pulse" />}
                        <g transform="translate(-9 -9)" color="var(--ink-2)"><Icon width={18} height={18} /></g>
                        <text y={38} textAnchor="middle" className="fill-[var(--ink)] text-[11px] font-medium">{n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label}</text>
                        <text y={51} textAnchor="middle" className="text-[10px]" fill={n.health === "healthy" ? "var(--muted)" : color}>{HEALTH[n.health].label}</text>
                        {n.alerts > 0 && (
                          <g transform="translate(17 -19)">
                            <circle r={9} fill="var(--critical)" stroke="var(--surface)" strokeWidth={2} />
                            <text y={3.5} textAnchor="middle" className="fill-white text-[10px] font-bold">{n.alerts > 9 ? "9+" : n.alerts}</text>
                          </g>
                        )}
                      </g>
                    );
                  })}
                </g>
              </svg>
            </div>
          )}
          {data && <p className="border-t border-line px-4 py-2 text-[11px] text-muted">Updated {timeAgo(data.generated_at)} · drag to pan, scroll or use the buttons to zoom · click a node for details</p>}
        </Card>

        <Card className="h-fit">
          {!sel ? (
            <EmptyState icon={<Workflow className="size-5" />} title="Select a resource" message="Click any node to see its details and connections." />
          ) : (
            <div>
              <div className="flex items-start justify-between gap-2 border-b border-line px-5 py-4">
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold tracking-wide text-muted uppercase">{titleCase(sel.type)}</p>
                  <p className="truncate font-semibold text-ink">{sel.label}</p>
                  <div className="mt-2 flex gap-2">
                    <Badge tone={sel.health === "healthy" ? "good" : sel.health === "critical" ? "critical" : sel.health === "warning" ? "warning" : "neutral"} dot>{HEALTH[sel.health].label}</Badge>
                    {sel.alerts > 0 && <Badge tone="critical">{sel.alerts} active alert{sel.alerts > 1 ? "s" : ""}</Badge>}
                  </div>
                </div>
                <button onClick={() => setSelected(null)} className="rounded-md p-1 text-muted hover:bg-surface-2" aria-label="Close details"><X className="size-4" /></button>
              </div>
              <dl className="divide-y divide-line px-5 py-2 text-sm">
                {Object.entries(sel.details).filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 py-1.5">
                    <dt className="text-muted">{DETAIL_LABEL[k] ?? titleCase(k)}</dt>
                    <dd className="truncate text-right text-ink">
                      {Array.isArray(v) ? v.join(", ") || "—" : k.endsWith("_percent") ? formatPercent(Number(v)) : k === "last_seen" ? timeAgo(String(v)) : String(v)}
                    </dd>
                  </div>
                ))}
              </dl>
              <div className="border-t border-line px-5 py-3">
                <p className="mb-1.5 text-xs font-medium text-muted">Connections ({edges.filter((e) => e.source === sel.id || e.target === sel.id).length})</p>
                <ul className="space-y-1">
                  {edges.filter((e) => e.source === sel.id || e.target === sel.id).map((e, i) => {
                    const other = nodes.find((n) => n.id === (e.source === sel.id ? e.target : e.source))!;
                    return (
                      <li key={i}>
                        <button onClick={() => setSelected(other.id)} className={clsx("flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-xs hover:bg-surface-2")}>
                          <span className="truncate text-ink-2">{e.source === sel.id ? `${e.kind} →` : `← ${e.kind}`} {other.label}</span>
                          <span style={{ color: HEALTH[other.health].color }}>{HEALTH[other.health].label}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
              {sel.link && (
                <div className="border-t border-line px-5 py-3">
                  <Link to={sel.link} className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">Open in module <ExternalLink className="size-3.5" /></Link>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
