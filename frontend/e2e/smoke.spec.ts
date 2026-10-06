import { test, expect, login, expectRendered } from "./fixtures";

test("sign-in page renders, including on a deep link", async ({ page }) => {
  for (const path of ["/", "/requests/1", "/dashboard"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  }
});

test("every page renders after sign-in", async ({ page }) => {
  await login(page);
  for (const [path, heading] of [
    ["/", /requests/i],
    ["/dashboard", /behind/i],
    ["/imports", /request lists/i],
    ["/inbox", /unmatched/i],
    ["/activity", /audit|activity/i],
  ] as const) {
    await page.goto(path);
    await expectRendered(page);
    await expect(page.getByRole("heading").filter({ hasText: heading }).first()).toBeVisible();
  }
});

test("sidebar navigation keeps the page rendered", async ({ page }) => {
  await login(page);
  for (const name of ["Who's behind", "Request lists", "Unmatched email", "Audit log", "Requests"]) {
    await page.getByRole("link", { name }).click();
    await expectRendered(page);
  }
});

test("unknown URLs and missing records show a message, not a blank page", async ({ page }) => {
  await login(page);
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();

  for (const path of ["/requests/999999", "/requests/abc", "/imports/999999", "/imports/abc"]) {
    await page.goto(path);
    await expectRendered(page);
    await expect(page.getByRole("alert")).toBeVisible();
  }
  await page.goto("/u/not-a-real-token");
  await expect(page.getByRole("heading", { name: "This request is closed" })).toBeVisible();
});

test("rapid navigation and back/forward don't blank the page", async ({ page }) => {
  await login(page);
  const paths = ["/", "/dashboard", "/imports", "/inbox", "/activity"];
  for (let i = 0; i < 25; i++) {
    page.goto(paths[i % paths.length]).catch(() => {});
    await page.waitForTimeout(50);
  }
  await page.waitForLoadState();
  await expectRendered(page);
  for (let i = 0; i < 8; i++) await page.goBack().catch(() => {});
  for (let i = 0; i < 8; i++) await page.goForward().catch(() => {});
  await expectRendered(page);
});
