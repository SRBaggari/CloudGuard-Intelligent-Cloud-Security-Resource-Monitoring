/** E2E coverage for the enhancement modules (incidents, notifications, topology, compliance, capacity, demo). */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const SHOTS = path.resolve(import.meta.dirname, "../../documentation/screenshots");
fs.mkdirSync(SHOTS, { recursive: true });
const ADMIN = { username: process.env.E2E_ADMIN ?? "admin", password: process.env.E2E_PASSWORD ?? "CloudGuard2026!" };
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });

test.describe.configure({ mode: "serial" });

async function login(page: Page) {
  await page.request.post("/api/auth/register", {
    data: { email: `${ADMIN.username}@example.com`, username: ADMIN.username, full_name: "Security Administrator", password: ADMIN.password },
  });
  await page.goto("/login");
  await page.getByLabel("Username or email").fill(ADMIN.username);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Security Operations Dashboard" })).toBeVisible();
}

const authHeaders = async (page: Page) => ({ Authorization: `Bearer ${await page.evaluate(() => sessionStorage.getItem("cg-access"))}` });

test("incident workflow: alert → incident → investigate → respond → resolve", async ({ page }) => {
  await login(page);
  const headers = await authHeaders(page);
  // make sure there is at least one active alert to work with (a real rule evaluation: failed logins)
  const active = await (await page.request.get("/api/security/alerts?status=active", { headers })).json();
  test.skip(active.total === 0, "no active alert available to build an incident from");

  await page.goto("/alerts");
  await page.getByRole("row").nth(1).click();
  await page.getByRole("dialog").getByRole("button", { name: "Create incident" }).click();
  const create = page.getByRole("dialog", { name: "Create incident" });
  await create.getByLabel("Title").fill("E2E incident: investigate host alert");
  await create.getByRole("button", { name: "Create incident" }).click();

  await expect(page).toHaveURL(/\/incidents\/\d+$/);
  await expect(page.getByRole("heading", { name: "E2E incident: investigate host alert" })).toBeVisible();
  await page.getByRole("button", { name: "Mark acknowledged" }).click();
  await expect(page.getByText("Moved to acknowledged")).toBeVisible();
  await page.getByRole("button", { name: "Mark investigating" }).click();
  await page.getByLabel("Investigation note").fill("Reviewed host metrics; load caused by a scheduled backup.");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Reviewed host metrics; load caused by a scheduled backup.")).toBeVisible();
  await page.getByLabel("What was done").fill("Rescheduled the backup job to off-peak hours");
  await page.getByRole("button", { name: "Record action" }).click();
  await expect(page.getByText("Action recorded")).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "16-incident-detail");

  await page.getByRole("button", { name: "Resolve…" }).click();
  await page.getByLabel("Resolution summary (required)").fill("Backup rescheduled; utilisation back to normal.");
  await page.getByRole("button", { name: "Resolve incident" }).click();
  await expect(page.getByRole("button", { name: "Reopen" })).toBeVisible();
  await expect(page.getByText("Backup rescheduled; utilisation back to normal.").first()).toBeVisible();

  await page.goto("/incidents");
  await expect(page.getByRole("heading", { name: "Incident Response" })).toBeVisible();
  await page.getByRole("combobox", { name: "Status" }).selectOption("");
  await expect(page.getByText("E2E incident: investigate host alert").first()).toBeVisible();
  await shot(page, "17-incidents");
});

test("notification center lists notifications and marks them read", async ({ page }) => {
  await login(page);
  await page.goto("/notifications");
  await expect(page.getByRole("heading", { name: "Notification Center" })).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "18-notifications");
  const markAll = page.getByRole("button", { name: "Mark all as read" }).first();
  if (await markAll.isEnabled()) {
    await markAll.click();
    await expect(page.getByRole("button", { name: "Notifications: 0 unread" })).toBeVisible();
  }
});

