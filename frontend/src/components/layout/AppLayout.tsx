import clsx from "clsx";
import {
  Activity, BarChart3, Bell, BellRing, ClipboardCheck, Boxes, BrainCircuit, ChevronDown, FileBarChart, FileLock2, Gauge, LayoutDashboard, LogOut,
  Menu, Moon, ScrollText, Server, Settings, ShieldAlert, ShieldCheck, Siren, Sun, Workflow, User as UserIcon, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { NOTIFICATIONS_CHANGED, useLiveChannel } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import type { AppNotification, NotificationPage } from "@/lib/types";
import { useToast } from "@/components/ui";

const NAV = [
  { section: "Overview", items: [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/monitoring", label: "Infrastructure", icon: Activity },
    { to: "/topology", label: "Topology", icon: Workflow },
    { to: "/capacity", label: "Capacity Planning", icon: Gauge },
  ]},
  { section: "Compute", items: [
    { to: "/containers", label: "Containers", icon: Boxes },
    { to: "/vms", label: "Virtual Machines", icon: Server },
  ]},
  { section: "Security", items: [
    { to: "/alerts", label: "Alert Center", icon: ShieldAlert },
    { to: "/incidents", label: "Incidents", icon: Siren },
    { to: "/notifications", label: "Notifications", icon: BellRing },
    { to: "/security", label: "Detection & Events", icon: ShieldCheck },
    { to: "/integrity", label: "File Integrity", icon: FileLock2, admin: true },
    { to: "/analytics", label: "Analytics & ML", icon: BrainCircuit },
  ]},
  { section: "Operations", items: [
    { to: "/reports", label: "Reports", icon: FileBarChart },
    { to: "/compliance", label: "Compliance", icon: ClipboardCheck, admin: true },
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

const SEV_DOT: Record<string, string> = {
  critical: "bg-critical", high: "bg-serious", medium: "bg-warning", low: "bg-low", info: "bg-accent",
};

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const navigate = useNavigate();

  const load = () =>
    api<NotificationPage>("/api/notifications", { query: { page_size: 8 } })
      .then((p) => {
        setItems(p.items);
        setUnread(p.unread);
      })
      .catch(() => {});

  useEffect(() => {
    load();
    window.addEventListener(NOTIFICATIONS_CHANGED, load);
    return () => window.removeEventListener(NOTIFICATIONS_CHANGED, load);
  }, []);

  const connected = useLiveChannel("notifications", (msg) => {
    if (msg.type === "notification.created" || msg.type === "notification.updated") {
      const n: AppNotification = msg.notification;
      toast({
        tone: n.severity === "critical" || n.severity === "high" ? "critical" : n.severity === "medium" ? "warning" : "info",
        title: n.category === "alert" ? `${n.severity[0].toUpperCase()}${n.severity.slice(1)} alert` : n.title,
        message: n.category === "alert" ? n.title : n.message,
      });
      load();
    }
  });

  useEffect(() => {
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function openItem(n: AppNotification) {
    setOpen(false);
    if (!n.is_read) await api(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(() => {});
    load();
    if (n.link) navigate(n.link);
  }

  async function readAll() {
    await api("/api/notifications/read-all", { method: "POST" }).catch(() => {});
    load();
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
        aria-label={`Notifications: ${unread} unread`}
      >
        <Bell className="size-4.5" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 grid min-w-4.5 place-items-center rounded-full bg-critical px-1 text-[10px] font-bold text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="animate-fade-up absolute right-0 z-50 mt-2 w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-line-strong bg-surface shadow-2xl">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div>
              <p className="text-sm font-semibold">Notifications</p>
              <span className="flex items-center gap-1.5 text-[11px] text-muted">
                <span className={clsx("size-1.5 rounded-full", connected ? "live-dot bg-good" : "bg-muted")} />
                {connected ? "Live" : "Offline"} · {unread} unread
              </span>
            </div>
            <button onClick={readAll} disabled={!unread} className="text-xs font-medium text-accent hover:underline disabled:text-muted disabled:no-underline">
              Mark all as read
            </button>
          </div>
          <ul className="max-h-96 divide-y divide-line overflow-y-auto">
            {items.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted">No notifications yet.</li>}
            {items.map((n) => (
              <li key={n.id}>
                <button className={clsx("flex w-full gap-3 px-4 py-3 text-left hover:bg-surface-2", !n.is_read && "bg-accent/5")} onClick={() => openItem(n)}>
                  <span className={clsx("mt-1.5 size-2 shrink-0 rounded-full", n.is_read ? "bg-surface-3" : SEV_DOT[n.severity])} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-muted uppercase">{n.category} · {n.severity}</span>
                      <span className="text-[11px] text-muted">{timeAgo(n.updated_at)}</span>
                    </span>
                    <span className={clsx("mt-0.5 line-clamp-2 block text-sm", n.is_read ? "text-ink-2" : "font-medium text-ink")}>{n.title}</span>
                    {!n.is_read && <span className="sr-only">(unread)</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <Link to="/notifications" onClick={() => setOpen(false)} className="block border-t border-line px-4 py-2.5 text-center text-xs font-medium text-accent hover:bg-surface-2">
            Open Notification Center
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
  const { theme, setPreference } = useTheme();
  const { user } = useAuth();
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setPreference(next);
    if (user) api("/api/auth/me", { method: "PATCH", body: { theme_preference: next } }).catch(() => {}); // persist to profile
  };
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
