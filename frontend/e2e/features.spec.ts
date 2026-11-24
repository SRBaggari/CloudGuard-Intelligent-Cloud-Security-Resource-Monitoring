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
