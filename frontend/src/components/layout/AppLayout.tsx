import clsx from "clsx";
import {
  Activity, BarChart3, Bell, Boxes, BrainCircuit, ChevronDown, FileBarChart, FileLock2, LayoutDashboard, LogOut,
  Menu, Moon, ScrollText, Server, Settings, ShieldAlert, ShieldCheck, Sun, User as UserIcon, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useLiveChannel } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import type { Alert, Page } from "@/lib/types";
import { SeverityBadge, useToast } from "@/components/ui";

const NAV = [
  { section: "Overview", items: [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/monitoring", label: "Infrastructure", icon: Activity },
  ]},
  { section: "Compute", items: [
    { to: "/containers", label: "Containers", icon: Boxes },
    { to: "/vms", label: "Virtual Machines", icon: Server },
  ]},
  { section: "Security", items: [
    { to: "/alerts", label: "Alert Center", icon: ShieldAlert },
    { to: "/security", label: "Detection & Events", icon: ShieldCheck },
    { to: "/integrity", label: "File Integrity", icon: FileLock2, admin: true },
    { to: "/analytics", label: "Analytics & ML", icon: BrainCircuit },
  ]},
  { section: "Operations", items: [
    { to: "/reports", label: "Reports", icon: FileBarChart },
    { to: "/activity", label: "Audit Log", icon: ScrollText, admin: true },
    { to: "/settings", label: "Settings", icon: Settings, admin: true },
  ]},
];

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 px-2">
      <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-[#1c5cab] to-[#0b1730] ring-1 ring-white/10">
        <ShieldCheck className="size-4.5 text-[#9ec5f4]" />
      </span>
      <span>
        <span className="block text-sm font-semibold tracking-tight text-ink">CloudGuard</span>
        <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-muted">Security Monitor</span>
      </span>
    </Link>
  );
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { isAdmin } = useAuth();
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={onClose} />}
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-line bg-surface transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-16 items-center justify-between px-3">
          <Logo />
          <button className="rounded-md p-1 text-muted lg:hidden" onClick={onClose} aria-label="Close menu">
            <X className="size-4" />
          </button>
        </div>
        <nav aria-label="Main navigation" className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
          {NAV.map((group) => {
            const items = group.items.filter((i) => !("admin" in i && i.admin) || isAdmin);
            if (!items.length) return null;
            return (
              <div key={group.section}>
                <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted">{group.section}</p>
                <ul className="space-y-0.5">
                  {items.map(({ to, label, icon: Icon, ...rest }) => (
                    <li key={to}>
                      <NavLink
                        to={to}
                        end={"end" in rest ? rest.end : false}
                        onClick={onClose}
                        className={({ isActive }) =>
                          clsx(
                            "group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                            isActive ? "bg-accent/12 font-medium text-ink ring-1 ring-inset ring-accent/25" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                          )
                        }
                      >
                        {({ isActive }) => (
                          <>
                            <Icon className={clsx("size-4", isActive ? "text-accent" : "text-muted group-hover:text-ink-2")} />
                            {label}
                          </>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>
        <div className="border-t border-line p-3 text-[11px] text-muted">
          <div className="flex items-center gap-2 px-2">
            <BarChart3 className="size-3.5" /> v1.0 · local infrastructure
          </div>
        </div>
      </aside>
    </>
  );
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [total, setTotal] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const navigate = useNavigate();

  const load = () =>
    api<Page<Alert>>("/api/security/alerts", { query: { status: "active", page_size: 6 } })
      .then((p) => {
        setAlerts(p.items);
        setTotal(p.total);
      })
      .catch(() => {});

  useEffect(() => {
    load();
  }, []);

  const connected = useLiveChannel("alerts", (msg) => {
    if (msg.type === "alert.created") {
      const a: Alert = msg.alert;
      toast({
        tone: a.severity === "critical" || a.severity === "high" ? "critical" : "warning",
        title: `New ${a.severity} alert`,
        message: a.title,
      });
      load();
    } else if (msg.type === "alert.updated") {
      load();
    }
  });

  useEffect(() => {
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
        aria-label={`Notifications: ${total} active alerts`}
      >
        <Bell className="size-4.5" />
        {total > 0 && (
          <span className="absolute -top-0.5 -right-0.5 grid min-w-4.5 place-items-center rounded-full bg-critical px-1 text-[10px] font-bold text-white">
            {total > 99 ? "99+" : total}
          </span>
        )}
      </button>
      {open && (
        <div className="animate-fade-up absolute right-0 z-50 mt-2 w-96 overflow-hidden rounded-xl border border-line-strong bg-surface shadow-2xl">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <p className="text-sm font-semibold">Active alerts</p>
            <span className="flex items-center gap-1.5 text-[11px] text-muted">
              <span className={clsx("size-1.5 rounded-full", connected ? "live-dot bg-good" : "bg-muted")} />
              {connected ? "Live" : "Offline"}
            </span>
          </div>
          <ul className="max-h-96 divide-y divide-line overflow-y-auto">
            {alerts.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted">No active alerts. All clear.</li>}
            {alerts.map((a) => (
              <li key={a.id}>
                <button
                  className="w-full px-4 py-3 text-left hover:bg-surface-2"
                  onClick={() => {
                    setOpen(false);
                    navigate(`/alerts?id=${a.id}`);
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <SeverityBadge severity={a.severity} />
                    <span className="text-[11px] text-muted">{timeAgo(a.last_seen_at)}</span>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-sm text-ink">{a.title}</p>
                </button>
              </li>
            ))}
          </ul>
          <Link to="/alerts" onClick={() => setOpen(false)} className="block border-t border-line px-4 py-2.5 text-center text-xs font-medium text-accent hover:bg-surface-2">
            Open Alert Center
          </Link>
        </div>
      )}
    </div>
  );
}

function ProfileMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  if (!user) return null;
  const initials = (user.full_name || user.username).split(/\s+/).map((s) => s[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 rounded-lg py-1 pr-2 pl-1 hover:bg-surface-2" aria-label="Account menu">
        <span className="grid size-7 place-items-center rounded-full bg-accent/20 text-[11px] font-bold text-accent">{initials}</span>
        <span className="hidden text-left sm:block">
          <span className="block text-xs font-medium leading-tight text-ink">{user.full_name || user.username}</span>
          <span className="block text-[10px] uppercase tracking-wide text-muted">{user.role_name}</span>
        </span>
        <ChevronDown className="size-3.5 text-muted" />
      </button>
      {open && (
        <div className="animate-fade-up absolute right-0 z-50 mt-2 w-52 overflow-hidden rounded-xl border border-line-strong bg-surface py-1 shadow-2xl">
          <div className="border-b border-line px-3 py-2">
            <p className="truncate text-xs text-muted">{user.email}</p>
          </div>
          <button className="flex w-full items-center gap-2 px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink" onClick={() => { setOpen(false); navigate("/profile"); }}>
            <UserIcon className="size-4" /> Profile & security
          </button>
          <button
            className="flex w-full items-center gap-2 px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 hover:text-critical"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export default function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const location = useLocation();
  useEffect(() => setMobileOpen(false), [location.pathname]);

  return (
    <div className="min-h-full">
      <Sidebar open={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2">
            <button className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
              <Menu className="size-5" />
            </button>
            <span className="hidden items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-ink-2 sm:flex">
              <span className="live-dot size-1.5 rounded-full bg-good" /> Monitoring local infrastructure
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={toggle} className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
              {theme === "dark" ? <Sun className="size-4.5" /> : <Moon className="size-4.5" />}
            </button>
            <NotificationBell />
            <div className="mx-1 h-6 w-px bg-line" />
            <ProfileMenu />
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
