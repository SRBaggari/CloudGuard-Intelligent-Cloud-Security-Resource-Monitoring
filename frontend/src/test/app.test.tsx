import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "@/App";
import { Badge, Meter, Pagination, SeverityBadge, ToastProvider, statusTone } from "@/components/ui";
import { api, ApiError, buildUrl, tokens } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { formatBytes, formatDuration, formatPercent, titleCase } from "@/lib/format";
import { ThemeProvider } from "@/lib/theme";
import { validateRegistration } from "@/pages/Register";

/* ------------------------------------------------------------------ fetch mock */
type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;
let handler: Handler = () => undefined;

function mockFetch() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const r = handler(url, init) ?? { status: 404, body: { detail: "not mocked: " + url } };
    return new Response(r.status === 204 ? null : JSON.stringify(r.body ?? {}), {
      status: r.status ?? 200, headers: { "Content-Type": "application/json" },
    });
  }));
}

class FakeWS {
  readyState = 0;
  onopen?: () => void;
  onmessage?: (e: { data: string }) => void;
  onclose?: () => void;
  constructor() { setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0); }
  send() {}
  close() {}
}

const ADMIN = { id: 1, email: "a@example.com", username: "admin", full_name: "Admin", role_name: "admin", is_active: true, last_login_at: null, created_at: "2026-01-01T00:00:00Z" };
const METRIC = {
  id: 1, timestamp: new Date().toISOString(), cpu_percent: 42.5, memory_percent: 61.2, memory_used: 8e9, memory_total: 16e9,
  disk_percent: 55.5, disk_used: 2e11, disk_total: 5e11, net_bytes_sent: 1, net_bytes_recv: 1, net_send_rate: 2048, net_recv_rate: 4096,
  process_count: 300, connection_count: 80,
};
const SUMMARY = {
  devices: { total: 4, hosts: 1 },
  vms: { available: false, mode: "real", message: "VirtualBox was not found", total: 0, running: 0 },
  containers: { available: true, mode: "real", total: 3, running: 2, unhealthy: 1 },
  metric: METRIC,
  health: { status: "degraded", score: 78, issues: ["Memory high (86%)"] },
  alerts: {
    active: 2, by_severity: { critical: 1, high: 1, medium: 0, low: 0 },
    recent: [{ id: 7, title: "CPU utilisation at 97% on host", description: "", severity: "critical", category: "system", status: "open", resource_type: "host", resource_name: "host", occurrences: 3, last_seen_at: new Date().toISOString(), created_at: new Date().toISOString() }],
  },
  threats: { events_24h: 12, failed_logins_24h: 5, anomalies_24h: 0, alerts_by_category_24h: {}, ml_model_ready: false },
  activity: [],
};

function renderApp(path: string) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <AppRoutes />
          </MemoryRouter>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  mockFetch();
  vi.stubGlobal("WebSocket", FakeWS);
});
afterEach(() => {
  vi.unstubAllGlobals();
  handler = () => undefined;
});

/* ------------------------------------------------------------------ utilities */
describe("format helpers", () => {
  it("formats bytes, percents and durations", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
    expect(formatBytes(null)).toBe("—");
    expect(formatPercent(12.345)).toBe("12.3%");
    expect(formatDuration(90061)).toBe("1d 1h");
    expect(formatDuration(3700)).toBe("1h 1m");
    expect(titleCase("container_unexpected_exit")).toBe("Container Unexpected Exit");
  });
  it("builds query strings and skips empty values", () => {
    expect(buildUrl("/api/x", { a: 1, b: "", c: undefined, d: false })).toBe("/api/x?a=1&d=false");
  });
});

describe("registration validation", () => {
  const ok = { email: "a@b.co", username: "alice", full_name: "", password: "Passw0rd1", confirm: "Passw0rd1" };
  it("accepts a valid form", () => expect(validateRegistration(ok)).toEqual({}));
  it("rejects bad email, username, weak and mismatched passwords", () => {
    const e = validateRegistration({ email: "nope", username: "a!", full_name: "", password: "password", confirm: "x" });
    expect(Object.keys(e).sort()).toEqual(["confirm", "email", "password", "username"]);
  });
});

