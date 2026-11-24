import { Download, FileBarChart, FileSpreadsheet, FileText, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import {
  Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, Pagination, Select, Spinner, Table, useToast,
} from "@/components/ui";
import { api, ApiError, downloadFile } from "@/lib/api";
import { formatBytes, formatDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page, Report } from "@/lib/types";

const SECTIONS = [
  { id: "health", label: "Infrastructure health" }, { id: "resources", label: "Resource utilisation" },
  { id: "incidents", label: "Security incident summary" }, { id: "containers", label: "Container activity" },
  { id: "vms", label: "Virtual machine status" }, { id: "anomalies", label: "Anomaly detection results" },
  { id: "alerts", label: "Alert history" },
];

const isoDate = (d: Date) => d.toISOString().slice(0, 10);

export default function Reports() {
  const toast = useToast();
  const today = new Date();
  const [title, setTitle] = useState("CloudGuard Security Report");
  const [format, setFormat] = useState<"pdf" | "csv">("pdf");
  const [start, setStart] = useState(isoDate(new Date(today.getTime() - 7 * 86400000)));
  const [end, setEnd] = useState(isoDate(today));
  const [sections, setSections] = useState<string[]>(SECTIONS.map((s) => s.id));
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [page, setPage] = useState(1);
  const list = useApi<Page<Report>>("/api/reports", { query: { page, page_size: 10 } });

  async function generate(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!sections.length) return setError("Select at least one section");
    if (end < start) return setError("End date must be on or after the start date");
    setGenerating(true);
    try {
      const r = await api<Report>("/api/reports/generate", {
        method: "POST",
        body: { title: title.trim() || "CloudGuard Security Report", format, sections,
          start_date: new Date(start + "T00:00:00").toISOString(), end_date: new Date(end + "T23:59:59").toISOString() },
      });
      toast({ tone: "good", title: "Report generated", message: r.file_name });
      list.reload();
      downloadFile(`/api/reports/${r.id}/download`, r.file_name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Reports" description="Generate PDF or CSV reports for any date range from collected monitoring and security data." />
      <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
        <Card>
          <CardHeader title="Generate report" icon={<FileBarChart className="size-4" />} />
          <form onSubmit={generate} className="space-y-4 p-5">
            <Field label="Title" htmlFor="r-title"><Input id="r-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="From" htmlFor="r-start"><Input id="r-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
              <Field label="To" htmlFor="r-end"><Input id="r-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
            </div>
            <Field label="Format" htmlFor="r-format">
              <Select id="r-format" value={format} onChange={(e) => setFormat(e.target.value as "pdf" | "csv")}>
                <option value="pdf">PDF — formatted with summary charts</option>
                <option value="csv">CSV — raw tables for spreadsheets</option>
              </Select>
            </Field>
            <fieldset>
              <legend className="mb-2 text-xs font-medium text-ink-2">Sections</legend>
              <div className="space-y-1.5">
                {SECTIONS.map((s) => (
                  <label key={s.id} className="flex items-center gap-2 text-sm text-ink-2">
                    <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={sections.includes(s.id)}
                      onChange={(e) => setSections((cur) => (e.target.checked ? [...cur, s.id] : cur.filter((x) => x !== s.id)))} />
                    {s.label}
                  </label>
                ))}
              </div>
            </fieldset>
            {error && <p className="text-sm text-critical" role="alert">{error}</p>}
            <Button type="submit" variant="primary" className="w-full" loading={generating} icon={<FileBarChart className="size-4" />}>Generate & download</Button>
          </form>
        </Card>
        <Card>
          <CardHeader title="Generated reports" icon={<FileText className="size-4" />} />
          {list.error ? <ErrorState message={list.error.message} onRetry={list.reload} /> : !list.data ? <Spinner /> : !list.data.items.length ? (
            <EmptyState icon={<FileBarChart className="size-5" />} title="No reports yet" message="Generated reports are stored and can be downloaded again later." />
          ) : (
            <>
              <Table head={["Report", "Period", "Summary", "Size", ""]}>
                {list.data.items.map((r) => (
                  <tr key={r.id} className="hover:bg-surface-2">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {r.format === "pdf" ? <FileText className="size-4 text-critical" /> : <FileSpreadsheet className="size-4 text-good" />}
                        <div><p className="text-ink">{r.title}</p><p className="text-[11px] text-muted">{formatDateTime(r.created_at)}</p></div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-ink-2">{new Date(r.start_date).toLocaleDateString()} – {new Date(r.end_date).toLocaleDateString()}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        <Badge tone={r.summary.health === "healthy" ? "good" : r.summary.health === "critical" ? "critical" : "warning"}>{titleCase(String(r.summary.health))}</Badge>
                        <Badge>{String(r.summary.alerts)} alerts</Badge>
                        <Badge>{String(r.summary.samples)} samples</Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs tabular text-muted">{formatBytes(r.file_size)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" icon={<Download className="size-3.5" />} onClick={() => downloadFile(`/api/reports/${r.id}/download`, r.file_name)}>{r.format.toUpperCase()}</Button>
                        <Button size="sm" variant="ghost" aria-label="Delete report" onClick={async () => { if (confirm("Delete this report?")) { await api(`/api/reports/${r.id}`, { method: "DELETE" }); list.reload(); } }}>
                          <Trash2 className="size-3.5 text-critical" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </Table>
              <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPage={setPage} />
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
