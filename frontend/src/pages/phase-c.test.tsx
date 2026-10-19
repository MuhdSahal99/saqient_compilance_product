import type { ReactNode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import i18n from "@/i18n";
import { AuthProvider } from "@/lib/auth";
import { jsonResponse } from "@/test/utils";
import type { Role, Workpaper } from "@/lib/types";
import { WorkpaperDetailPage } from "./WorkpaperDetailPage";
import { WorkpapersPage } from "./WorkpapersPage";

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

/** The forms warn about unsaved changes with useBlocker, which needs a data router. */
function renderRoute(path: string, element: ReactNode, route: string) {
  const router = createMemoryRouter([{ path, element: <AuthProvider>{element}</AuthProvider> }], { initialEntries: [route] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await act(() => i18n.changeLanguage("en"));
});

const draftRule = {
  rule_id: "r1",
  rule_key: "syn.ct.rate",
  value: "0.09",
  value_sha256: null,
  value_type: "decimal",
  unit: "ratio",
  rule_pack_version_id: "rpv1",
  pack_name: "Synthetic CT pack",
  pack_version: 2,
  verification_status: "draft",
  effective_from: "2026-01-01",
  effective_to: null,
};

const workpaper: Workpaper = {
  id: "w1",
  entity_id: "e1",
  entity_name: "Synthetic Trading LLC",
  kind: "corporate_tax",
  title: "FY2026 corporate tax",
  period_start: "2026-01-01",
  period_end: "2026-12-31",
  currency: "AED",
  status: "draft",
  computed_at: "2026-10-10T08:00:00Z",
  is_demo: true,
  created_at: "2026-10-01T08:00:00Z",
  rule_pack_version_id: "rpv1",
  rules_prefix: "syn.ct",
  calc_version: "ct-1.0",
  result_hash: "c".repeat(64),
  warnings: ["Rule syn.ct.rate in Synthetic CT pack v2 is a draft and has not been verified."],
  snapshots: [],
  lines: [
    {
      id: "l1",
      source: "manual",
      section: "input",
      line_key: "accounting_profit",
      category: "input",
      label: "Accounting profit",
      ordinal: 1,
      amount: "1000000.0000",
      value: null,
      formula_id: null,
      explanation: [],
      rule_snapshots: [],
      evidence: [],
      note: "",
    },
    {
      id: "l2",
      source: "computed",
      section: "result",
      line_key: "ct_payable",
      category: "computed",
      label: "Corporate tax indicated",
      ordinal: 2,
      amount: "56250.0000",
      value: null,
      formula_id: "ct.payable.v1",
      explanation: [{ label: "Tax at rate", expression: "625000.0000 × 0.09", value: "56250.0000" }],
      rule_snapshots: [draftRule] as Workpaper["lines"][number]["rule_snapshots"],
      evidence: [],
      note: "",
    },
  ],
};

function renderDetail(role: Role, wp: Workpaper = workpaper) {
  mockFetch((url) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me(role));
    if (url.endsWith("/workpapers/w1")) return jsonResponse(200, wp);
  });
  renderRoute("/workpapers/:workpaperId", <WorkpaperDetailPage />, "/workpapers/w1");
}