/* ------------------------------------------------------------------ components */
describe("UI components", () => {
  it("renders severity badges with text labels (not colour alone)", () => {
    render(<><SeverityBadge severity="critical" /><SeverityBadge severity="low" /></>);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
  });
  it("maps statuses to tones", () => {
    expect(statusTone("running")).toBe("good");
    expect(statusTone("exited")).toBe("critical");
    expect(statusTone("acknowledged")).toBe("warning");
    render(<Badge tone="good">Up</Badge>);
    expect(screen.getByText("Up")).toBeInTheDocument();
  });
  it("meter exposes its value accessibly", () => {
    render(<Meter value={73.4} />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "73");
  });
  it("pagination disables buttons at the boundaries", async () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={10} total={25} onPage={onPage} />);
    expect(screen.getByText("1–10 of 25")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
});

/* ------------------------------------------------------------------ API client */
describe("api client", () => {
  it("raises ApiError with server detail and field errors", async () => {
    handler = () => ({ status: 422, body: { detail: "Validation failed", errors: [{ field: "email", message: "bad" }] } });
    await expect(api("/api/x")).rejects.toMatchObject({ status: 422, message: "Validation failed", fieldErrors: [{ field: "email", message: "bad" }] });
  });
  it("refreshes the access token on 401 and retries once", async () => {
    tokens.set("old-access", "refresh-1");
    let calls = 0;
    handler = (url, init) => {
      if (url === "/api/auth/refresh") return { body: { access_token: "new-access", refresh_token: "refresh-2" } };
      calls++;
      const auth = (init?.headers as Record<string, string>)?.Authorization;
      return auth === "Bearer new-access" ? { body: { ok: true } } : { status: 401, body: { detail: "expired" } };
    };
    await expect(api("/api/data")).resolves.toEqual({ ok: true });
    expect(calls).toBe(2);
    expect(tokens.access).toBe("new-access");
  });
  it("reports a friendly message when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = (await api("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/Cannot reach the CloudGuard API/);
  });
});

/* ------------------------------------------------------------------ routing & pages */
describe("routing and pages", () => {
  it("redirects unauthenticated users to the login page", async () => {
    renderApp("/alerts");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("login form validates required fields and shows server errors", async () => {
    handler = (url) => (url === "/api/auth/login" ? { status: 401, body: { detail: "Invalid username or password" } } : undefined);
    renderApp("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter your username or email")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Username or email"), "eve");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpass1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument();
  });

  it("renders the dashboard from API data for an authenticated admin", async () => {
    tokens.set("access", "refresh");
    handler = (url) => {
      if (url === "/api/auth/me") return { body: ADMIN };
      if (url.startsWith("/api/dashboard/summary")) return { body: SUMMARY };
      if (url.startsWith("/api/monitoring/history")) return { body: [METRIC, { ...METRIC, id: 2 }] };
      if (url.startsWith("/api/security/alerts")) return { body: { items: [], total: 0, page: 1, page_size: 6 } };
      return undefined;
    };
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Security Operations Dashboard" }, { timeout: 10000 })).toBeInTheDocument();
    expect(await screen.findByText("42.5%")).toBeInTheDocument(); // CPU from API, not hardcoded
    expect(screen.getByText("VirtualBox not connected")).toBeInTheDocument();
    expect(screen.getByText("1 unhealthy")).toBeInTheDocument();
    expect(screen.getByText("CPU utilisation at 97% on host")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    // admin-only navigation is visible
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("hides admin navigation and blocks admin pages for regular users", async () => {
    tokens.set("access", "refresh");
    handler = (url) => {
      if (url === "/api/auth/me") return { body: { ...ADMIN, role_name: "user", username: "bob" } };
      if (url.startsWith("/api/security/alerts")) return { body: { items: [], total: 0, page: 1, page_size: 6 } };
      return undefined;
    };
    renderApp("/settings");
    expect(await screen.findByText("Administrator access required")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit Log" })).not.toBeInTheDocument();
  });

  it("shows an error state with retry when the API fails", async () => {
    tokens.set("access", "refresh");
    let fail = true;
    handler = (url) => {
      if (url === "/api/auth/me") return { body: ADMIN };
      if (url.startsWith("/api/dashboard/summary")) return fail ? { status: 500, body: { detail: "Internal server error" } } : { body: SUMMARY };
      if (url.startsWith("/api/monitoring/history")) return { body: [] };
      if (url.startsWith("/api/security/alerts")) return { body: { items: [], total: 0, page: 1, page_size: 6 } };
      return undefined;
    };
    renderApp("/");
    expect(await screen.findByText("Internal server error")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Security Operations Dashboard")).toBeInTheDocument());
  });

  it("notification bell shows unread count and marks items read", async () => {
    tokens.set("access", "refresh");
    const read: number[] = [];
    let unread = 2;
    const n = (id: number, is_read: boolean) => ({
      id, category: "alert", severity: "high", title: `Alert ${id}`, message: "", link: "", alert_id: id,
      is_read, read_at: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    });
    handler = (url, init) => {
      if (url === "/api/auth/me") return { body: ADMIN };
      if (url.startsWith("/api/notifications/") && url.endsWith("/read") && init?.method === "POST") {
        read.push(Number(url.split("/")[3]));
        unread = 1;
        return { body: n(1, true) };
      }
      if (url.startsWith("/api/notifications")) return { body: { items: [n(1, unread < 2), n(2, false)], total: 2, page: 1, page_size: 8, unread } };
      if (url.startsWith("/api/dashboard/summary")) return { body: SUMMARY };
      if (url.startsWith("/api/monitoring/history")) return { body: [] };
      return undefined;
    };
    renderApp("/");
    const bell = await screen.findByRole("button", { name: "Notifications: 2 unread" });
    await userEvent.click(bell);
    await userEvent.click(await screen.findByText("Alert 1"));
    await waitFor(() => expect(read).toEqual([1]));
    expect(await screen.findByRole("button", { name: "Notifications: 1 unread" })).toBeInTheDocument();
  });
});
