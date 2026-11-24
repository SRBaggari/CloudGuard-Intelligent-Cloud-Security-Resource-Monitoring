import { Activity, Boxes, BrainCircuit, FileLock2, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

const FEATURES = [
  { icon: Activity, title: "Real-time infrastructure telemetry", text: "CPU, memory, disk and network from the host via psutil." },
  { icon: Boxes, title: "Containers & virtual machines", text: "Docker Engine and VirtualBox discovery, health and control." },
  { icon: ShieldCheck, title: "Transparent detection rules", text: "Brute-force, abnormal usage, crashes and integrity changes." },
  { icon: BrainCircuit, title: "Anomaly detection", text: "Isolation Forest models trained on your own baseline." },
  { icon: FileLock2, title: "File integrity monitoring", text: "SHA-256 baselines for the directories you choose." },
];

export default function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-full lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-line bg-[radial-gradient(1200px_600px_at_-10%_-10%,#1c5cab55,transparent),linear-gradient(160deg,#0b1730,#070d1a)] p-12 text-[#e6edf7] lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 opacity-[0.07] [background-image:linear-gradient(#fff_1px,transparent_1px),linear-gradient(90deg,#fff_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="relative flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-[#1c5cab]/40 ring-1 ring-white/15">
            <ShieldCheck className="size-5 text-[#9ec5f4]" />
          </span>
          <div>
            <p className="text-lg font-semibold tracking-tight">CloudGuard</p>
            <p className="text-[11px] uppercase tracking-[0.16em] text-[#9fb0cc]">Intelligent Cloud Security</p>
          </div>
        </div>
        <div className="relative max-w-lg">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight">
            One console for your cloud infrastructure, workloads and threats.
          </h2>
          <ul className="mt-8 space-y-4">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-white/5 ring-1 ring-white/10">
                  <Icon className="size-4 text-[#86b6ef]" />
                </span>
                <span>
                  <span className="block text-sm font-medium">{title}</span>
                  <span className="block text-xs text-[#9fb0cc]">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-[#7d8aa3]">Monitoring is restricted to your own local environment and explicitly authorised systems.</p>
      </section>
      <section className="flex items-center justify-center p-6 sm:p-12">
        <div className="animate-fade-up w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <ShieldCheck className="size-6 text-accent" />
            <span className="text-lg font-semibold">CloudGuard</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-sm text-muted">{subtitle}</p>
          <div className="mt-8">{children}</div>
        </div>
      </section>
    </div>
  );
}
