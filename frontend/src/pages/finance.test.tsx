import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, Route, RouterProvider, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth";
import i18n from "@/i18n";
import { jsonResponse, renderWithProviders } from "@/test/utils";
import type { DatasetRowsEvidence, Role } from "@/lib/types";
import { DatasetRowsTable } from "@/components/evidence";
import { OutcomeBadge } from "@/components/common";
import { anyEvidenceLocation } from "@/lib/evidence";
import { MembersCard } from "@/components/members-card";
import { RulePackVersionPage } from "./RulePacksPage";
import { ReviewsPage } from "./ReviewsPage";
import { AcceptInvitePage, ResetPasswordPage } from "./PublicAuthPages";

const org = { id: "o1", name: "Alpha Synthetic Audit Team", slug: "alpha-synthetic", is_demo: true };
function me(role: Role) {
  return {
    user: { id: "u1", email: "admin@alpha.example", full_name: "Demo Admin", preferred_locale: "en", is_demo: true },
    org,
    role,
    memberships: [{ org, role }],
    csrf_token: "csrf",
    demo_mode: true,
    ai_enabled: false,
  };
}

type Handler = (url: string, init?: RequestInit) => Response | undefined;
function mockFetch(handler: Handler) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    return Promise.resolve(handler(url, init) ?? jsonResponse(404, { detail: "Not found." }));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(async () => {
  vi.unstubAllGlobals();
  window.location.hash = "";
  await act(() => i18n.changeLanguage("en"));
});

const rowsEvidence: DatasetRowsEvidence = {
  type: "dataset_rows",
  dataset_version_id: "dv1",
  dataset_kind: "general_ledger",
  version_number: 2,
  label: "Unbalanced journals",
  row_ids: [3, 4, 9, 10, 11, 12],
  row_count: 8,
  columns: ["row_id", "journal_id", "debit"],
  rows: [
    ["3", "JE-1", "100.0000"],
    ["4", "JE-1", null],
  ],
  detail: { difference: "100.0000" },
};

describe("dataset evidence", () => {
  it("shows exact values, the shown/total count and a readable location", () => {
    render(<DatasetRowsTable evidence={rowsEvidence} />);
    expect(screen.getByText("General ledger v2")).toBeInTheDocument();
    expect(screen.getByText("First 2 of 8 rows")).toBeInTheDocument();
    expect(screen.getAllByText("100.0000")).toHaveLength(2); // the row value and the detail
    expect(screen.getByRole("columnheader", { name: "Row" })).toBeInTheDocument();
    const t = i18n.t.bind(i18n) as (k: string, o?: Record<string, unknown>) => string;
    expect(anyEvidenceLocation(rowsEvidence, t)).toBe("General ledger v2, rows 3, 4, 9, 10, 11 …");
  });

  it("labels data-check outcomes in both languages", async () => {
    render(<OutcomeBadge outcome="exceptions_found" />);
    expect(screen.getByText("Exceptions found")).toBeInTheDocument();
    await act(() => i18n.changeLanguage("ar"));
    expect(await screen.findByText("توجد استثناءات")).toBeInTheDocument();
  });
});

const ruleVersion = {
  id: "rv1",
  rule_pack_id: "rp1",
  version_number: 1,
  state: "published",
  published_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  rule_count: 2,
  unverified_count: 1,
  pack_name: "VAT thresholds",
  jurisdiction: "AE",
  is_synthetic: false,
  rules: [
    {
      id: "r1",
      rule_key: "vat.standard_rate",
      title: "Standard rate",
      value_type: "decimal",
      value: "0.05",
      unit: "ratio",
      effective_from: "2018-01-01",
      effective_to: null,
      source_url: "https://example.org/source",
      source_note: "",
      todo: "",
      verification_status: "draft",
      verified_by_name: null,
      verified_at: null,
    },
    {
      id: "r2",
      rule_key: "vat.registration_threshold",
      title: "Registration threshold",
      value_type: "decimal",
      value: "375000",
      unit: "AED",
      effective_from: "2018-01-01",
      effective_to: null,
      source_url: "https://example.org/source",
      source_note: "",
      todo: "",
      verification_status: "verified",
      verified_by_name: "Demo Admin",
      verified_at: "2026-01-02T00:00:00Z",
    },
  ],
};

