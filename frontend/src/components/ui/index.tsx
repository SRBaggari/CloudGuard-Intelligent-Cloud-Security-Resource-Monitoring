import clsx from "clsx";
import {
  AlertOctagon, AlertTriangle, CheckCircle2, CircleAlert, Info, Inbox, Loader2, RefreshCw, ShieldAlert, X,
} from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Severity } from "@/lib/types";

/* ------------------------------------------------------------------ Card */
export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.12)]", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, actions, icon }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
      <div className="flex min-w-0 items-center gap-2.5">
        {icon && <span className="text-muted">{icon}</span>}
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-ink">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Button */
type Variant = "primary" | "secondary" | "ghost" | "danger";
export function Button({
  variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-accent text-white hover:brightness-110",
        variant === "secondary" && "border border-line-strong bg-surface-2 text-ink hover:bg-surface-3",
        variant === "ghost" && "text-ink-2 hover:bg-surface-2 hover:text-ink",
        variant === "danger" && "bg-critical text-white hover:brightness-110",
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Inputs */
export function Field({ label, error, hint, children, htmlFor }: { label: string; error?: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-ink-2">{label}</label>
      {children}
      {error ? <p className="text-xs text-critical" role="alert">{error}</p> : hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export const inputClass =
  "h-9 rounded-lg border border-line-strong bg-surface-2 px-3 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";

// Full width unless the caller sets an explicit width utility
const widthOf = (className?: string) => (/(^|\s)w-/.test(className ?? "") ? "" : "w-full");

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={clsx(inputClass, widthOf(props.className), props.className)} />;
}

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={clsx(inputClass, widthOf(className), "pr-8", className)}>
      {children}
    </select>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx("relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50", checked ? "bg-accent" : "bg-surface-3 ring-1 ring-line-strong")}
    >
      <span className={clsx("absolute top-0.5 left-0 size-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-4.5" : "translate-x-0.5")} />
    </button>
  );
}

/* ------------------------------------------------------------------ Badges */
const SEV_STYLE: Record<Severity, { cls: string; icon: typeof AlertOctagon; label: string }> = {
  critical: { cls: "bg-critical/15 text-critical ring-critical/30", icon: AlertOctagon, label: "Critical" },
  high: { cls: "bg-serious/15 text-serious ring-serious/30", icon: ShieldAlert, label: "High" },
  medium: { cls: "bg-warning/15 text-warning ring-warning/30", icon: AlertTriangle, label: "Medium" },
  low: { cls: "bg-low/15 text-low ring-low/30", icon: Info, label: "Low" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEV_STYLE[severity] ?? SEV_STYLE.low;
  const Icon = s.icon;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset", s.cls)}>
      <Icon className="size-3" aria-hidden />
      {s.label}
    </span>
  );
}

export const severityColor: Record<Severity, string> = {
  critical: "var(--critical)", high: "var(--serious)", medium: "var(--warning)", low: "var(--low)",
};

type Tone = "good" | "warning" | "critical" | "neutral" | "info" | "serious";
const TONE: Record<Tone, string> = {
  good: "bg-good/15 text-good ring-good/30",
  warning: "bg-warning/15 text-warning ring-warning/30",
  serious: "bg-serious/15 text-serious ring-serious/30",
  critical: "bg-critical/15 text-critical ring-critical/30",
  info: "bg-accent/15 text-accent ring-accent/30",
  neutral: "bg-surface-3 text-ink-2 ring-line-strong",
};

export function Badge({ tone = "neutral", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset", TONE[tone])}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

export function statusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (["running", "healthy", "online", "up", "resolved", "ready", "trained"].includes(s)) return "good";
  if (["exited", "dead", "aborted", "unhealthy", "critical", "open"].includes(s)) return "critical";
  if (["paused", "restarting", "degraded", "acknowledged", "saved", "starting"].includes(s)) return "warning";
  return "neutral";
}

/* ------------------------------------------------------------------ States */
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted" role="status">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-surface-3", className)} />;
}

