import { Boxes, Cloud, GraduationCap, Layers, ServerCog, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader, PageHeader, Table } from "@/components/ui";

function Concept({ icon, title, children, inCloudGuard }: { icon: ReactNode; title: string; children: ReactNode; inCloudGuard: ReactNode }) {
  return (
    <Card>
      <CardHeader title={title} icon={icon} />
      <div className="grid gap-5 p-5 lg:grid-cols-[1.3fr_1fr]">
        <div className="space-y-3 text-sm leading-relaxed text-ink-2">{children}</div>
        <div className="rounded-xl border border-accent/25 bg-accent/6 p-4 text-sm leading-relaxed text-ink-2">
          <p className="mb-1.5 text-[11px] font-semibold tracking-wide text-accent uppercase">In CloudGuard</p>
          {inCloudGuard}
        </div>
      </div>
    </Card>
  );
}

const MODULES = [
  ["Dashboard & Infrastructure", "Real-time host telemetry (psutil), history, WebSocket streaming", "Cloud monitoring / observability"],
  ["Topology", "Graph of hosts, hypervisors, containers, networks and VMs with health", "Infrastructure visibility"],
  ["Capacity Planning", "Linear trend on measured history, threshold ETAs, clearly labelled estimates", "Elasticity & capacity management"],
  ["Containers", "Docker Engine API: discovery, stats, logs, lifecycle actions", "Containerisation"],
  ["Virtual Machines", "VirtualBox via a whitelisted VBoxManage wrapper", "Virtualisation"],
  ["Alert Center & Detection rules", "Transparent rules: brute force, thresholds, crashes, integrity", "Security monitoring (SIEM-style)"],
  ["Incidents", "Detected → acknowledged → investigating → resolved, timeline, response actions", "Incident response (NIST SP 800-61 lifecycle)"],
  ["File Integrity", "SHA-256 baselines of selected directories", "Host-based intrusion detection (FIM)"],
  ["Analytics & ML", "Isolation Forest anomaly detection with explanations", "Machine learning for security analytics"],
  ["Compliance & Audit Log", "CIS-inspired checklist, posture score, audit trail", "Governance, risk & compliance"],
  ["Notifications & Reports", "Per-user notifications, PDF/CSV reports", "Operations & communication"],
];

