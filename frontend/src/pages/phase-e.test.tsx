import type { ReactNode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import i18n from "@/i18n";
import { AuthProvider } from "@/lib/auth";
import { jsonResponse } from "@/test/utils";
import type { Role } from "@/lib/types";
import type { BankRec, BankRecListItem, Connector, ConnectorStatusInfo, ControlProcess, Deficiency } from "@/lib/assurance";
import { ReconciliationsPage } from "./ReconciliationsPage";
import { BankRecDetailPage } from "./ReconciliationDetailPages";
import { ControlsPage } from "./ControlsPage";
import { ProcessDetailPage } from "./ControlDetailPages";
import { ConnectorsPage } from "./ConnectorsPage";

const org = { id: "o1", name: "Alpha Synthetic Audit Team", slug: "alpha-synthetic", is_demo: true };
function me(role: Role) {
  return {
    user: { id: "u1", email: "user@alpha.example", full_name: "Demo User", preferred_locale: "en", is_demo: true },
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

function renderRoutes(routes: { path: string; element: ReactNode }[], route: string) {
  const router = createMemoryRouter(
    routes.map((r) => ({ path: r.path, element: <AuthProvider>{r.element}</AuthProvider> })),
    { initialEntries: [route] },
  );
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function bodyOf(fetchMock: ReturnType<typeof mockFetch>, path: string, method = "POST") {
  const call = fetchMock.mock.calls.find(([u, i]) => String(u).split("?")[0]!.endsWith(path) && (i as RequestInit)?.method === method);
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await act(() => i18n.changeLanguage("en"));
});

const signOff = { status: "draft" as const, version: 0, prepared_by_name: null, prepared_at: null, signed_off_by_name: null, signed_off_at: null, reopen_reason: "" };

const bankListItem: BankRecListItem = {
  id: "br1",
  entity_id: "ent1",
  entity_name: "Synthetic Trading LLC",
  name: "Operating account October",
  account_label: "Synthetic operating account",
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  currency: "AED",
  status: "draft",
  version: 0,
  is_demo: true,
  created_at: "2026-10-15T08:00:00Z",
};

const bankRec: BankRec = {
  ...bankListItem,
  statement_version_id: "sv1",
  ledger_version_id: "lv1",
  gl_accounts: ["1010"],
  rule_pack_version_id: "rp1",
  rules_prefix: "syn.bank",
  bank_closing_balance: null,
  book_opening_balance: "0.0000",
  matcher_version: "recon-1",
  matched_at: "2026-10-15T08:00:00Z",
  warnings: [],
  parameters: {},
  sign_off: signOff,
  summary: {
    bank_closing_balance: "1500.0000",
    bank_closing_source: "statement",
    book_opening_balance: "0.0000",
    book_movement: "1450.0000",
    book_closing_balance: "1450.0000",
    unmatched_bank_total: "50.0000",
    unmatched_book_total: "0.0000",
    adjusted_bank: "1500.0000",
    adjusted_book: "1500.0000",
    difference: "0.0000",
    bank_items: 3,
    book_items: 2,
    matched_bank_items: 1,
    matched_book_items: 1,
    ageing: [{ side: "bank", bucket: "0-30", count: 2, total: "50.0000" }],
    steps: [{ label: "Difference", expression: "adjusted bank − adjusted book", value: "0.0000" }],
  },
  items: [
    { side: "bank", row_id: 7, date: "2026-10-20", amount: "20.0000", reference: "SYN-7", description: "Synthetic fee", match_id: null, method: null, age_days: 11, bucket: "0-30" },
    { side: "bank", row_id: 8, date: "2026-10-21", amount: "30.0000", reference: "SYN-8", description: "Synthetic fee", match_id: null, method: null, age_days: 10, bucket: "0-30" },
    { side: "book", row_id: 4, date: "2026-10-21", amount: "50.0000", reference: "SYN-B4", description: "Synthetic charge", match_id: null, method: null, age_days: 10, bucket: "0-30" },
  ],
  matches: [],
  versions: [],
};

const entity = { id: "ent1", name: "Synthetic Trading LLC" };
const dataset = (id: string, kind: string, name: string) => ({
  id,
  entity_id: "ent1",
  entity_name: "Synthetic Trading LLC",
  kind,
  name,
  period_start: null,
  period_end: null,
  is_demo: true,
  created_at: "2026-10-01T08:00:00Z",
  latest_version: { id: `${id}-v1`, version_number: 1, status: "ready" },
});
const rulePacks = [
  {
    id: "pack1",
    name: "Synthetic assurance pack",
    jurisdiction: "XX",
    description: "",
    is_synthetic: true,
    created_at: "2026-10-01T08:00:00Z",
    versions: [{ id: "rp1", rule_pack_id: "pack1", version_number: 1, state: "published", published_at: null, created_at: "2026-10-01T08:00:00Z", rule_count: 3, unverified_count: 3 }],
  },
];

describe("reconciliations", () => {
  it("lists bank reconciliations and hides creation from a viewer", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/bank-reconciliations")) return jsonResponse(200, [bankListItem]);
    });
    renderRoutes([{ path: "/reconciliations", element: <ReconciliationsPage /> }], "/reconciliations");
    const link = await screen.findByRole("link", { name: "Operating account October" });
    expect(link).toHaveAttribute("href", "/reconciliations/bank/br1");
    const row = link.closest("tr")!;
    expect(within(row).getByText("Draft")).toBeInTheDocument();
    expect(within(row).getByText("Synthetic operating account")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New bank reconciliation" })).not.toBeInTheDocument();
  });

  it("shows the empty state for account reconciliations", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/account-reconciliations")) return jsonResponse(200, []);
    });
    renderRoutes([{ path: "/reconciliations", element: <ReconciliationsPage /> }], "/reconciliations?tab=account");
    expect(await screen.findByText("No account reconciliations yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New account reconciliations" })).toBeInTheDocument();
  });

  it("posts the bank reconciliation form with parsed GL accounts and opens the detail", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/entities")) return jsonResponse(200, [entity]);
      if (url.endsWith("/rule-packs")) return jsonResponse(200, rulePacks);
      if (url.includes("/datasets?") && url.includes("kind=bank_statement")) return jsonResponse(200, [dataset("ds-bank", "bank_statement", "Synthetic statement")]);
      if (url.includes("/datasets?") && url.includes("kind=general_ledger")) return jsonResponse(200, [dataset("ds-gl", "general_ledger", "Synthetic ledger")]);
      if (url.endsWith("/bank-reconciliations") && init?.method === "POST") return jsonResponse(201, bankRec);
      if (url.endsWith("/bank-reconciliations")) return jsonResponse(200, []);
    });
    const router = renderRoutes(
      [
        { path: "/reconciliations", element: <ReconciliationsPage /> },
        { path: "/reconciliations/bank/:recId", element: <p>detail page</p> },
      ],
      "/reconciliations",
    );
    expect(await screen.findByText("No bank reconciliations yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New bank reconciliation" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: "Synthetic Trading LLC" });
    await user.selectOptions(within(dialog).getByLabelText("Legal entity"), "ent1");
    await user.type(within(dialog).getByLabelText("Name"), "Operating account October");
    await user.type(within(dialog).getByLabelText("Bank account label"), "Synthetic operating account");
    await user.type(within(dialog).getByLabelText("Period start"), "2026-10-01");
    await user.type(within(dialog).getByLabelText("Period end"), "2026-10-31");
    await within(dialog).findByRole("option", { name: "Synthetic statement · v1" });
    await user.selectOptions(within(dialog).getByLabelText("Bank statement"), "ds-bank-v1");
    await within(dialog).findByRole("option", { name: "Synthetic ledger · v1" });
    await user.selectOptions(within(dialog).getByLabelText("General ledger"), "ds-gl-v1");
    await user.type(within(dialog).getByLabelText("GL accounts"), "1010, 1020");
    await within(dialog).findByRole("option", { name: /Synthetic assurance pack · v1/ });
    await user.selectOptions(within(dialog).getByLabelText("Rule pack"), "rp1");
    await user.type(within(dialog).getByLabelText("Rules prefix"), "syn.bank");
    await user.click(within(dialog).getByRole("button", { name: "Create reconciliation" }));
    expect(await screen.findByText("detail page")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/reconciliations/bank/br1");
    expect(bodyOf(fetchMock, "/bank-reconciliations")).toEqual({
      entity_id: "ent1",
      name: "Operating account October",
      account_label: "Synthetic operating account",
      period_start: "2026-10-01",
      period_end: "2026-10-31",
      statement_version_id: "ds-bank-v1",
      ledger_version_id: "ds-gl-v1",
      gl_accounts: ["1010", "1020"],
      bank_closing_balance: null,
      book_opening_balance: "0",
      rule_pack_version_id: "rp1",
      rules_prefix: "syn.bank",
    });
  });

  it("matches selected bank and book lines by hand with a reason", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/bank-reconciliations/br1/matches") && init?.method === "POST") return jsonResponse(201, { ...bankRec, items: [] });
      if (url.endsWith("/bank-reconciliations/br1")) return jsonResponse(200, bankRec);
    });
    renderRoutes([{ path: "/reconciliations/bank/:recId", element: <BankRecDetailPage /> }], "/reconciliations/bank/br1");
    expect(await screen.findByRole("heading", { name: "Operating account October" })).toBeInTheDocument();
    expect(screen.getByText(/adjusted bank − adjusted book/)).toBeInTheDocument();
    const match = screen.getByRole("button", { name: "Match selected" });
    expect(match).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Select row 7" }));
    await user.click(screen.getByRole("checkbox", { name: "Select row 8" }));
    await user.click(screen.getByRole("checkbox", { name: "Select row 4" }));
    await user.click(match);
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Two synthetic fees booked as one charge");
    await user.click(within(dialog).getByRole("button", { name: "Match" }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/bank-reconciliations/br1/matches")).toEqual({
        bank_row_ids: [7, 8],
        book_row_ids: [4],
        reason: "Two synthetic fees booked as one charge",
      }),
    );
  });
});

