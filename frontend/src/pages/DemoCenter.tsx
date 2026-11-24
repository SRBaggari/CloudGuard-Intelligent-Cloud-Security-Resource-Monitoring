import clsx from "clsx";
import { Cpu, FlaskConical, GraduationCap, Play, RotateCcw, ShieldAlert, Sparkles, Workflow } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, SeverityBadge, Spinner, StatTile, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Alert, Page } from "@/lib/types";
import Capacity from "./Capacity";
import TopologyPage from "./Topology";

interface DemoStatus {
  active: boolean; device: string | null; metrics: number; containers: number; vms: number; alerts: number;
  open_alerts: number; events: number; incidents: number;
  scenarios: { key: string; title: string; description: string; uses_real_rule_engine: boolean }[];
}

export default function DemoCenter() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const status = useApi<DemoStatus>("/api/demo");
  const alerts = useApi<Page<Alert>>("/api/security/alerts", { query: { demo_only: true, page_size: 8 } });
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<"alerts" | "topology" | "capacity">("alerts");
  const [last, setLast] = useState<{ scenario: string; alert_ids?: number[]; incident_id?: number; reference?: string } | null>(null);
  const reload = () => { status.reload(); alerts.reload(); };

  async function call(key: string, path: string, ok: string) {
    setBusy(key);
    try {
      const r = await api<any>(path, { method: "POST" });
      toast({ tone: "good", title: ok });
      if (r.scenario) setLast(r);
      reload();
    } catch (e) {
      toast({ tone: "critical", title: "Demo action failed", message: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  if (status.error) return <ErrorState message={status.error.message} onRetry={reload} />;
  const s = status.data;

  return (
    <div className="space-y-6">
      <PageHeader title="Demo & Learning"
        description="A clearly labelled demonstration environment for presentations and teaching — separate from the real infrastructure CloudGuard monitors."
        actions={isAdmin && s && (s.active ? (
          <Button icon={<RotateCcw className="size-4" />} loading={busy === "reset"}
            onClick={() => confirm("Delete all demonstration data? Real data is not affected.") && call("reset", "/api/demo/reset", "Demonstration data removed")}>
            Reset demo data
          </Button>
        ) : (
          <Button variant="primary" icon={<FlaskConical className="size-4" />} loading={busy === "seed"} onClick={() => call("seed", "/api/demo/seed", "Demonstration environment created")}>
            Create demo environment
          </Button>
        ))} />

      <div className="rounded-xl border-2 border-dashed border-accent/50 bg-accent/6 px-5 py-4">
        <p className="flex items-center gap-2 font-semibold text-ink"><FlaskConical className="size-4 text-accent" /> DEMONSTRATION ENVIRONMENT</p>
        <p className="mt-1 text-sm text-ink-2">
          Everything on this page is <b>sample data</b> stored with a demo flag. Names start with <code className="font-mono">demo</code>, the demo node uses a
          <code className="mx-1 font-mono">.demo</code> hostname and documentation IP ranges. Real dashboards, alert lists, reports, analytics and compliance exclude it, and demo
          resources can never be started, stopped or modified through Docker or VirtualBox.
        </p>
        <p className="mt-2 text-xs text-muted">
          Want the concepts behind it? See <Link to="/about" className="text-accent hover:underline">Project information</Link>.
        </p>
      </div>

      {!s ? <Spinner /> : !s.active ? (
        <Card><EmptyState icon={<GraduationCap className="size-5" />} title="Demo environment not created"
          message={isAdmin ? "Create it to get a demo node with 3 days of sample metrics, 5 containers on 2 networks and 2 VMs." : "Ask an administrator to create the demonstration environment."} /></Card>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatTile label="Demo node" value={<span className="text-base">{s.device}</span>} icon={<Cpu className="size-4" />} sub={`${s.metrics.toLocaleString()} sample metrics`} />
            <StatTile label="Demo containers" value={s.containers} icon={<Workflow className="size-4" />} sub={`${s.vms} demo VMs`} />
            <StatTile label="Demo alerts" value={s.alerts} icon={<ShieldAlert className="size-4" />} tone={s.open_alerts ? "warning" : "good"} sub={`${s.open_alerts} open`} />
            <StatTile label="Demo events" value={s.events} icon={<Sparkles className="size-4" />} />
            <StatTile label="Demo incidents" value={s.incidents} icon={<GraduationCap className="size-4" />} />
          </div>

          <Card>
            <CardHeader title="Scenarios" subtitle="Trigger a scenario, then follow the alert or incident through the normal workflow" icon={<Play className="size-4" />} />
            <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
              {s.scenarios.map((sc) => (
                <div key={sc.key} className="flex flex-col rounded-xl border border-line bg-surface-2 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-ink">{sc.title}</p>
                    <Badge tone={sc.uses_real_rule_engine ? "good" : "neutral"}>{sc.uses_real_rule_engine ? "Real rule engine" : "Sample event"}</Badge>
                  </div>
                  <p className="mt-1.5 flex-1 text-xs leading-relaxed text-ink-2">{sc.description}</p>
                  <Button size="sm" className="mt-3" variant={sc.key === "incident" ? "primary" : "secondary"} disabled={!isAdmin}
                    loading={busy === sc.key} icon={<Play className="size-3.5" />}
                    onClick={() => call(sc.key, `/api/demo/scenarios/${sc.key}`, `Scenario “${sc.title}” triggered`)}>
                    Run scenario
                  </Button>
                </div>
              ))}
            </div>
            {last && (
              <div className="border-t border-line px-5 py-3 text-sm text-ink-2">
                Last run: <b className="text-ink">{titleCase(last.scenario)}</b> —{" "}
                {last.incident_id ? <Link className="text-accent hover:underline" to={`/incidents/${last.incident_id}`}>open {last.reference}</Link>
                  : last.alert_ids?.length ? last.alert_ids.map((id) => <Link key={id} className="mr-2 text-accent hover:underline" to={`/alerts?id=${id}`}>alert #{id}</Link>)
                    : <span>no alert raised (the corresponding rule may be disabled)</span>}
              </div>
            )}
            {!isAdmin && <p className="border-t border-line px-5 py-3 text-xs text-muted">Only administrators can run scenarios.</p>}
          </Card>

          <div className="flex gap-1 border-b border-line">
            {([["alerts", "Demo alerts"], ["topology", "Demo topology"], ["capacity", "Demo capacity forecast"]] as const).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} className={clsx("-mb-px border-b-2 px-3 py-2 text-sm", tab === k ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink")}>{l}</button>
            ))}
          </div>
          {tab === "alerts" && (
            <Card>
              {!alerts.data ? <Spinner /> : !alerts.data.items.length ? <EmptyState title="No demo alerts yet" message="Run a scenario above." /> : (
                <ul className="divide-y divide-line">
                  {alerts.data.items.map((a) => (
                    <li key={a.id}>
                      <Link to={`/alerts?id=${a.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2">
                        <span className="rounded bg-accent/15 px-1 py-0.5 text-[10px] font-bold text-accent">DEMO</span>
                        <SeverityBadge severity={a.severity} />
                        <span className="min-w-0 flex-1 truncate text-sm text-ink">{a.title}</span>
                        <Badge tone={a.status === "resolved" ? "good" : a.status === "acknowledged" ? "warning" : "critical"}>{a.status}</Badge>
                        <span className="w-16 text-right text-xs text-muted">{timeAgo(a.last_seen_at)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          {tab === "topology" && <TopologyPage demo />}
          {tab === "capacity" && <Capacity demo />}
        </>
      )}
      <Banner title="Teaching tip">Run “CPU saturation” and “Container crash”, then “Incident walkthrough” to show detection → alert → incident → response → resolution in one flow.</Banner>
    </div>
  );
}
