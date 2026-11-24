import clsx from "clsx";
import { BellRing, CheckCheck, ExternalLink, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Pagination, Select, SeverityBadge, Spinner, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, timeAgo, titleCase } from "@/lib/format";
import { useApi, useLiveChannel } from "@/lib/hooks";
import type { AppNotification, NotificationPage, Severity } from "@/lib/types";

export default function Notifications() {
  const toast = useToast();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  useEffect(() => setPage(1), [unreadOnly, severity, category]);
  const { data, error, loading, reload } = useApi<NotificationPage>("/api/notifications", {
    query: { page, page_size: 20, unread_only: unreadOnly || undefined, severity, category },
  });
  const prefs = useApi<{ min_severity: Severity }>("/api/notifications/preferences");
  useLiveChannel("notifications", () => reload());

  async function markRead(n: AppNotification) {
    await api(`/api/notifications/${n.id}/read`, { method: "POST" });
    reload();
  }

  async function readAll() {
    const r = await api<{ detail: string }>("/api/notifications/read-all", { method: "POST" });
    toast({ tone: "good", title: r.detail });
    reload();
  }

  async function setMin(v: string) {
    await api("/api/notifications/preferences", { method: "PUT", body: { min_severity: v } });
    toast({ tone: "good", title: "Preference saved", message: `You will be notified for ${v} severity and above.` });
    prefs.reload();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notification Center"
        description="Your real-time in-app notifications. Each alert notifies you once; repeated detections update the alert instead of creating duplicates."
        actions={<Button icon={<CheckCheck className="size-4" />} onClick={readAll} disabled={!data?.unread}>Mark all as read</Button>}
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
            <div className="flex rounded-lg border border-line-strong p-0.5" role="group" aria-label="Read state">
              {[{ v: false, l: "All" }, { v: true, l: `Unread${data ? ` (${data.unread})` : ""}` }].map((o) => (
                <button key={String(o.v)} onClick={() => setUnreadOnly(o.v)}
                  className={clsx("rounded-md px-3 py-1 text-xs font-medium", unreadOnly === o.v ? "bg-accent text-white" : "text-ink-2 hover:text-ink")}>
                  {o.l}
                </button>
              ))}
            </div>
            <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-40" aria-label="Severity">
              <option value="">All severities</option>
              {["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
            <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-40" aria-label="Category">
              <option value="">All categories</option>
              {["alert", "incident", "system"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
          </div>
          {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? (
            <EmptyState icon={<BellRing className="size-5" />} title={unreadOnly ? "You're all caught up" : "No notifications"}
              message="Notifications appear here when alerts are raised or incidents change." />
          ) : (
            <>
              <ul className="divide-y divide-line">
                {data.items.map((n) => (
                  <li key={n.id} className={clsx("flex flex-wrap items-start gap-3 px-5 py-4", !n.is_read && "bg-accent/5")}>
                    {n.severity === "info" ? <Badge tone="info">Info</Badge> : <SeverityBadge severity={n.severity} />}
                    <div className="min-w-[220px] flex-1">
                      <p className={clsx("text-sm", n.is_read ? "text-ink-2" : "font-medium text-ink")}>
                        {n.title} {!n.is_read && <Badge tone="info">New</Badge>}
                      </p>
                      {n.message && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{n.message}</p>}
                      <p className="mt-1 text-[11px] text-muted" title={formatDateTime(n.updated_at)}>
                        {titleCase(n.category)} · {timeAgo(n.updated_at)}{n.read_at ? ` · read ${timeAgo(n.read_at)}` : ""}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      {n.link && (
                        <Button size="sm" variant="ghost" icon={<ExternalLink className="size-3.5" />}
                          onClick={async () => { if (!n.is_read) await markRead(n); navigate(n.link); }}>Open</Button>
                      )}
                      {!n.is_read && <Button size="sm" variant="ghost" onClick={() => markRead(n)}>Mark read</Button>}
                    </div>
                  </li>
                ))}
              </ul>
              <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
            </>
          )}
        </Card>

        <Card className="h-fit">
          <CardHeader title="Preferences" icon={<SlidersHorizontal className="size-4" />} />
          <div className="space-y-3 p-5">
            <label htmlFor="min-sev" className="block text-xs font-medium text-ink-2">Notify me about alerts of at least</label>
            {!prefs.data ? <Spinner /> : (
              <Select id="min-sev" value={prefs.data.min_severity} onChange={(e) => setMin(e.target.value)}>
                {["low", "medium", "high", "critical"].map((s) => <option key={s} value={s}>{titleCase(s)} severity</option>)}
              </Select>
            )}
            <p className="text-xs leading-relaxed text-muted">
              Applies to new alerts. The Alert Center always shows every alert regardless of this setting.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
