import { Cpu, Info, MonitorCog, Play, Power, RefreshCw, Server, TriangleAlert } from "lucide-react";
import { useState } from "react";
import {
  Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, Modal, PageHeader, Select, Spinner, StatTile, Table, statusTone, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { IntegrationStatus, Page, User, VM } from "@/lib/types";

interface ListResp {
  virtualbox: IntegrationStatus & { path?: string };
  items: VM[];
  summary: { total: number; running: number };
}

function VMDetail({ vm, onClose }: { vm: VM; onClose: () => void }) {
  const { data, error } = useApi<{ details: { config: Record<string, string> } & Record<string, any> }>(`/api/vms/${vm.uuid}`);
  return (
    <Modal open onClose={onClose} title={`Virtual machine · ${vm.name}`} wide>
      {error ? <ErrorState message={error.message} /> : !data ? <Spinner /> : (
        <div className="grid gap-x-8 gap-y-0 text-sm sm:grid-cols-2">
          {[["UUID", <span className="font-mono text-xs">{vm.uuid}</span>], ["State", data.details.state], ["Guest OS", data.details.os_type],
            ["Memory", `${data.details.memory_mb} MB`], ["vCPUs", data.details.cpus],
            ...Object.entries(data.details.config ?? {}).map(([k, v]) => [k, v])].map(([k, v], i) => (
            <div key={i} className="flex justify-between gap-3 border-b border-line py-1.5"><span className="text-muted">{k as string}</span><span className="truncate text-right text-ink">{v as React.ReactNode}</span></div>
          ))}
        </div>
      )}
    </Modal>
  );
}

export default function VirtualMachines() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useApi<ListResp>("/api/vms", { query: { refresh: true }, interval: 20000 });
  const users = useApi<Page<User>>(isAdmin ? "/api/users" : null, { query: { page_size: 200 } });
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<VM | null>(null);

  async function act(vm: VM, action: "start" | "stop", force = false) {
    if (action === "stop" && force && !confirm(`Hard power-off "${vm.name}"? Unsaved guest data may be lost.`)) return;
    setBusy(vm.uuid + action);
    try {
      await api(`/api/vms/${vm.uuid}/${action}`, { method: "POST", query: force ? { force: true } : undefined });
      toast({ tone: "good", title: `VM ${action} requested`, message: vm.name });
      reload();
    } catch (e) {
      toast({ tone: "critical", title: `Failed to ${action} ${vm.name}`, message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  async function assign(vm: VM, owner: string) {
    try {
      await api(`/api/vms/${vm.uuid}/owner`, { method: "PUT", body: { owner_id: owner ? Number(owner) : null } });
      reload();
    } catch (e) {
      toast({ tone: "critical", title: "Could not assign owner", message: (e as Error).message });
    }
  }

  if (error && !data) return <ErrorState message={error.message} onRetry={reload} />;
  const vb = data?.virtualbox;

  return (
    <div className="space-y-6">
      <PageHeader title="Virtual Machines" description="Optional VirtualBox integration through a validated VBoxManage wrapper."
        actions={<Button icon={<RefreshCw className="size-4" />} onClick={reload}>Refresh</Button>} />

      {vb && !vb.available && (
        <Banner tone="warning" title="VirtualBox is not connected" icon={<TriangleAlert className="size-4" />}>
          <p>{vb.message}</p>
          <ol className="mt-2 list-decimal space-y-0.5 pl-4">
            <li>Download and install VirtualBox from <a className="text-accent underline" href="https://www.virtualbox.org/wiki/Downloads" target="_blank" rel="noreferrer">virtualbox.org</a>.</li>
            <li>Ensure <code className="font-mono">VBoxManage</code> is on PATH, or set <code className="font-mono">VBOXMANAGE_PATH</code> in <code className="font-mono">backend/.env</code>.</li>
            <li>Restart the CloudGuard backend and refresh this page.</li>
          </ol>
          <p className="mt-2">No VMs are reported as monitored until VirtualBox is connected.</p>
        </Banner>
      )}
      {vb?.mode === "mock" && <Banner tone="info" title="Demo mode" icon={<Info className="size-4" />}>INTEGRATION_MODE=mock — the VMs below are simulated.</Banner>}

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Registered VMs" value={vb?.available ? data?.summary.total : "—"} icon={<Server className="size-4" />} sub={vb?.available ? `VirtualBox ${vb.version}` : "Not connected"} />
        <StatTile label="Running" value={vb?.available ? data?.summary.running : "—"} tone="good" icon={<Play className="size-4" />} />
        <StatTile label="Stopped" value={vb?.available ? (data!.summary.total - data!.summary.running) : "—"} tone="warning" icon={<Power className="size-4" />} />
      </div>

      <Card>
        <CardHeader title="Virtual machines" subtitle={isAdmin ? "All registered VMs" : "VMs assigned to you"} icon={<MonitorCog className="size-4" />} />
        {loading && !data ? <Spinner /> : !data?.items.length ? (
          <EmptyState icon={<Server className="size-5" />} title={vb?.available ? "No virtual machines" : "VirtualBox unavailable"}
            message={vb?.available ? (isAdmin ? "Create a VM in VirtualBox and it will be discovered automatically." : "No VMs have been assigned to you.") : "Install VirtualBox to enable VM monitoring."} />
        ) : (
          <Table head={["Name", "State", "Guest OS", "Resources", "Last seen", ...(isAdmin ? ["Owner"] : []), ""]}>
            {data.items.map((vm) => (
              <tr key={vm.id} className="hover:bg-surface-2">
                <td className="px-4 py-3">
                  <button onClick={() => setSelected(vm)} className="text-left">
                    <span className="block font-medium text-ink hover:text-accent">{vm.name}</span>
                    <span className="font-mono text-[11px] text-muted">{vm.uuid.slice(0, 13)}…</span>
                  </button>
                </td>
                <td className="px-4 py-3"><Badge tone={statusTone(vm.state)} dot>{vm.state}</Badge></td>
                <td className="px-4 py-3 text-ink-2">{vm.os_type}</td>
                <td className="px-4 py-3 text-xs text-ink-2"><span className="inline-flex items-center gap-1"><Cpu className="size-3" />{vm.cpus} vCPU · {vm.memory_mb} MB</span></td>
                <td className="px-4 py-3 text-xs text-muted">{timeAgo(vm.last_seen_at)}</td>
                {isAdmin && (
                  <td className="px-4 py-3">
                    <Select value={vm.owner_id ?? ""} onChange={(e) => assign(vm, e.target.value)} className="h-7 w-32 text-xs" aria-label={`Owner of ${vm.name}`}>
                      <option value="">Unassigned</option>
                      {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                    </Select>
                  </td>
                )}
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    {vm.state === "running" ? (
                      <>
                        <Button size="sm" variant="ghost" loading={busy === vm.uuid + "stop"} onClick={() => act(vm, "stop")} title="ACPI shutdown">Shut down</Button>
                        <Button size="sm" variant="ghost" onClick={() => act(vm, "stop", true)} title="Hard power off"><Power className="size-3.5 text-critical" /></Button>
                      </>
                    ) : (
                      <Button size="sm" variant="ghost" loading={busy === vm.uuid + "start"} onClick={() => act(vm, "start")} icon={<Play className="size-3.5" />}>Start</Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {selected && <VMDetail vm={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