const process: ControlProcess = {
  id: "p1",
  entity_id: "ent1",
  entity_name: "Synthetic Trading LLC",
  name: "Purchase to pay",
  description: "",
  owner_id: null,
  owner_name: null,
  is_demo: true,
  risks: [
    { id: "r1", ref: "R1", description: "Payments to fictitious suppliers", assertions: ["occurrence"], rating: "high" },
    { id: "r2", ref: "R2", description: "Invoices recorded twice", assertions: ["accuracy"], rating: "medium" },
  ],
  controls: [
    {
      id: "c1",
      process_id: "p1",
      ref: "C1",
      title: "Supplier master changes approved",
      description: "",
      key: true,
      nature: "preventive",
      automation: "manual",
      frequency: "monthly",
      owner_id: null,
      owner_name: null,
      risk_ids: ["r1"],
      design: null,
      operating: null,
      tests: [],
      open_deficiencies: 0,
    },
  ],
  unmitigated_risk_ids: ["r2"],
};

const deficiency: Deficiency = {
  id: "d1",
  control_id: "c1",
  control_ref: "C1",
  control_title: "Supplier master changes approved",
  test_id: null,
  title: "Approval missing for two changes",
  description: "",
  classification: null,
  rationale: "",
  classified_by_name: null,
  classified_at: null,
  status: "open",
  remediation_task_id: null,
  remediation_note: "",
  created_at: "2026-10-10T08:00:00Z",
};

