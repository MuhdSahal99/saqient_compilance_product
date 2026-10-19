import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "Demo-Password-2026!";
const SAMPLE = fileURLToPath(new URL("../../samples/synthetic-vendor-policy.txt", import.meta.url));

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

async function openFinding(page: Page, title: string) {
  await page.getByRole("list", { name: "Findings" }).getByRole("button", { name: new RegExp(title) }).click();
  await expect(page.getByRole("heading", { name: title, level: 2 }).or(page.getByText(title).nth(1))).toBeVisible();
}

test("analyst uploads and runs a review; reviewer decides, assigns, signs off and exports", async ({ page }, testInfo) => {
  // Synthetic content only. A unique line avoids the duplicate-upload check across runs.
  const unique = `Run reference ${Date.now()}.`;
  const file = testInfo.outputPath("synthetic-vendor-policy-e2e.txt");
  writeFileSync(file, `${readFileSync(SAMPLE, "utf8")}\n${unique}\n`);
  const docTitle = `E2E synthetic vendor policy ${Date.now()}`;
  const reviewTitle = `E2E review ${Date.now()}`;

  // 1. Analyst signs in and uploads.
  await login(page, "analyst@alpha.example");
  await page.getByRole("navigation").getByRole("link", { name: "Documents", exact: true }).click();
  await page.getByRole("button", { name: "Upload document" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("File").setInputFiles(file);
  await dialog.getByLabel("Title").fill(docTitle);
  await dialog.getByLabel("Document type").selectOption("policy");
  await dialog.getByRole("button", { name: "Upload" }).click();

  // 2. Wait for background extraction (Celery worker) to finish.
  await expect(page.getByRole("heading", { name: docTitle })).toBeVisible();
  await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Our systems are 100% secure")).toBeVisible();
  await expect(page.getByText(/not scanned for malware/)).toBeVisible();

  // 3. Choose the checklist and run deterministic checks.
  await page.getByRole("link", { name: "Start review" }).click();
  const review = page.getByRole("dialog");
  await review.getByLabel("Review title").fill(reviewTitle);
  await expect(review.getByLabel("Checklist version")).toContainText("Synthetic");
  await review.getByRole("button", { name: "Create and run checks" }).click();
  await expect(page.getByRole("heading", { name: reviewTitle })).toBeVisible();
  const findings = page.getByRole("list", { name: "Findings" });
  await expect(findings).toBeVisible({ timeout: 60_000 });
  await expect(findings.getByRole("button")).toHaveCount(3);

  // Analysts cannot record reviewer decisions.
  await findings.getByRole("button", { name: /No absolute assurance language/ }).click();
  await expect(page.locator("mark.evidence").first()).toContainText("100% secure");
  await expect(page.getByRole("button", { name: "Confirm" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sign off review" })).toHaveCount(0);
  const reviewUrl = page.url().split("?")[0]!;
  await logout(page);

  // 4. Reviewer inspects evidence and decides each finding.
  await login(page, "reviewer@alpha.example");
  await page.goto(reviewUrl);
  await expect(page.getByRole("heading", { name: reviewTitle })).toBeVisible();

  await openFinding(page, "No absolute assurance language");
  await expect(page.locator("mark.evidence").first()).toContainText("100% secure");
  await expect(page.getByText("(not a reviewer decision)")).toBeVisible();
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(findings.getByRole("button", { name: /No absolute assurance language/ })).toContainText("Confirmed");

  // 5. Assign remediation.
  await page.getByLabel("Owner").selectOption({ label: "Demo Analyst (Alpha)" });
  await page.getByLabel("Due date").fill("2030-01-31");
  await page.getByRole("button", { name: "Save assignment" }).click();
  await expect(findings.getByRole("button", { name: /No absolute assurance language/ })).toContainText("Remediation in progress");

  // Dismissal needs a rationale.
  await openFinding(page, "Periodic access review is required");
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByText("Give a rationale of at least 5 characters.")).toBeVisible();
  await page.getByLabel(/Rationale/).fill("Access reviews are covered by a separate synthetic standard.");
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(findings.getByRole("button", { name: /Periodic access review is required/ })).toContainText("Dismissed");

  await openFinding(page, "Management approval is evidenced");
  await page.getByLabel(/Rationale/).fill("Approval record is held outside this synthetic document.");
  await page.getByRole("button", { name: "Accept risk" }).click();
  await expect(findings.getByRole("button", { name: /Management approval is evidenced/ })).toContainText("Accepted risk");

  // 6. Reviewer sign-off.
  await expect(page.getByText("Every finding has a reviewer decision.")).toBeVisible();
  await page.getByRole("button", { name: "Sign off review" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sign off review" }).click();
  await expect(page.getByText(/Signed off by Demo Reviewer/).first()).toBeVisible();
  await expect(page.getByText("Report version 1")).toBeVisible();

  // Decisions are locked after sign-off.
  await page.getByRole("tab", { name: "Findings" }).click();
  await openFinding(page, "Periodic access review is required");
  await expect(page.getByText(/The review is signed off/)).toBeVisible();

  // 7. Export the report in each format.
  await page.getByRole("tab", { name: "Reports" }).click();
  const html = page.getByRole("link", { name: "HTML" });
  const csv = page.getByRole("link", { name: "CSV" });
  const pdf = page.getByRole("link", { name: "PDF" });
  const htmlRes = await page.request.get((await html.getAttribute("href"))!);
  expect(htmlRes.status()).toBe(200);
  const body = await htmlRes.text();
  expect(body).toContain(reviewTitle);
  expect(body).toContain("No absolute assurance language");
  expect(body).toContain("not legal guidance");
  const csvRes = await page.request.get((await csv.getAttribute("href"))!);
  expect(csvRes.status()).toBe(200);
  expect(await csvRes.text()).toContain("Periodic access review is required");
  const pdfRes = await page.request.get((await pdf.getAttribute("href"))!);
  expect(pdfRes.status()).toBe(200);
  expect((await pdfRes.body()).subarray(0, 4).toString()).toBe("%PDF");

  const [download] = await Promise.all([page.waitForEvent("download"), csv.click()]);
  expect(download.suggestedFilename()).toMatch(/\.csv$/);
});

test("Arabic switches the interface to right-to-left", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");
  await page.getByLabel("البريد الإلكتروني").fill("reviewer@alpha.example");
  await page.getByLabel("كلمة المرور", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "تسجيل الدخول" }).click();
  await expect(page.getByRole("heading", { name: "نظرة عامة" })).toBeVisible();
  await expect(page.getByText("نسبة بنود قائمة التحقق التي تمت مراجعتها.").first()).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
});

test("signed-out users are sent to the login page", async ({ page }) => {
  await page.goto("/reviews");
  await expect(page).toHaveURL(/\/login/);
});

test("seeded ledger review shows dataset exceptions and the unverified rule", async ({ page }) => {
  await login(page, "reviewer@alpha.example");
  await page.getByRole("navigation").getByRole("link", { name: "Datasets", exact: true }).click();
  await page.getByRole("link", { name: "December 2025 ledger (synthetic)" }).click();
  await expect(page.getByText("Ready to use as review input.")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Imported rows/ })).toContainText("13");

  await page.getByRole("navigation").getByRole("link", { name: "Reviews", exact: true }).click();
  await page.getByRole("link", { name: "December ledger checks (synthetic demo)" }).click();
  await expect(page.getByText(/Unverified rule: demo\.large_entry/)).toBeVisible();
  await openFinding(page, "Data exceptions found: Weekend postings are explained");
  await expect(page.getByText("Exceptions found").first()).toBeVisible();
  // Evidence is the flagged ledger rows, by row id, with stored values.
  const evidence = page.getByRole("figure").filter({ hasText: "General ledger v1" });
  await expect(evidence.getByRole("cell", { name: "2025-12-06" }).first()).toBeVisible();

  await page.getByRole("navigation").getByRole("link", { name: "Rule packs", exact: true }).click();
  await expect(page.getByText("1 unverified").first()).toBeVisible();
});

test("seeded e-invoices, e-invoice review and tax calendar", async ({ page }) => {
  await login(page, "reviewer@alpha.example");
  await page.getByRole("navigation").getByRole("link", { name: "E-invoices", exact: true }).click();
  await expect(page.getByText(/Nothing on this page is sent to any e-invoicing platform/)).toBeVisible();
  await expect(page.getByText("March 2026 e-invoices (synthetic)").first()).toBeVisible();

  await page.getByRole("navigation").getByRole("link", { name: "Reviews", exact: true }).click();
  await page.getByRole("link", { name: "E-invoice validation and readiness (synthetic demo)" }).click();
  await expect(page.getByText(/Unverified rule/).first()).toBeVisible();
  await page.getByRole("list", { name: "Findings" }).getByRole("button", { name: /Mandatory|mandatory|Issue date/ }).first().click();
  await expect(page.getByText("/inv:Invoice/cbc:IssueDate").first()).toBeVisible();

  await page.getByRole("navigation").getByRole("link", { name: "Tax calendar", exact: true }).click();
  await expect(page.getByText("VAT return (synthetic)").first()).toBeVisible();
  await expect(page.getByText("Unverified").first()).toBeVisible();
});