describe("workpaper detail", () => {
  it("renders computed lines with their steps, rules and the unverified warning", async () => {
    const user = userEvent.setup();
    renderDetail("analyst");
    expect(await screen.findByRole("heading", { name: "FY2026 corporate tax" })).toBeInTheDocument();
    expect(screen.getByText("Unverified rules were used")).toBeInTheDocument();
    expect(screen.getByText(/Rule syn\.ct\.rate in Synthetic CT pack v2 is a draft/)).toBeInTheDocument();
    expect(screen.getByText("Accounting profit")).toBeInTheDocument();
    const line = screen.getByRole("button", { name: /Corporate tax indicated/ });
    expect(line).toHaveAttribute("aria-expanded", "false");
    await user.click(line);
    expect(line).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("625000.0000 × 0.09 = 56250.0000")).toBeInTheDocument();
    expect(screen.getByText("ct.payable.v1")).toBeInTheDocument();
    expect(screen.getByText("syn.ct.rate")).toBeInTheDocument();
    expect(screen.getByText("Synthetic CT pack v2")).toBeInTheDocument();
  });

  it("shows Sign off to a reviewer but not to an analyst", async () => {
    renderDetail("analyst");
    expect(await screen.findByRole("button", { name: "Compute" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign off" })).not.toBeInTheDocument();
  });

  it("offers Sign off, not Reopen, to a reviewer on a draft", async () => {
    renderDetail("reviewer");
    expect(await screen.findByRole("button", { name: "Sign off" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
  });

  it("shows snapshot exports and Post to loss register on a signed-off CT workpaper", async () => {
    renderDetail("reviewer", {
      ...workpaper,
      status: "signed_off",
      snapshots: [{ version: 1, signed_off_by_name: "Demo Reviewer", signed_off_at: "2026-10-11T08:00:00Z", result_hash: "d".repeat(64) }],
    });
    expect(await screen.findByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post to loss register" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Compute" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/api/workpapers/w1/snapshots/1/export?format=pdf");
  });

  it("shows the server's 422 message when an input is rejected", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/workpapers/w1/inputs/exempt_dividends") && init?.method === "PUT")
        return jsonResponse(422, { detail: "Category must be one of: input." });
      if (url.endsWith("/workpapers/w1")) return jsonResponse(200, workpaper);
    });
    renderRoute("/workpapers/:workpaperId", <WorkpaperDetailPage />, "/workpapers/w1");
    await user.click(await screen.findByRole("button", { name: "Add input" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Key"), "exempt_dividends");
    await user.selectOptions(within(dialog).getByLabelText("Category"), "exempt_income");
    await user.type(within(dialog).getByLabelText("Label"), "Exempt dividends");
    await user.type(within(dialog).getByLabelText("Amount"), "-2500.50");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Category must be one of: input.")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).includes("/inputs/") && (i as RequestInit)?.method === "PUT")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      category: "exempt_income",
      label: "Exempt dividends",
      amount: "-2500.50",
      value: null,
      note: "",
      evidence: [],
    });
  });
});

describe("loss register", () => {
  it("shows the balance and entries for the chosen entity", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/entities")) return jsonResponse(200, [{ id: "e1", name: "Synthetic Trading LLC" }]);
      if (url.endsWith("/entities/e1/tax-losses"))
        return jsonResponse(200, {
          entity_id: "e1",
          currency: "AED",
          balance: "150000.0000",
          entries: [
            {
              id: "le1",
              entity_id: "e1",
              kind: "incurred",
              period_start: "2025-01-01",
              period_end: "2025-12-31",
              amount: "200000.0000",
              signed_amount: "200000.0000",
              currency: "AED",
              workpaper_id: null,
              counterparty_entity_id: null,
              counterparty_name: null,
              transfer_id: null,
              explanation: [],
              rule_snapshots: [],
              evidence: [],
              note: "FY2025 return ref SYN-1",
              created_at: "2026-02-01T08:00:00Z",
            },
            {
              id: "le2",
              entity_id: "e1",
              kind: "used",
              period_start: "2026-01-01",
              period_end: "2026-12-31",
              amount: "50000.0000",
              signed_amount: "-50000.0000",
              currency: "AED",
              workpaper_id: "w1",
              counterparty_entity_id: null,
              counterparty_name: null,
              transfer_id: null,
              explanation: [],
              rule_snapshots: [],
              evidence: [],
              note: "",
              created_at: "2026-10-01T08:00:00Z",
            },
          ],
        });
    });
    renderRoute("/workpapers", <WorkpapersPage />, "/workpapers?tab=losses&entity=e1");
    expect(await screen.findByText("Balance carried forward")).toBeInTheDocument();
    expect(screen.getByText("150000.0000")).toBeInTheDocument();
    expect(screen.getByText("-50000.0000")).toBeInTheDocument();
    expect(screen.getByText("FY2025 return ref SYN-1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add entry" })).toBeInTheDocument();
  });

  it("asks for an entity before showing the register", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/entities")) return jsonResponse(200, []);
    });
    renderRoute("/workpapers", <WorkpapersPage />, "/workpapers?tab=losses");
    expect(await screen.findByText("Choose a legal entity")).toBeInTheDocument();
  });
});

