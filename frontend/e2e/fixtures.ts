import { test as base, expect, type Page } from "@playwright/test";

export const STARTER = new URL("../../data/starter/", import.meta.url).pathname;

type Guard = {
  /** uncaught page errors and real 5xx responses seen during the test */
  errors: string[];
  /** set when a test stubs failures on purpose */
  allowServerErrors: boolean;
  allowPageErrors: boolean;
};

/** Watch a page for crashes; accept the app's confirm() prompts. */
export function guardPage(page: Page, g: Guard) {
  page.on("dialog", (d) => void d.accept().catch(() => {}));
  page.on("pageerror", (e) => {
    if (!g.allowPageErrors) g.errors.push(`pageerror: ${e.message}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 500 && !g.allowServerErrors) g.errors.push(`${r.status()} ${r.request().method()} ${r.url()}`);
  });
}

export const test = base.extend<{ guard: Guard }>({
  guard: [
    async ({ page }, use) => {
      const g: Guard = { errors: [], allowServerErrors: false, allowPageErrors: false };
      guardPage(page, g);
      await use(g);
      expect(g.errors, "page errors / server errors during the test").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };

export async function login(page: Page, email = "sam@example.com", password = "requester") {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/** The page shows real content: not blank, not the crash screen. */
export async function expectRendered(page: Page) {
  const root = page.locator("#root");
  await expect(root).not.toBeEmpty();
  await expect.poll(async () => (await root.innerText()).trim().length, { message: "page is blank" }).toBeGreaterThan(0);
  await expect(page.getByText("Something went wrong")).toHaveCount(0);
}

/** Create a request from the chat box and take it through confirm → send. Returns its upload link. */
export async function createAndSendRequest(page: Page, ask: string) {
  await page.goto("/");
  await page.locator("#new-request").fill(ask);
  await page.locator("#new-request").press("ControlOrMeta+Enter");
  await expect(page).toHaveURL(/\/requests\/\d+$/);
  await page.getByRole("button", { name: "Confirm checklist" }).click();
  await page.getByRole("button", { name: "Approve and send" }).click();
  await expect(page.getByText("Awaiting provider")).toBeVisible();
  const text = await page.locator("text=/\\/u\\/[A-Za-z0-9_-]+/").first().innerText();
  return { url: page.url(), hubPath: text.match(/\/u\/[A-Za-z0-9_-]+/)![0] };
}