test("topology map renders real resources and shows node details", async ({ page }) => {
  await login(page);
  await page.goto("/topology");
  await expect(page.getByRole("heading", { name: "Infrastructure Topology" })).toBeVisible();
  const host = page.getByRole("button", { name: /^Host .*:/ }).first();
  await expect(host).toBeVisible();
  await host.click();
  await expect(page.getByText("Connections (")).toBeVisible();
  await expect(page.getByText("Hostname")).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "19-topology");
});

test("compliance: run checklist, assess a manual item, see posture score", async ({ page }) => {
  await login(page);
  await page.goto("/compliance");
  await expect(page.getByRole("heading", { name: "Security Audit & Compliance" })).toBeVisible();
  await expect(page.getByText("CIS-inspired, not a certification")).toBeVisible();
  await page.getByRole("button", { name: "Run checks now" }).click();
  await expect(page.getByText(/Posture score \d/)).toBeVisible();
  const item = page.getByRole("listitem").filter({ hasText: "Incident response contacts documented" });
  await item.getByRole("button", { name: "Assess" }).click();
  await page.getByRole("dialog").getByLabel("Result").selectOption("pass");
  await page.getByLabel("Evidence", { exact: true }).fill("Contact list stored in the project wiki, reviewed by the team lead");
  await page.getByRole("button", { name: "Save assessment" }).click();
  await expect(page.getByText("Assessment recorded")).toBeVisible();
  await expect(item.getByText("Contact list stored in the project wiki")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(5500); // let toasts disappear
  await shot(page, "20-compliance");
});

test("audit log filters and exports CSV", async ({ page }) => {
  await login(page);
  await page.goto("/activity");
  await expect(page.getByRole("heading", { name: "Security Audit Log" })).toBeVisible();
  await page.getByRole("combobox", { name: "Action category" }).selectOption("auth.");
  await expect(page.getByRole("cell", { name: "auth.login" }).first()).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect((await download).suggestedFilename()).toBe("cloudguard-audit-log.csv");
});

test("capacity planning shows estimates or explains missing history", async ({ page }) => {
  await login(page);
  await page.goto("/capacity");
  await expect(page.getByRole("heading", { name: "Capacity Planning" })).toBeVisible();
  await expect(page.getByText("Estimates are not measurements")).toBeVisible();
  const insufficient = page.getByText("Not enough history yet");
  const ready = page.getByText("Estimate (linear trend)").first();
  await expect(insufficient.or(ready)).toBeVisible();
  if (await ready.isVisible()) await expect(page.getByText("Measured (bucket average)").first()).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "21-capacity");
});

test("settings: thresholds, diagnostics and saved theme preference", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Security thresholds" })).toBeVisible();
  const warning = page.getByLabel("High CPU utilisation warning");
  const original = await warning.inputValue();
  await warning.fill(original === "85" ? "84" : "85");
  await page.getByRole("row").filter({ hasText: "High CPU utilisation" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Threshold saved")).toBeVisible();
  // restore the original value so the test leaves configuration unchanged
  await warning.fill(original);
  await page.getByRole("row").filter({ hasText: "High CPU utilisation" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Threshold saved").nth(1)).toBeVisible();
  await expect(page.getByRole("heading", { name: "System health diagnostics" })).toBeVisible();
  await expect(page.getByText("Database connection")).toBeVisible();
  await expect(page.getByText(/Loop: metrics/)).toBeVisible();
  await page.getByRole("heading", { name: "System health diagnostics" }).scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await shot(page, "22-settings-diagnostics");

  // appearance is stored on the profile and survives a fresh session
  await page.goto("/profile");
  await page.getByLabel("Appearance").selectOption("light");
  await expect(page.getByText("Appearance saved")).toBeVisible();
  await page.evaluate(() => localStorage.removeItem("cg-theme"));
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/light/);
  await page.getByLabel("Appearance").selectOption("dark");
  await expect(page.locator("html")).toHaveClass(/dark/);
});
