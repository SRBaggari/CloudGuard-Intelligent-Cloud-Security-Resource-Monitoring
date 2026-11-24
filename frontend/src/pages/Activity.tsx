import { FileDown, ScrollText, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Card, EmptyState, ErrorState, Input, PageHeader, Pagination, Select, Spinner, Table, useToast } from "@/components/ui";
import { buildUrl, downloadFile } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page, User } from "@/lib/types";

interface Entry {
  id: number; user_id: number | null; username: string | null; action: string; resource_type: string; resource_id: string;
  details: Record<string, unknown>; ip_address: string; created_at: string;
}

const CATEGORIES = [
  ["", "All actions"], ["auth.", "Authentication"], ["admin.", "Administration"], ["user.", "User profile"],
  ["container.", "Containers"], ["vm.", "Virtual machines"], ["alert.", "Alerts"], ["incident.", "Incidents"],
  ["rule.", "Detection rules"], ["settings.", "Settings"], ["integrity.", "File integrity"], ["compliance.", "Compliance"],
  ["report.", "Reports"], ["ml.", "Machine learning"], ["audit.", "Audit"], ["demo.", "Demonstration"],
];

export default function Activity() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const [q, setQ] = useState("");
  const [qd, setQd] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  useEffect(() => { const t = setTimeout(() => setQd(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => setPage(1), [action, userId, qd, start, end]);
  const filters = {
    action, user_id: userId, q: qd,
    start: start ? new Date(start + "T00:00:00").toISOString() : undefined,
    end: end ? new Date(end + "T23:59:59").toISOString() : undefined,
  };
  const { data, error, loading, reload } = useApi<Page<Entry>>("/api/activity", { query: { ...filters, page, page_size: 30 } });
  const users = useApi<Page<User>>("/api/users", { query: { page_size: 200 } });

  async function exportCsv() {
    try {
      await downloadFile(buildUrl("/api/activity/export", filters), "cloudguard-audit-log.csv");
    } catch (e) {
      toast({ tone: "critical", title: "Export failed", message: (e as Error).message });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Security Audit Log"
        description="Tamper-evident trail of authentication, administrative changes and resource actions, with user, source IP and timestamp."
        actions={<Button icon={<FileDown className="size-4" />} onClick={exportCsv}>Export CSV</Button>} />
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Resource or IP…" className="pl-8" aria-label="Search resource or IP" />
          </div>
          <Select value={action} onChange={(e) => setAction(e.target.value)} className="w-44" aria-label="Action category">
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          <Select value={userId} onChange={(e) => setUserId(e.target.value)} className="w-40" aria-label="User">
            <option value="">All users</option>
            {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
          </Select>
          <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="w-38" aria-label="From date" />
          <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="w-38" aria-label="To date" />
        </div>
        {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? (
          <EmptyState icon={<ScrollText className="size-5" />} title="No audit entries match these filters" />
        ) : (
          <>
            <Table head={["Time", "User", "Action", "Resource", "Details", "Source IP"]}>
              {data.items.map((e) => (
                <tr key={e.id} className="hover:bg-surface-2">
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted">{formatDateTime(e.created_at)}</td>
                  <td className="px-4 py-2.5 text-xs text-ink">{e.username ?? (e.user_id ? `#${e.user_id}` : "system")}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-ink">{e.action}</td>
                  <td className="max-w-[200px] truncate px-4 py-2.5 text-xs text-ink-2">{e.resource_type} {e.resource_id}</td>
                  <td className="max-w-sm truncate px-4 py-2.5 font-mono text-[11px] text-muted" title={JSON.stringify(e.details)}>
                    {Object.keys(e.details).length ? JSON.stringify(e.details) : ""}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{e.ip_address}</td>
                </tr>
              ))}
            </Table>
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </div>
  );
}