export default function About() {
  return (
    <div className="space-y-6">
      <PageHeader title="Project information"
        description="CloudGuard — Intelligent Cloud Security & Resource Monitoring System. A Computer Science Engineering project demonstrating cloud computing, virtualisation, containerisation and security monitoring on real infrastructure." />

      <Concept icon={<Cloud className="size-4" />} title="Cloud computing"
        inCloudGuard={<>CloudGuard treats the local host, its VMs and containers as a small private cloud: it measures resource usage continuously,
          keeps history for <Link className="text-accent hover:underline" to="/capacity">capacity planning</Link>, and exposes everything through a
          REST API and a <Link className="text-accent hover:underline" to="/topology">topology map</Link>, as cloud monitoring services do.</>}>
        <p>Cloud computing delivers computing resources — servers, storage, networks, platforms and software — on demand over a network, with
          self-service provisioning, resource pooling, rapid elasticity and measured service (NIST SP 800-145).</p>
        <p><b className="text-ink">Service models:</b> IaaS (virtual machines, networks, storage), PaaS (managed runtimes and databases) and SaaS
          (complete applications). <b className="text-ink">Deployment models:</b> public, private, hybrid and community clouds.</p>
        <p>Because resources are shared and billed by use, providers and customers must <i>observe</i> utilisation, plan capacity and detect
          misuse — the role of monitoring platforms such as AWS CloudWatch, Azure Monitor and Prometheus/Grafana.</p>
      </Concept>

      <Concept icon={<ServerCog className="size-4" />} title="Virtualisation"
        inCloudGuard={<>The <Link className="text-accent hover:underline" to="/vms">Virtual Machines</Link> module discovers VirtualBox VMs, shows their
          configuration and state, starts and shuts them down through a validated command wrapper, and raises an alert if a running VM stops
          without a CloudGuard action.</>}>
        <p>A <b className="text-ink">hypervisor</b> lets several isolated virtual machines share one physical computer. Each VM has virtual CPUs,
          memory, disks and network cards and runs its own operating system.</p>
        <p><b className="text-ink">Type 1</b> (bare-metal) hypervisors such as KVM, ESXi and Hyper-V run directly on hardware and power public clouds;
          <b className="text-ink"> Type 2</b> (hosted) hypervisors such as VirtualBox run on a host OS and are common for labs and development.</p>
        <p>Hardware extensions (Intel VT-x, AMD-V) and techniques such as nested paging make virtualisation efficient; strong isolation is why VMs remain the
          foundation of IaaS.</p>
      </Concept>

      <Concept icon={<Boxes className="size-4" />} title="Containerisation"
        inCloudGuard={<>The <Link className="text-accent hover:underline" to="/containers">Containers</Link> module talks to the Docker Engine API:
          it lists containers, reads cgroup-based CPU/memory/network statistics and logs, performs authorised start/stop/restart, and detects
          crashes, restart loops, failing health checks and resource abuse. Compliance checks are inspired by the CIS Docker Benchmark.</>}>
        <p>Containers package an application with its dependencies and run it as isolated processes on a shared kernel. Linux
          <b className="text-ink"> namespaces</b> isolate what a process can see (PIDs, network, mounts, users) and
          <b className="text-ink"> control groups (cgroups)</b> limit what it can use (CPU, memory, I/O).</p>
        <p>Compared with VMs, containers start in milliseconds and use far less memory, but share the host kernel — so least privilege
          (non-root users, no <code className="font-mono">--privileged</code>), resource limits and image hygiene matter for security.</p>
        <p>Images are built from layered filesystems, distributed through registries and orchestrated at scale by platforms such as Kubernetes.</p>
      </Concept>

      <Concept icon={<ShieldCheck className="size-4" />} title="Security monitoring"
        inCloudGuard={<>CloudGuard combines <Link className="text-accent hover:underline" to="/security">transparent detection rules</Link>,
          <Link className="text-accent hover:underline" to="/integrity"> file integrity monitoring</Link>,
          <Link className="text-accent hover:underline" to="/analytics"> explainable anomaly detection</Link>, a de-duplicating
          <Link className="text-accent hover:underline" to="/alerts"> alert center</Link>, an
          <Link className="text-accent hover:underline" to="/incidents"> incident workflow</Link> and an audit log. It does not claim to detect malware:
          every alert states the exact condition that triggered it.</>}>
        <p>Security monitoring collects events and telemetry, detects suspicious conditions and supports a response. Core ideas:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li><b className="text-ink">Rule-based detection</b> — explicit conditions such as “≥ 5 failed logins in 10 minutes” (brute force).</li>
          <li><b className="text-ink">File integrity monitoring</b> — cryptographic hashes reveal unauthorised changes to important files.</li>
          <li><b className="text-ink">Anomaly detection</b> — unsupervised models (e.g. Isolation Forest) learn normal behaviour and flag outliers.</li>
          <li><b className="text-ink">Alert triage &amp; incident response</b> — preparation, detection &amp; analysis, containment, eradication, recovery and lessons learned (NIST SP 800-61).</li>
          <li><b className="text-ink">Defence in depth</b> — authentication, least privilege, auditing and secure configuration (e.g. CIS Controls).</li>
        </ul>
      </Concept>

      <Card>
        <CardHeader title="How the modules map to the concepts" icon={<Layers className="size-4" />} />
        <Table head={["Module", "What it does", "Concept demonstrated"]}>
          {MODULES.map(([m, d, c]) => (
            <tr key={m}><td className="px-4 py-2.5 text-sm text-ink">{m}</td><td className="px-4 py-2.5 text-xs text-ink-2">{d}</td><td className="px-4 py-2.5 text-xs text-ink-2">{c}</td></tr>
          ))}
        </Table>
      </Card>

      <Card>
        <CardHeader title="Architecture & technology" icon={<GraduationCap className="size-4" />} />
        <div className="grid gap-4 p-5 text-sm text-ink-2 md:grid-cols-3">
          <div><p className="font-semibold text-ink">Frontend</p><p>React, TypeScript, Vite, Tailwind CSS, Recharts — live updates over WebSockets.</p></div>
          <div><p className="font-semibold text-ink">Backend</p><p>Python, FastAPI, SQLAlchemy, Alembic, psutil, Docker SDK, scikit-learn, ReportLab; JWT + Argon2id authentication with role-based access.</p></div>
          <div><p className="font-semibold text-ink">Data & operations</p><p>PostgreSQL (SQLite for quick local runs), Prometheus exporter, Grafana dashboard, Docker Compose deployment.</p></div>
        </div>
        <p className="border-t border-line px-5 py-3 text-xs text-muted">
          Try it safely in <Link className="text-accent hover:underline" to="/demo">Demo &amp; Learning</Link>: a separate, labelled demonstration environment.
        </p>
      </Card>
    </div>
  );
}
