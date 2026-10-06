// What people see when the server is briefly unreachable (a deploy or restart of the single
// machine): never a blank page or the sign-in form, and the page comes back on its own.
import type { Page, Route } from "@playwright/test";
import { test, expect, login, expectRendered, createAndSendRequest, guardPage } from "./fixtures";

const isApi = (u: URL) => u.pathname.startsWith("/api/") && !/^\/api\/(events|client-error)/.test(u.pathname);

const OUTAGES: Record<string, (r: Route) => Promise<void>> = {
  "502 from the proxy": (r) => r.fulfill({ status: 502, contentType: "text/html", body: "<html>502 Bad Gateway</html>" }),
  "connection refused": (r) => r.abort("connectionrefused"),
  "429 rate limit": (r) => r.fulfill({ status: 429, contentType: "application/json", body: '{"detail":"too many requests"}' }),
};

async function outage(page: Page, handler: (r: Route) => Promise<void>, during: () => Promise<void>) {
  await page.route(isApi, handler);
  try {
    await during();
  } finally {
    await page.unroute(isApi);
  }
}

for (const [name, handler] of Object.entries(OUTAGES)) {
  test(`app: ${name} shows a reconnecting message, then recovers on its own`, async ({ page, guard }) => {
    guard.allowServerErrors = true;
    await login(page);
    for (const path of ["/", "/dashboard"]) {
      await outage(page, handler, async () => {
        await page.goto(path);
        await expect(page.getByText("Loading…")).toBeVisible();
        await expect(page.getByRole("heading", { name: "Can't reach the server" })).toBeVisible({ timeout: 15_000 });
        await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toHaveCount(0);
      });
      // server is back: no reload needed
      await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 15_000 });
      await expectRendered(page);
    }
  });
}

test("app: a failure while already on a page keeps the page up", async ({ page, guard }) => {
  guard.allowServerErrors = true;
  await login(page);
  await page.goto("/");
  await expectRendered(page);
  await outage(page, OUTAGES["502 from the proxy"], async () => {
    await page.getByRole("link", { name: "Who's behind" }).click();
    await page.waitForTimeout(4000);
    await expectRendered(page);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  });
  await page.getByRole("link", { name: "Requests" }).click();
  await expectRendered(page);
});

test("app: a slow server shows Loading…, not a blank page", async ({ page }) => {
  await login(page);
  await page.route(isApi, async (r) => {
    await new Promise((z) => setTimeout(z, 3000));
    await r.continue().catch(() => {});
  });
  await page.goto("/dashboard");
  await expect(page.getByText("Loading…")).toBeVisible();
  await page.unroute(isApi);
  await expectRendered(page);
});

test("app: a crash in one page keeps the sidebar, and navigating away recovers", async ({ page, guard }) => {
  guard.allowPageErrors = true;
  await login(page);
  // a malformed response makes the dashboard throw while rendering
  await page.route((u) => u.pathname === "/api/dashboard", (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.getByRole("link", { name: "Who's behind" }).click();
  await expect(page.getByText("Something went wrong")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.getByRole("link", { name: "Request lists" }).click();
  await expectRendered(page);
});

for (const [name, handler] of Object.entries(OUTAGES)) {
  test(`provider page: ${name} never says the request is closed`, async ({ page, browser, guard }) => {
    await login(page);
    const { hubPath } = await createAndSendRequest(page, `Get the W-9 from Ana Diaz (ana.${name.replace(/\W/g, "")}@example.com) by Dec 22`);
    guard.allowServerErrors = true;

    const ctx = await browser.newContext();
    const hub = await ctx.newPage();
    guardPage(hub, guard);

    // cold load during an outage
    await outage(hub, handler, async () => {
      await hub.goto(hubPath);
      await expect(hub.getByRole("heading", { name: "We couldn't load this page" })).toBeVisible({ timeout: 15_000 });
      await expect(hub.getByText("This request is closed")).toHaveCount(0);
    });
    await expect(hub.getByText(/Hi Ana/)).toBeVisible({ timeout: 15_000 });

    // an upload starts polling every 3s; polls that fail keep what's already shown
    await hub.locator("input[type=file]").first().setInputFiles({ name: "w9.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF\n") });
    await expect(hub.getByRole("button", { name: /^Remove / })).toHaveCount(1);
    await outage(hub, handler, async () => {
      await hub.waitForTimeout(7000);
      await expect(hub.getByText("This request is closed")).toHaveCount(0);
      await expect(hub.getByText(/Hi Ana/)).toBeVisible();
    });
    await ctx.close();
  });
}
