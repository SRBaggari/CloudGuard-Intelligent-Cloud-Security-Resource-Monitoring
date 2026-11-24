import { Boxes, FileText, Info, Play, RefreshCw, RotateCw, Square, TriangleAlert } from "lucide-react";
import { useState } from "react";
import {
  Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, Modal, PageHeader, Select, Spinner, StatTile, Table, statusTone, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatPercent, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Container, IntegrationStatus, Page, User } from "@/lib/types";

interface ListResp {
  docker: IntegrationStatus & { api_version?: string; os?: string };
  items: Container[];
  summary: { total: number; running: number; stopped: number; unhealthy: number };
}

function ContainerDetail({ c, onClose }: { c: Container; onClose: () => void }) {
  const [tab, setTab] = useState<"details" | "logs">("details");
  const [tail, setTail] = useState(200);
  const detail = useApi<{ details: Record<string, any> }>(`/api/containers/${c.container_id}`);
  const logs = useApi<{ logs: string }>(tab === "logs" ? `/api/containers/${c.container_id}/logs` : null, { query: { tail } });
  const d = detail.data?.details;
  return (
    <Modal open onClose={onClose} title={`Container · ${c.name}`} wide>
      <div className="mb-4 flex gap-1 border-b border-line">
        {(["details", "logs"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-3 py-2 text-sm capitalize ${tab === t ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>{t}</button>
        ))}
      </div>
      {tab === "details" ? (
        detail.error ? <ErrorState message={detail.error.message} /> : !d ? <Spinner /> : (
          <div className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            {[
              ["ID", <span className="font-mono text-xs">{d.short_id}</span>], ["Image", d.image], ["Status", d.status], ["Health", d.health],
              ["Restarts", d.restart_count], ["Exit code", d.exit_code ?? "—"], ["Created", d.created ? new Date(d.created).toLocaleString() : "—"],
              ["Started", d.started_at ? new Date(d.started_at).toLocaleString() : "—"], ["Networks", (d.networks ?? []).join(", ") || "—"],
              ["Restart policy", d.restart_policy?.Name ?? "—"], ["Memory limit", d.memory_limit ? formatBytes(d.memory_limit) : "unlimited"],
              ["Privileged", d.privileged ? <Badge tone="critical">Yes</Badge> : "No"],
            ].map(([k, v], i) => (
              <div key={i} className="flex justify-between gap-3 border-b border-line py-1.5"><span className="text-muted">{k}</span><span className="truncate text-right text-ink">{v}</span></div>
            ))}
            <div className="sm:col-span-2">
              <p className="mt-2 mb-1 text-xs font-medium text-muted">Command</p>
              <pre className="overflow-x-auto rounded-lg bg-surface-2 p-2 font-mono text-xs">{JSON.stringify(d.command)}</pre>
              <p className="mt-3 mb-1 text-xs font-medium text-muted">Ports</p>
              <pre className="overflow-x-auto rounded-lg bg-surface-2 p-2 font-mono text-xs">{JSON.stringify(d.ports, null, 1)}</pre>
              <p className="mt-3 mb-1 text-xs font-medium text-muted">Environment variable names <span className="font-normal">(values hidden — they may contain secrets)</span></p>
              <p className="font-mono text-xs text-ink-2">{(d.env_keys ?? []).join(", ") || "—"}</p>
            </div>
          </div>
        )
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <Select value={tail} onChange={(e) => setTail(Number(e.target.value))} className="w-36" aria-label="Lines">
              {[100, 200, 500, 1000].map((n) => <option key={n} value={n}>Last {n} lines</option>)}
            </Select>
            <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={logs.reload}>Refresh</Button>
          </div>
          {logs.error ? <ErrorState message={logs.error.message} /> : !logs.data ? <Spinner /> : (
            <pre className="max-h-[50vh] overflow-auto rounded-lg bg-[#060b16] p-3 font-mono text-[11px] leading-relaxed text-[#c3d0e6]">{logs.data.logs || "(no log output)"}</pre>
          )}
        </div>
      )}
    </Modal>
  );
}

export default function Containers() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [state, setState] = useState("");
  const { data, error, loading, reload } = useApi<ListResp>("/api/containers", { query: { state, refresh: true }, interval: 15000 });
  const users = useApi<Page<User>>(isAdmin ? "/api/users" : null, { query: { page_size: 200 } });
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<Container | null>(null);

  async function act(c: Container, action: "start" | "stop" | "restart") {
    setBusy(c.container_id + action);
    try {
      await api(`/api/containers/${c.container_id}/${action}`, { method: "POST" });
      toast({ tone: "good", title: `Container ${action} requested`, message: c.name });
      reload();
    } catch (e) {
      toast({ tone: "critical", title: `Failed to ${action} ${c.name}`, message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function assign(c: Container, owner: string) {
    try {
      await api(`/api/containers/${c.container_id}/owner`, { method: "PUT", body: { owner_id: owner ? Number(owner) : null } });
      toast({ tone: "good", title: "Owner updated", message: c.name });
      reload();
    } catch (e) {
      toast({ tone: "critical", title: "Could not assign owner", message: (e as Error).message });
    }
  }

  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;
  const docker = data?.docker;

  return (
    <div className="space-y-6">
      <PageHeader title="Docker Containers" description="Containers discovered from the local Docker Engine. Actions are authorised, validated and audited."
        actions={<Button icon={<RefreshCw className="size-4" />} onClick={reload}>Refresh</Button>} />

      {docker && !docker.available && (
        <Banner tone="warning" title="Docker Engine is not connected" icon={<TriangleAlert className="size-4" />}>
          {docker.message} Install <a className="text-accent underline" href="https://docs.docker.com/get-docker/" target="_blank" rel="noreferrer">Docker Desktop</a> (Windows/macOS) or Docker Engine (Linux), start it, then refresh. CloudGuard keeps working without it.
        </Banner>
      )}
      {docker?.mode === "mock" && (
        <Banner tone="info" title="Demo mode" icon={<Info className="size-4" />}>INTEGRATION_MODE=mock — the containers below are simulated for demonstration/testing.</Banner>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Total containers" value={data?.summary.total ?? "—"} icon={<Boxes className="size-4" />} sub={docker?.available ? `Engine ${docker.version ?? ""}` : "Engine unavailable"} />
        <StatTile label="Running" value={data?.summary.running ?? "—"} tone="good" icon={<Play className="size-4" />} />
        <StatTile label="Stopped" value={data?.summary.stopped ?? "—"} tone="warning" icon={<Square className="size-4" />} />
        <StatTile label="Unhealthy" value={data?.summary.unhealthy ?? "—"} tone={data?.summary.unhealthy ? "critical" : "good"} icon={<TriangleAlert className="size-4" />} />
      </div>

      <Card>
        <CardHeader title="Containers" subtitle={isAdmin ? "All containers" : "Containers assigned to you"} icon={<Boxes className="size-4" />}
          actions={
            <Select value={state} onChange={(e) => setState(e.target.value)} className="h-8 w-36 text-xs" aria-label="Filter by state">
              <option value="">All states</option>
              {["running", "exited", "paused", "restarting", "removed"].map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          } />
        {loading && !data ? <Spinner /> : !data?.items.length ? (
          <EmptyState icon={<Boxes className="size-5" />} title="No containers to show"
            message={!docker?.available ? "Connect Docker Engine to discover containers." : isAdmin ? "No containers found. Start one with `docker run` and it will appear here." : "An administrator has not assigned any containers to you yet."} />
        ) : (
          <Table head={["Name", "Image", "Status", "Health", "CPU", "Memory", "Network I/O", "Restarts", ...(isAdmin ? ["Owner"] : []), ""]}>
            {data.items.map((c) => (
              <tr key={c.id} className="hover:bg-surface-2">
                <td className="px-4 py-3">
                  <button className="text-left" onClick={() => setSelected(c)}>
                    <span className="block font-medium text-ink hover:text-accent">{c.name}</span>
                    <span className="font-mono text-[11px] text-muted">{c.container_id.slice(0, 12)}</span>
                  </button>
                </td>
                <td className="max-w-[180px] truncate px-4 py-3 text-xs text-ink-2">{c.image}</td>
                <td className="px-4 py-3"><Badge tone={statusTone(c.status)} dot>{c.status}</Badge>{c.exit_code ? <span className="ml-1 text-[11px] text-muted">({c.exit_code})</span> : null}</td>
                <td className="px-4 py-3">{c.health === "none" ? <span className="text-xs text-muted">—</span> : <Badge tone={statusTone(c.health)}>{c.health}</Badge>}</td>
                <td className="px-4 py-3 tabular">{c.status === "running" ? formatPercent(c.cpu_percent) : "—"}</td>
                <td className="px-4 py-3 tabular">{c.status === "running" ? <>{formatBytes(c.memory_usage)} <span className="text-xs text-muted">({formatPercent(c.memory_percent)})</span></> : "—"}</td>
                <td className="px-4 py-3 text-xs tabular text-ink-2">↓{formatBytes(c.net_rx_bytes)} ↑{formatBytes(c.net_tx_bytes)}</td>
                <td className="px-4 py-3 tabular">{c.restart_count}</td>
                {isAdmin && (
                  <td className="px-4 py-3">
                    <Select value={c.owner_id ?? ""} onChange={(e) => assign(c, e.target.value)} className="h-7 w-32 text-xs" aria-label={`Owner of ${c.name}`}>
                      <option value="">Unassigned</option>
                      {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                    </Select>
                  </td>
                )}
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    {c.status === "removed" ? <span className="text-xs text-muted">seen {timeAgo(c.last_seen_at)}</span> : c.status === "running" ? (
                      <>
                        <Button size="sm" variant="ghost" title="Restart" aria-label={`Restart ${c.name}`} loading={busy === c.container_id + "restart"} onClick={() => act(c, "restart")}><RotateCw className="size-3.5" /></Button>
                        <Button size="sm" variant="ghost" title="Stop" aria-label={`Stop ${c.name}`} loading={busy === c.container_id + "stop"} onClick={() => act(c, "stop")}><Square className="size-3.5" /></Button>
                      </>
                    ) : (
                      <Button size="sm" variant="ghost" title="Start" aria-label={`Start ${c.name}`} loading={busy === c.container_id + "start"} onClick={() => act(c, "start")}><Play className="size-3.5" /></Button>
                    )}
                    {c.status !== "removed" && <Button size="sm" variant="ghost" title="Details & logs" aria-label={`Details for ${c.name}`} onClick={() => setSelected(c)}><FileText className="size-3.5" /></Button>}
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {selected && <ContainerDetail c={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
