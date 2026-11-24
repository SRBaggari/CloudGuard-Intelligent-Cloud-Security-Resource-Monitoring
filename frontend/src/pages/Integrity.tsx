import { FileLock2, FolderPlus, History, ListTree, RefreshCw, ScanSearch, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import {
  Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Pagination, Select, Spinner, Table, Toggle, useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatBytes, formatDateTime, timeAgo } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page } from "@/lib/types";

interface Dir {
  id: number; path: string; recursive: boolean; enabled: boolean; baseline_at: string | null; last_scan_at: string | null;
  files: number; changed: number; status_counts: Record<string, number>;
}
interface Change { id: number; directory_id: number; file_path: string; change_type: "modified" | "new" | "deleted"; old_hash: string | null; new_hash: string | null; detected_at: string }
interface FileRec { id: number; file_path: string; sha256: string; size: number; status: string; modified_at: string | null }

const CHANGE_TONE = { modified: "warning", new: "info", deleted: "critical" } as const;

function FilesModal({ dir, onClose }: { dir: Dir; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const { data, error } = useApi<Page<FileRec>>(`/api/integrity/directories/${dir.id}/files`, { query: { page, page_size: 50 } });
  return (
    <Modal open onClose={onClose} title={`Baseline · ${dir.path}`} wide>
      {error ? <ErrorState message={error.message} /> : !data ? <Spinner /> : (
        <>
          <Table head={["File", "Status", "Size", "SHA-256"]}>
            {data.items.map((f) => (
              <tr key={f.id}>
                <td className="max-w-sm truncate px-4 py-2 font-mono text-xs text-ink" title={f.file_path}>{f.file_path.replace(dir.path, "") || f.file_path}</td>
                <td className="px-4 py-2"><Badge tone={f.status === "baseline" ? "good" : f.status === "deleted" ? "critical" : "warning"}>{f.status}</Badge></td>
                <td className="px-4 py-2 text-xs tabular text-ink-2">{formatBytes(f.size)}</td>
                <td className="px-4 py-2 font-mono text-[11px] text-muted" title={f.sha256}>{f.sha256.slice(0, 16)}…</td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
        </>
      )}
    </Modal>
  );
}

export default function Integrity() {
  const toast = useToast();
  const status = useApi<{ directories: Dir[]; total_changes: number }>("/api/integrity/status");
  const [page, setPage] = useState(1);
  const [type, setType] = useState("");
  const history = useApi<Page<Change>>("/api/integrity/history", { query: { page, page_size: 20, change_type: type } });
  const [path, setPath] = useState("");
  const [recursive, setRecursive] = useState(true);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [viewing, setViewing] = useState<Dir | null>(null);

  const reloadAll = () => { status.reload(); history.reload(); };

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!path.trim()) return setAddError("Enter an absolute directory path");
    setAdding(true); setAddError("");
    try {
      await api("/api/integrity/directories", { method: "POST", body: { path: path.trim(), recursive } });
      toast({ tone: "good", title: "Directory added", message: "Baseline created with SHA-256 hashes." });
      setPath("");
      reloadAll();
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setAdding(false);
    }
  }

  async function run(key: string, fn: () => Promise<unknown>, success: string) {
    setBusy(key);
    try {
      const r: any = await fn();
      const res = r?.results?.[0];
      toast({ tone: "good", title: success, message: res && !res.error ? `${res.modified} modified · ${res.new} new · ${res.deleted} deleted${res.unreadable ? ` · ${res.unreadable} unreadable (locked)` : ""}` : undefined });
      reloadAll();
    } catch (err) {
      toast({ tone: "critical", title: "Operation failed", message: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="File Integrity Monitoring" description="SHA-256 baselines for explicitly configured directories. Changes are detected on scan and every 5 minutes automatically."
        actions={<Button variant="primary" icon={<ScanSearch className="size-4" />} loading={busy === "all"} onClick={() => run("all", () => api("/api/integrity/scan", { method: "POST" }), "Integrity scan complete")}>Scan all now</Button>} />

      <Banner tone="info" title="Only directories you add are monitored" icon={<ShieldCheck className="size-4" />}>
        Sensitive system locations (Windows, Program Files, ProgramData, /etc, /proc, ~/.ssh, AppData and similar) and whole drives are blocked. Up to 20,000 files per directory are hashed.
      </Banner>

      <Card>
        <CardHeader title="Add monitored directory" icon={<FolderPlus className="size-4" />} />
        <form onSubmit={add} className="flex flex-wrap items-end gap-4 p-5">
          <div className="min-w-[320px] flex-1">
            <Field label="Absolute directory path" htmlFor="fim-path" error={addError} hint="Example: C:\inetpub\wwwroot or /srv/app/config">
              <Input id="fim-path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\Projects\my-app\config" />
            </Field>
          </div>
          <label className="mb-6 flex items-center gap-2 text-sm text-ink-2"><Toggle checked={recursive} onChange={setRecursive} label="Recursive" /> Include subdirectories</label>
          <Button type="submit" variant="primary" className="mb-5" loading={adding}>Add & create baseline</Button>
        </form>
      </Card>

      <Card>
        <CardHeader title="Monitored directories" icon={<FileLock2 className="size-4" />} actions={<Button size="sm" variant="ghost" onClick={status.reload} aria-label="Refresh"><RefreshCw className="size-3.5" /></Button>} />
        {status.error ? <ErrorState message={status.error.message} onRetry={status.reload} /> : !status.data ? <Spinner /> : !status.data.directories.length ? (
          <EmptyState icon={<FileLock2 className="size-5" />} title="No directories monitored yet" message="Add a directory above to create its SHA-256 baseline." />
        ) : (
          <Table head={["Directory", "Files", "Changes pending", "Baseline", "Last scan", ""]}>
            {status.data.directories.map((d) => (
              <tr key={d.id} className="hover:bg-surface-2">
                <td className="max-w-md px-4 py-3"><p className="truncate font-mono text-xs text-ink" title={d.path}>{d.path}</p><p className="text-[11px] text-muted">{d.recursive ? "recursive" : "top-level only"}</p></td>
                <td className="px-4 py-3 tabular">{d.files}</td>
                <td className="px-4 py-3">{d.changed ? <Badge tone="warning">{d.changed} changed</Badge> : <Badge tone="good">Clean</Badge>}</td>
                <td className="px-4 py-3 text-xs text-muted">{timeAgo(d.baseline_at)}</td>
                <td className="px-4 py-3 text-xs text-muted">{timeAgo(d.last_scan_at)}</td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" title="View baseline" aria-label="View baseline" onClick={() => setViewing(d)}><ListTree className="size-3.5" /></Button>
                    <Button size="sm" variant="ghost" loading={busy === `s${d.id}`} onClick={() => run(`s${d.id}`, () => api("/api/integrity/scan", { method: "POST", query: { directory_id: d.id } }), "Scan complete")}>Scan</Button>
                    <Button size="sm" variant="ghost" title="Accept current state as the trusted baseline" loading={busy === `b${d.id}`}
                      onClick={() => confirm("Accept all current files as the new trusted baseline?") && run(`b${d.id}`, () => api(`/api/integrity/directories/${d.id}/baseline`, { method: "POST" }), "Baseline updated")}>Accept changes</Button>
                    <Button size="sm" variant="ghost" aria-label="Remove directory" onClick={() => confirm(`Stop monitoring ${d.path}?`) && run(`d${d.id}`, () => api(`/api/integrity/directories/${d.id}`, { method: "DELETE" }), "Directory removed")}><Trash2 className="size-3.5 text-critical" /></Button>
                  </div>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title="Change history" subtitle={`${status.data?.total_changes ?? 0} changes recorded`} icon={<History className="size-4" />}
          actions={<Select value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} className="h-8 w-36 text-xs" aria-label="Change type">
            <option value="">All changes</option><option value="modified">Modified</option><option value="new">New</option><option value="deleted">Deleted</option>
          </Select>} />
        {history.error ? <ErrorState message={history.error.message} /> : !history.data ? <Spinner /> : !history.data.items.length ? (
          <EmptyState title="No changes detected" message="Modified, new and deleted files will be listed here after a scan." />
        ) : (
          <>
            <Table head={["Detected", "Change", "File", "Previous hash", "New hash"]}>
              {history.data.items.map((c) => (
                <tr key={c.id}>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted">{formatDateTime(c.detected_at)}</td>
                  <td className="px-4 py-2.5"><Badge tone={CHANGE_TONE[c.change_type]}>{c.change_type}</Badge></td>
                  <td className="max-w-md truncate px-4 py-2.5 font-mono text-xs text-ink" title={c.file_path}>{c.file_path}</td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-muted" title={c.old_hash ?? ""}>{c.old_hash ? c.old_hash.slice(0, 12) + "…" : "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-muted" title={c.new_hash ?? ""}>{c.new_hash ? c.new_hash.slice(0, 12) + "…" : "—"}</td>
                </tr>
              ))}
            </Table>
            <Pagination page={history.data.page} pageSize={history.data.page_size} total={history.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      {viewing && <FilesModal dir={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