export function EmptyState({ title, message, icon, action }: { title: string; message?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-surface-2 p-3 text-muted ring-1 ring-line">{icon ?? <Inbox className="size-5" />}</div>
      <p className="text-sm font-semibold text-ink">{title}</p>
      {message && <div className="mt-1 max-w-md text-xs leading-relaxed text-muted">{message}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center" role="alert">
      <CircleAlert className="size-6 text-critical" />
      <p className="text-sm text-ink-2">{message}</p>
      {onRetry && (
        <Button size="sm" icon={<RefreshCw className="size-3.5" />} onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Banner({ tone = "info", title, children, icon }: { tone?: "info" | "warning" | "critical" | "good"; title: string; children?: ReactNode; icon?: ReactNode }) {
  const cls = {
    info: "border-accent/30 bg-accent/8",
    warning: "border-warning/30 bg-warning/8",
    critical: "border-critical/30 bg-critical/8",
    good: "border-good/30 bg-good/8",
  }[tone];
  const color = { info: "text-accent", warning: "text-warning", critical: "text-critical", good: "text-good" }[tone];
  return (
    <div className={clsx("flex gap-3 rounded-xl border px-4 py-3", cls)}>
      <span className={clsx("mt-0.5", color)}>{icon ?? <Info className="size-4" />}</span>
      <div className="text-sm">
        <p className="font-semibold text-ink">{title}</p>
        {children && <div className="mt-0.5 text-xs leading-relaxed text-ink-2">{children}</div>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Table */
export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-wide text-muted">
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-2.5 font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-xs text-muted">
      <span className="tabular">
        {total === 0 ? "0 results" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}
      </span>
      <div className="flex gap-1.5">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Modal */
export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh] backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx("animate-fade-up w-full rounded-xl border border-line-strong bg-surface shadow-2xl", wide ? "max-w-4xl" : "max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Toasts */
type Toast = { id: number; tone: "good" | "critical" | "info" | "warning"; title: string; message?: string };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((ts) => [...ts.slice(-3), { ...t, id }]);
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 5000);
  }, []);
  const icon = { good: CheckCircle2, critical: AlertOctagon, info: Info, warning: AlertTriangle };
  const color = { good: "text-good", critical: "text-critical", info: "text-accent", warning: "text-warning" };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => {
          const Icon = icon[t.tone];
          return (
            <div key={t.id} className="animate-fade-up pointer-events-auto flex gap-3 rounded-xl border border-line-strong bg-surface-2 p-3 shadow-xl">
              <Icon className={clsx("mt-0.5 size-4 shrink-0", color[t.tone])} />
              <div className="min-w-0 text-sm">
                <p className="font-semibold text-ink">{t.title}</p>
                {t.message && <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{t.message}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

/* ------------------------------------------------------------------ Page header */
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Stat tile */
export function StatTile({
  label, value, sub, icon, tone, children,
}: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; tone?: "accent" | "good" | "warning" | "critical"; children?: ReactNode }) {
  const toneCls = { accent: "text-accent bg-accent/12", good: "text-good bg-good/12", warning: "text-warning bg-warning/12", critical: "text-critical bg-critical/12" }[tone ?? "accent"];
  return (
    <Card className="animate-fade-up p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-muted">{label}</p>
        {icon && <span className={clsx("rounded-lg p-1.5", toneCls)}>{icon}</span>}
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
      {children}
    </Card>
  );
}

/** Thin utilisation meter with threshold colouring (status colours + numeric label). */
export function Meter({ value, warn = 80, crit = 92 }: { value: number; warn?: number; crit?: number }) {
  const color = value >= crit ? "var(--critical)" : value >= warn ? "var(--warning)" : "var(--accent)";
  return (
    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-3" role="meter" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.min(100, value)}%`, background: color }} />
    </div>
  );
}
