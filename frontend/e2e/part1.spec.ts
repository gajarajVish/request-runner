import { test, expect, login, expectRendered, createAndSendRequest, guardPage, STARTER } from "./fixtures";

const MSA = `${STARTER}part1/A_msa-and-insurance/acme-msa-2025_signed.pdf`;
const COI = `${STARTER}part1/A_msa-and-insurance/acme-logistics-llc_certificate-of-insurance_2026-2027.pdf`;
const REPLY = `${STARTER}part1/A_msa-and-insurance/reply-1_certificate-and-msa-question.eml`;

test("request → confirm → send → provider uploads → requester sees it", async ({ page, browser, guard }) => {
  await login(page);
  const { url, hubPath } = await createAndSendRequest(page, "Get the signed 2025 MSA and the certificate of insurance from Jordan Lee (jordan@acme.example) by Dec 17");

  // the provider opens their link on a phone, without an account
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const hub = await phone.newPage();
  guardPage(hub, guard);
  await hub.goto(hubPath);
  await expect(hub.getByText(/Hi Jordan/)).toBeVisible();

  await hub.locator("input[type=file]").first().setInputFiles([MSA, COI]);
  const removes = hub.getByRole("button", { name: /^Remove / });
  await expect(removes).toHaveCount(2);
  await removes.first().click();
  await expect(removes).toHaveCount(1);
  await hub.reload();
  await expectRendered(hub);
  await expect(removes).toHaveCount(1);

  await hub.getByRole("button", { name: "I've sent everything I have" }).click();
  await expect(hub.getByRole("heading", { name: "Thanks, you're all done" })).toBeVisible();
  await phone.close();

  await page.goto(url);
  await expectRendered(page);
  await expect(page.getByText("acme-logistics-llc_certificate-of-insurance_2026-2027.pdf").first()).toBeVisible();
});

test("request menu dialogs open and close cleanly", async ({ page }) => {
  await login(page);
  await createAndSendRequest(page, "Get the September bank statement from Mei Wong (mei@example.com) by Dec 20");
  const more = page.getByRole("button", { name: "More actions" });
  for (const item of ["Re-check what was received", "Email history", "Audit log", "Accept as is", "Change due date", "Cancel request"]) {
    await more.click();
    await page.getByRole("menuitem", { name: new RegExp(item) }).click();
    await expectRendered(page);
    await page.keyboard.press("Escape");
    const back = page.getByRole("button", { name: /^(Keep request|Back)$/ });
    if (await back.count()) await back.first().click();
    await expectRendered(page);
  }
  await page.getByPlaceholder(/Ask about this request/).fill("What's still missing?");
  await page.getByPlaceholder(/Ask about this request/).press("ControlOrMeta+Enter");
  await expectRendered(page);
});

test("an inbound email injected from the inbox reaches the request", async ({ page }) => {
  await login(page);
  const { url } = await createAndSendRequest(page, "Get the signed MSA from Pat Kim (pat@vendor.example) by Dec 30");
  await page.goto("/inbox");
  await page.getByRole("button", { name: /inject a raw/i }).click();
  await page.locator("input[type=file]").first().setInputFiles(REPLY);
  await page.getByRole("button", { name: /^Inject/ }).click();
  await expectRendered(page);
  await page.goto(url);
  await expectRendered(page);
});