describe("controls", () => {
  it("renders the risk-control matrix and highlights risks without a control", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/control-processes/p1")) return jsonResponse(200, process);
    });
    renderRoutes([{ path: "/controls/processes/:processId", element: <ProcessDetailPage /> }], "/controls/processes/p1");
    expect(await screen.findByRole("heading", { name: "Purchase to pay" })).toBeInTheDocument();
    const mitigated = screen.getByText("Payments to fictitious suppliers").closest("tr")!;
    expect(within(mitigated).getByText("Supplier master changes approved")).toBeInTheDocument();
    const gap = screen.getByText("Invoices recorded twice").closest("tr")!;
    expect(within(gap).getByText("No mitigating control")).toBeInTheDocument();
    expect(gap.className).toContain("bg-red-50");
    expect(screen.queryByRole("button", { name: "Add control" })).not.toBeInTheDocument();
  });

  it("classifies a deficiency through the classify endpoint", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/deficiencies/d1/classify") && init?.method === "POST") return jsonResponse(200, { ...deficiency, classification: "significant_deficiency" });
      if (url.endsWith("/deficiencies")) return jsonResponse(200, [deficiency]);
    });
    renderRoutes([{ path: "/controls", element: <ControlsPage /> }], "/controls?tab=deficiencies");
    expect(await screen.findByText("Approval missing for two changes")).toBeInTheDocument();
    expect(screen.getByText("Not classified")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Classify Approval missing for two changes" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Classification"), "significant_deficiency");
    await user.type(within(dialog).getByLabelText("Rationale"), "Two synthetic changes lacked approval");
    await user.click(within(dialog).getByRole("button", { name: "Classify" }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/deficiencies/d1/classify")).toEqual({
        classification: "significant_deficiency",
        rationale: "Two synthetic changes lacked approval",
      }),
    );
  });

  it("does not offer deficiency decisions to an analyst", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/deficiencies")) return jsonResponse(200, [deficiency]);
    });
    renderRoutes([{ path: "/controls", element: <ControlsPage /> }], "/controls?tab=deficiencies");
    expect(await screen.findByText("Approval missing for two changes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Classify/ })).not.toBeInTheDocument();
  });
});

