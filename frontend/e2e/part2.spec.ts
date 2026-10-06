import { test, expect, login, expectRendered, STARTER } from "./fixtures";

test("import a request list, send it, and run the follow-up schedule forward", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);

  await page.goto("/imports");
  await page.locator("input[type=file]").first().setInputFiles(`${STARTER}requests.csv`);
  await page.getByRole("button", { name: "Upload and review" }).click();
  await expect(page).toHaveURL(/\/imports\/\d+$/);
  await expectRendered(page);
  const batch = page.url();

  for (const f of ["Changes", "All"]) {
    await page.getByLabel("Filter rows").getByText(f, { exact: false }).first().click();
    await expectRendered(page);
  }

  await page.getByRole("button", { name: "Apply import" }).click();
  const sendAll = page.getByRole("button", { name: /^Send all \d+ emails$/ });
  await expect(sendAll).toBeVisible();
  await sendAll.click();
  await expect(sendAll).toHaveCount(0);
  await expectRendered(page);

  await page.goto("/");
  await page.getByLabel("Filter requests").getByText("All").click();
  const links = await page.locator("a[href^='/requests/']").evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute("href")!))]);
  expect(links.length).toBeGreaterThanOrEqual(25);

  // reminders, overdue notices and escalations: step the demo clock forward and sweep
  for (const jump of ["+3 days", "+1 week", "+1 week"]) {
    await page.getByRole("button", { name: /demo clock/i }).click();
    await page.getByRole("button", { name: jump }).click();
    await expect(page.getByRole("button", { name: jump })).toHaveCount(0);
    // the popover closes after a jump; "Run sweep now" calls this
    expect((await page.request.post("/api/dev/sweep")).ok()).toBe(true);
    await page.waitForTimeout(2000);
    for (const p of ["/", "/dashboard", "/activity", batch]) {
      await page.goto(p);
      await expectRendered(page);
    }
  }
  for (const href of links) {
    await page.goto(href);
    await expectRendered(page);
  }

  await page.goto("/dashboard");
  await expectRendered(page);
  await page.goto("/");
  await page.getByLabel("Filter requests").getByText("Overdue").click();
  await expect(page.locator("a[href^='/requests/']").first()).toBeVisible();
});