describe("transfer pricing", () => {
  it("runs the threshold check and renders the result lines with warnings", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/entities")) return jsonResponse(200, [{ id: "e1", name: "Synthetic Trading LLC" }]);
      if (url.endsWith("/rule-packs"))
        return jsonResponse(200, [
          {
            id: "p1",
            name: "Synthetic TP pack",
            jurisdiction: "AE",
            description: "",
            is_synthetic: true,
            created_at: "",
            versions: [{ id: "rpv1", rule_pack_id: "p1", version_number: 1, state: "published", unverified_count: 2 }],
          },
        ]);
      if (url.endsWith("/entities/e1/related-parties"))
        return jsonResponse(200, [{ id: "rp1", entity_id: "e1", name: "Synthetic Parent Holdings", relation: "parent", jurisdiction: "AE", note: "", is_demo: true }]);
      if (url.endsWith("/entities/e1/rp-transactions")) return jsonResponse(200, []);
      if (url.endsWith("/entities/e1/tp/check") && init?.method === "POST")
        return jsonResponse(200, {
          currency: "AED",
          rp_total: "4200000.0000",
          transaction_count: 3,
          calc_version: "tp-1.0",
          result_hash: "e".repeat(64),
          warnings: ["Rule syn.tp.disclosure_threshold is a draft."],
          lines: [
            {
              key: "disclosure_indicated",
              label: "Disclosure form indicated",
              section: "test",
              formula_id: "tp.disclosure.v1",
              amount: null,
              value: "true",
              explanation: [{ label: "Compare", expression: "4200000.0000 >= 4000000", value: "true" }],
              rule_snapshots: [],
            },
          ],
        });
    });
    renderRoute("/workpapers", <WorkpapersPage />, "/workpapers?tab=tp&entity=e1");
    expect(await screen.findByText("Synthetic Parent Holdings")).toBeInTheDocument();
    await user.selectOptions(await screen.findByLabelText("Rule pack"), "rpv1");
    await user.type(screen.getByLabelText("Rules prefix"), "syn.tp");
    await user.type(screen.getByLabelText("Period start", { selector: "#tpc-start" }), "2026-01-01");
    await user.type(screen.getByLabelText("Period end", { selector: "#tpc-end" }), "2026-12-31");
    await user.type(screen.getByLabelText("Entity revenue"), "90000000");
    expect(screen.getByRole("link", { name: "Disclosure CSV" })).toHaveAttribute(
      "href",
      "/api/entities/e1/tp/disclosure.csv?period_start=2026-01-01&period_end=2026-12-31",
    );
    await user.click(screen.getByRole("button", { name: "Run check" }));
    expect(await screen.findByText("Disclosure form indicated")).toBeInTheDocument();
    expect(screen.getByText("4200000.0000")).toBeInTheDocument();
    expect(screen.getByText("Unverified rules were used")).toBeInTheDocument();
    expect(screen.getByText("Rule syn.tp.disclosure_threshold is a draft.")).toBeInTheDocument();
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/tp/check"))!;
      expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
        rule_pack_version_id: "rpv1",
        rules_prefix: "syn.tp",
        period_start: "2026-01-01",
        period_end: "2026-12-31",
        entity_revenue: "90000000",
        in_mne_group: null,
        group_revenue: null,
      });
    });
  });
});