const providers: ConnectorStatusInfo["providers"] = [
  { provider: "zoho_books", label: "Zoho Books", auth: "oauth", kinds: ["general_ledger"], scopes: [], configured: false, mapping_status: "unverified" },
  { provider: "odoo", label: "Odoo", auth: "api_key", kinds: ["general_ledger", "trial_balance"], scopes: [], configured: true, mapping_status: "unverified" },
];

const odoo: Connector = {
  id: "cn1",
  entity_id: "ent1",
  entity_name: "Synthetic Trading LLC",
  provider: "odoo",
  provider_label: "Odoo",
  auth: "api_key",
  name: "Synthetic Odoo",
  status: "pending",
  scopes: [],
  config: { base_url: "https://odoo.example.test", database: "synthetic", username: "reader" },
  has_credentials: true,
  kinds: ["general_ledger", "trial_balance"],
  datasets: {},
  mapping_status: "unverified",
  last_sync_at: null,
  last_error: "",
  syncs: [],
  created_at: "2026-10-15T08:00:00Z",
};

describe("connectors", () => {
  it("shows Not available when connectors are disabled", async () => {
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("org_admin"));
      if (url.endsWith("/connectors/status")) return jsonResponse(200, { enabled: false, providers: [] });
    });
    renderRoutes([{ path: "/connectors", element: <ConnectorsPage /> }], "/connectors");
    expect(await screen.findByText("Not available")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add connector" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/api/connectors"))).toBe(false);
  });

  it("posts the Odoo form with the API key as a password field", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("org_admin"));
      if (url.endsWith("/connectors/status")) return jsonResponse(200, { enabled: true, providers });
      if (url.endsWith("/entities")) return jsonResponse(200, [entity]);
      if (url.endsWith("/connectors") && init?.method === "POST") return jsonResponse(201, odoo);
      if (url.endsWith("/connectors")) return jsonResponse(200, []);
    });
    renderRoutes([{ path: "/connectors", element: <ConnectorsPage /> }], "/connectors");
    expect(await screen.findByText(/Field mappings have not been verified/)).toBeInTheDocument();
    expect(await screen.findByText("No connectors yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add connector" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("option", { name: /Zoho Books/ })).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText("System"), "odoo");
    await within(dialog).findByRole("option", { name: "Synthetic Trading LLC" });
    await user.selectOptions(within(dialog).getByLabelText("Legal entity"), "ent1");
    await user.type(within(dialog).getByLabelText("Name"), "Synthetic Odoo");
    await user.type(within(dialog).getByLabelText("Server URL"), "https://odoo.example.test");
    await user.type(within(dialog).getByLabelText("Database"), "synthetic");
    await user.type(within(dialog).getByLabelText("Username"), "reader");
    const key = within(dialog).getByLabelText("API key");
    expect(key).toHaveAttribute("type", "password");
    await user.type(key, "synthetic-key-123");
    await user.click(within(dialog).getByRole("button", { name: "Add connector" }));
    await waitFor(() =>
      expect(bodyOf(fetchMock, "/connectors")).toEqual({
        entity_id: "ent1",
        provider: "odoo",
        name: "Synthetic Odoo",
        config: { base_url: "https://odoo.example.test", database: "synthetic", username: "reader" },
        api_key: "synthetic-key-123",
      }),
    );
  });

  it("lists a connector with its non-secret settings and lets an admin test it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("org_admin"));
      if (url.endsWith("/connectors/status")) return jsonResponse(200, { enabled: true, providers });
      if (url.endsWith("/connectors/cn1/test") && init?.method === "POST") return jsonResponse(200, { ...odoo, status: "connected" });
      if (url.endsWith("/connectors")) return jsonResponse(200, [odoo]);
    });
    renderRoutes([{ path: "/connectors", element: <ConnectorsPage /> }], "/connectors");
    expect(await screen.findByText("Synthetic Odoo")).toBeInTheDocument();
    expect(screen.getByText("https://odoo.example.test")).toBeInTheDocument();
    expect(screen.getByText("Mapping unverified")).toBeInTheDocument();
    expect(screen.getByText("Credentials stored")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/connectors/cn1/test") && (i as RequestInit)?.method === "POST")).toBe(true));
  });
});