describe("rule pack version", () => {
  function renderVersion(role: Role) {
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me(role));
      if (url.endsWith("/rule-pack-versions/rv1")) return jsonResponse(200, ruleVersion);
      if (url.endsWith("/rules/r1/verify")) return jsonResponse(200, { ...ruleVersion.rules[0], verification_status: "verified" });
    });
    // The rules editor warns about unsaved changes with useBlocker, which needs a data router.
    const router = createMemoryRouter(
      [{ path: "/rule-packs/versions/:versionId", element: <AuthProvider><RulePackVersionPage /></AuthProvider> }],
      { initialEntries: ["/rule-packs/versions/rv1"] },
    );
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    return fetchMock;
  }

  it("flags unverified rules and lets an admin verify one", async () => {
    const user = userEvent.setup();
    const fetchMock = renderVersion("org_admin");
    expect(await screen.findByText("This version contains unverified rules. Checks that use them say so in the review and the report.")).toBeInTheDocument();
    const row = screen.getByText("vat.standard_rate").closest("tr")!;
    expect(within(row).getByText("Unverified")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Verify" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, init]) => String(u).endsWith("/rules/r1/verify") && (init as RequestInit)?.method === "POST")).toBe(true),
    );
    // Published versions are read-only; a new draft is the way to change them.
    expect(screen.queryByRole("button", { name: "Add rule" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New draft" })).toBeInTheDocument();
  });

  it("hides verification from reviewers", async () => {
    renderVersion("reviewer");
    expect(await screen.findByText("vat.standard_rate")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Return to draft" })).not.toBeInTheDocument();
  });
});

describe("members", () => {
  const members = [
    { user_id: "u1", full_name: "Demo Admin", email: "admin@alpha.example", role: "org_admin", membership_id: "m1", joined_at: null },
    { user_id: "u2", full_name: "Demo Viewer", email: "viewer@alpha.example", role: "viewer", membership_id: "m2", joined_at: null },
  ];

  it("lets an admin invite by email and change a role", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("org_admin"));
      if (url.endsWith("/members")) return jsonResponse(200, members);
      if (url.endsWith("/invitations") && init?.method === "POST")
        return jsonResponse(201, {
          id: "i1",
          email: "new@example.com",
          role: "analyst",
          invited_by_name: "Demo Admin",
          created_at: "",
          expires_at: "2026-02-01T00:00:00Z",
          is_expired: false,
          last_sent_at: null,
          last_delivery: "sent",
        });
      if (url.endsWith("/invitations")) return jsonResponse(200, []);
      if (url.endsWith("/members/m2")) return jsonResponse(200, { ...members[1], role: "reviewer" });
    });
    renderWithProviders(<MembersCard />);
    await user.selectOptions(await screen.findByLabelText("Role for Demo Viewer"), "reviewer");
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/members/m2"));
      expect(call && JSON.parse(String((call[1] as RequestInit).body))).toEqual({ role: "reviewer" });
    });
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.click(screen.getByRole("button", { name: "Send invite" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, init]) => String(u).endsWith("/invitations") && (init as RequestInit)?.method === "POST");
      expect(call && JSON.parse(String((call[1] as RequestInit).body))).toEqual({ email: "new@example.com", role: "analyst" });
    });
  });

  it("shows a read-only list to non-admins", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/members")) return jsonResponse(200, members);
    });
    renderWithProviders(<MembersCard />);
    expect(await screen.findByText("Demo Viewer")).toBeInTheDocument();
    expect(screen.queryByLabelText("Role for Demo Viewer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send invite" })).not.toBeInTheDocument();
  });
});

describe("password reset", () => {
  it("sends the token from the link fragment and removes it from the address bar", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/reset-password#token=tok-1234567890abcdefghij");
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(401, { detail: "Not signed in." });
      if (url.endsWith("/auth/password-reset/confirm")) return new Response(null, { status: 204 });
    });
    renderWithProviders(<ResetPasswordPage />, { route: "/reset-password" });
    expect(window.location.hash).toBe("");
    await user.type(await screen.findByLabelText("New password"), "a-long-new-password");
    await user.type(screen.getByLabelText("Confirm new password"), "a-long-new-password");
    await user.click(screen.getByRole("button", { name: "Set password" }));
    expect(await screen.findByText("Password updated")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/auth/password-reset/confirm"))!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({ token: "tok-1234567890abcdefghij", new_password: "a-long-new-password" });
  });

  it("explains a missing token", async () => {
    window.history.replaceState(null, "", "/reset-password");
    mockFetch((url) => (url.endsWith("/auth/me") ? jsonResponse(401, {}) : undefined));
    renderWithProviders(<ResetPasswordPage />, { route: "/reset-password" });
    expect(await screen.findByRole("alert")).toHaveTextContent("This link is invalid or has expired.");
  });
});

