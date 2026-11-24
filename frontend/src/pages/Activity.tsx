import { ScrollText, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Card, EmptyState, ErrorState, Input, PageHeader, Pagination, Spinner, Table } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page } from "@/lib/types";

interface Entry { id: number; user_id: number | null; action: string; resource_type: string; resource_id: string; details: Record<string, unknown>; ip_address: string; created_at: string }

export default function Activity() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => { const t = setTimeout(() => { setDebounced(action); setPage(1); }, 300); return () => clearTimeout(t); }, [action]);
  const { data, error, loading, reload } = useApi<Page<Entry>>("/api/activity", { query: { page, page_size: 30, action: debounced } });
  return (
    <div className="space-y-6">
      <PageHeader title="Audit Log" description="Every authentication, configuration change and resource action is recorded with user, IP and timestamp." />
      <Card>
        <div className="border-b border-line p-3">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted" />
            <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="Filter by action prefix, e.g. container." className="pl-8" aria-label="Filter actions" />
          </div>
        </div>
        {error ? <ErrorState message={error.message} onRetry={reload} /> : loading && !data ? <Spinner /> : !data?.items.length ? (
          <EmptyState icon={<ScrollText className="size-5" />} title="No audit entries" />
        ) : (
          <>
            <Table head={["Time", "Action", "User", "Resource", "Details", "IP"]}>
              {data.items.map((e) => (
                <tr key={e.id}>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted">{formatDateTime(e.created_at)}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-ink">{e.action}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-2">{e.user_id ? `#${e.user_id}` : "system"}</td>
                  <td className="max-w-[200px] truncate px-4 py-2.5 text-xs text-ink-2">{e.resource_type} {e.resource_id}</td>
                  <td className="max-w-sm truncate px-4 py-2.5 font-mono text-[11px] text-muted">{Object.keys(e.details).length ? JSON.stringify(e.details) : ""}</td>
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
