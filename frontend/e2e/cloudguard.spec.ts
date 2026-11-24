import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SHOTS = path.resolve(import.meta.dirname, "../../documentation/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

const ADMIN = { username: process.env.E2E_ADMIN ?? "admin", password: process.env.E2E_PASSWORD ?? "CloudGuard2026!" };
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });

async function ensureAdmin(page: Page) {
  // registering is idempotent for the test: 409 means the account already exists
  await page.request.post("/api/auth/register", {
    data: { email: `${ADMIN.username}@example.com`, username: ADMIN.username, full_name: "Security Administrator", password: ADMIN.password },
  });
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(ADMIN.username);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Security Operations Dashboard" })).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("unauthenticated users are redirected to login", async ({ page }) => {
  await page.goto("/alerts");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.waitForTimeout(700); // entrance animation
  await shot(page, "01-login");
});

test("login form validates input and rejects bad credentials", async ({ page }) => {
  await ensureAdmin(page);
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter your username or email")).toBeVisible();
  await page.getByLabel("Username or email").fill("nobody-e2e");
  await page.getByLabel("Password").fill("wrong-password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid username or password")).toBeVisible();
});

test("registration form validates", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill("not-an-email");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Enter a valid email address")).toBeVisible();
  await expect(page.getByText("Passwords do not match").or(page.getByText("At least 8 characters"))).toBeVisible();
  await shot(page, "02-register");
});

test("dashboard renders live infrastructure data", async ({ page }) => {
  await ensureAdmin(page);
  await login(page);
  await expect(page.getByText("CPU utilisation")).toBeVisible();
  await expect(page.getByText("Live stream connected")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Infrastructure health")).toBeVisible();
  await page.waitForTimeout(4000); // let a few live samples arrive
  await shot(page, "03-dashboard");
  await page.screenshot({ path: path.join(SHOTS, "03-dashboard-full.png"), fullPage: true });
});

test("navigation across all modules", async ({ page }) => {
  await login(page);
  const pages: [string, string, string][] = [
    ["Infrastructure", "Infrastructure Monitoring", "04-monitoring"],
    ["Containers", "Docker Containers", "05-containers"],
    ["Virtual Machines", "Virtual Machines", "06-vms"],
    ["Alert Center", "Alert Center", "07-alerts"],
    ["Detection & Events", "Detection & Events", "08-detection-rules"],
    ["File Integrity", "File Integrity Monitoring", "09-integrity-empty"],
    ["Analytics & ML", "Analytics & Machine Learning", "10-analytics"],
    ["Reports", "Reports", "12-reports"],
    ["Audit Log", "Audit Log", "13-audit-log"],
    ["Settings", "Settings", "14-settings"],
  ];
  for (const [link, heading, file] of pages) {
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: link }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await page.waitForTimeout(1200);
    await shot(page, file);
    if (file === "10-analytics") {
      await page.getByRole("button", { name: "Anomaly detection" }).click();
      await page.waitForTimeout(800);
      await shot(page, "11-anomaly-detection");
    }
  }
});

test("optional integrations show setup guidance instead of fake data", async ({ page }) => {
  await login(page);
  const status = await (await page.request.get("/api/settings/integrations", {
    headers: { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem("cg-access"))}` },
  })).json();
  await page.goto("/vms");
  if (!status.virtualbox.available) await expect(page.getByText("VirtualBox is not connected")).toBeVisible();
  await page.goto("/containers");
  if (!status.docker.available) await expect(page.getByText("Docker Engine is not connected")).toBeVisible();
});

test("file integrity monitoring detects real file changes end-to-end", async ({ page }) => {
  const dir = path.resolve(import.meta.dirname, "../test-results/fim-demo-site");
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(path.join(dir, "config"), { recursive: true });
  fs.writeFileSync(path.join(dir, "index.html"), "<h1>Welcome</h1>");
  fs.writeFileSync(path.join(dir, "config", "app.ini"), "debug=false");
  fs.writeFileSync(path.join(dir, "robots.txt"), "User-agent: *");

  await login(page);
  // remove a leftover registration from an interrupted run
  const headers = { Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem("cg-access"))}` };
  const st = await (await page.request.get("/api/integrity/status", { headers })).json();
  for (const d of st.directories.filter((x: { path: string }) => x.path.includes("fim-demo-site")))
    await page.request.delete(`/api/integrity/directories/${d.id}`, { headers });
  await page.goto("/integrity");
  await page.getByLabel("Absolute directory path").fill(dir);
  await page.getByRole("button", { name: "Add & create baseline" }).click();
  const row = page.getByRole("row").filter({ hasText: "fim-demo-site" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Clean")).toBeVisible();

  // tamper with the monitored files on disk
  fs.writeFileSync(path.join(dir, "config", "app.ini"), "debug=true");
  fs.writeFileSync(path.join(dir, "unexpected-admin.html"), "<form>login</form>");
  fs.rmSync(path.join(dir, "robots.txt"));
  await row.getByRole("button", { name: "Scan", exact: true }).click();
  await expect(page.getByText("1 modified · 1 new · 1 deleted")).toBeVisible();
  await expect(page.getByRole("cell", { name: /unexpected-admin\.html/ })).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "09-integrity");

  // the detection engine raised an alert, visible in the Alert Center
  await page.goto("/alerts?q=fim-demo-site");
  await page.getByLabel("Search alerts").fill("fim-demo-site");
  await expect(page.getByRole("cell", { name: /3 file change\(s\)/ }).first()).toBeVisible();
  await page.getByRole("cell", { name: /3 file change\(s\)/ }).first().click();
  await expect(page.getByText("Recommended response")).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "07b-alert-detail");
  const ack = page.getByRole("dialog").getByRole("button", { name: "Acknowledge", exact: true });
  if (await ack.isVisible()) {
    await ack.click();
    await expect(page.getByText("Alert acknowledged")).toBeVisible();
  }
  await page.getByRole("dialog").getByPlaceholder(/Optional note/).fill("Test change, verified as authorised");
  await page.getByRole("dialog").getByRole("button", { name: "Resolve", exact: true }).click();
  await expect(page.getByText("Alert resolved")).toBeVisible();

  // clean up: stop monitoring the temp directory
  page.on("dialog", (d) => d.accept());
  await page.goto("/integrity");
  await page.getByRole("row").filter({ hasText: "fim-demo-site" }).getByRole("button", { name: "Remove directory" }).click();
  await expect(page.getByRole("row").filter({ hasText: "fim-demo-site" })).toHaveCount(0);
});

test("report generation produces a downloadable PDF", async ({ page }) => {
  await login(page);
  await page.goto("/reports");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Generate & download" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.pdf$/);
  await expect(page.getByText("Report generated")).toBeVisible();
});

test("theme toggle switches to light mode", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: /Switch to light theme/ }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await page.waitForTimeout(2500);
  await shot(page, "15-dashboard-light");
  await page.getByRole("button", { name: /Switch to dark theme/ }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("logout returns to login", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
});