describe("accept invitation", () => {
  it("creates an account and signs in", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/accept-invite#token=inv-1234567890abcdefghij");
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(401, { detail: "Not signed in." });
      if (url.endsWith("/invitations/lookup"))
        return jsonResponse(200, { organization_name: "Org a", email: "new@example.com", role: "analyst", has_account: false, expires_at: "2026-02-01T00:00:00Z" });
      if (url.endsWith("/invitations/accept")) return jsonResponse(200, me("analyst"));
    });
    renderWithProviders(
      <Routes>
        <Route path="/accept-invite" element={<AcceptInvitePage />} />
        <Route path="/" element={<p>workspace home</p>} />
      </Routes>,
      { route: "/accept-invite" },
    );
    expect(await screen.findByText("Join Org a")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Name"), "New Person");
    await user.type(screen.getByLabelText("New password"), "a-long-new-password");
    await user.type(screen.getByLabelText("Confirm new password"), "a-long-new-password");
    await user.click(screen.getByRole("button", { name: "Create account and join" }));
    expect(await screen.findByText("workspace home")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/invitations/accept"))!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      token: "inv-1234567890abcdefghij",
      password: "a-long-new-password",
      full_name: "New Person",
    });
  });

  it("shows a clear message for an unusable invitation", async () => {
    window.history.replaceState(null, "", "/accept-invite#token=inv-1234567890abcdefghij");
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(401, {});
      if (url.endsWith("/invitations/lookup")) return jsonResponse(404, { detail: "Not found." });
    });
    renderWithProviders(<AcceptInvitePage />, { route: "/accept-invite" });
    expect(await screen.findByRole("alert")).toHaveTextContent("This invitation is invalid, has expired or was already used.");
  });
});

describe("new review with datasets", () => {
  it("creates a dataset-only review with a rule pack and as-of date", async () => {
    const user = userEvent.setup();
    const ready = (id: string, kind: string, name: string) => ({
      id,
      entity_id: "e1",
      entity_name: "Synthetic Trading LLC",
      kind,
      name,
      period_start: null,
      period_end: null,
      is_demo: true,
      created_at: "",
      latest_version: { id: `${id}-v1`, version_number: 1, status: "ready" },
    });
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.includes("/documents?")) return jsonResponse(200, { items: [], total: 0, page: 1, page_size: 100 });
      if (url.endsWith("/checklists"))
        return jsonResponse(200, [
          { id: "c1", name: "Ledger checks", description: "", kind: "synthetic_demo", created_at: "", versions: [{ id: "cv1", version_number: 1, state: "published" }] },
        ]);
      if (url.endsWith("/datasets")) return jsonResponse(200, [ready("d1", "general_ledger", "GL FY25"), ready("d2", "general_ledger", "GL FY24"), ready("d3", "trial_balance", "TB FY25")]);
      if (url.endsWith("/rule-packs"))
        return jsonResponse(200, [
          { id: "rp1", name: "Synthetic thresholds", jurisdiction: "SYNTHETIC", description: "", is_synthetic: true, created_at: "", versions: [{ id: "rpv1", version_number: 1, state: "published", unverified_count: 2 }] },
        ]);
      if (url.endsWith("/reviews") && init?.method === "POST") return jsonResponse(201, { id: "r1" });
      if (url.includes("/reviews?")) return jsonResponse(200, { items: [], total: 0, page: 1, page_size: 20 });
    });
    renderWithProviders(
      <Routes>
        <Route path="/reviews" element={<ReviewsPage />} />
        <Route path="/reviews/:id" element={<p>review page</p>} />
      </Routes>,
      { route: "/reviews?new" },
    );
    await user.type(await screen.findByLabelText("Review title"), "Ledger review");
    await user.click(screen.getByRole("button", { name: "Create and run checks" }));
    expect(await screen.findByText("Choose a document, a dataset, or both.")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /GL FY25/ }));
    // One dataset per type: the other ledger is disabled, the trial balance is not.
    expect(screen.getByRole("checkbox", { name: /GL FY24/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /TB FY25/ })).toBeEnabled();
    await user.selectOptions(screen.getByLabelText("Rule pack"), "rpv1");
    expect(screen.getByText("This rule pack has unverified rules. Results that use them are flagged as unverified.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("As-of date"), "2025-12-31");
    await user.click(screen.getByRole("button", { name: "Create and run checks" }));
    expect(await screen.findByText("review page")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/reviews") && (i as RequestInit)?.method === "POST")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      title: "Ledger review",
      checklist_version_id: "cv1",
      document_version_id: null,
      dataset_version_ids: ["d1-v1"],
      rule_pack_version_id: "rpv1",
      as_of_date: "2025-12-31",
    });
  });
});
