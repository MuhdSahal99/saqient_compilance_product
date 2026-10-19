import type { ReactNode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import i18n from "@/i18n";
import { AuthProvider } from "@/lib/auth";
import { jsonResponse } from "@/test/utils";
import type { Role } from "@/lib/types";
import type { Engagement, EngagementSummary, Letter } from "@/lib/audit";
import { AppLayout } from "@/components/layout";
import { EngagementsPage } from "./EngagementsPage";
import { EngagementDetailPage } from "./EngagementDetailPage";
import { PortalPage } from "./PortalPage";

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

function renderRoutes(routes: { path: string; element: ReactNode }[], route: string, withLayout = false) {
  const tree = withLayout
    ? [{ element: <AuthProvider><AppLayout /></AuthProvider>, children: routes }]
    : routes.map((r) => ({ path: r.path, element: <AuthProvider>{r.element}</AuthProvider> }));
  const router = createMemoryRouter(tree, { initialEntries: [route] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await act(() => i18n.changeLanguage("en"));
});

const summary: EngagementSummary = {
  id: "e1",
  entity_id: "ent1",
  entity_name: "Synthetic Trading LLC",
  kind: "external_audit",
  name: "FY2026 statutory audit",
  period_start: "2026-01-01",
  period_end: "2026-12-31",
  currency: "AED",
  status: "fieldwork",
  is_demo: true,
  created_at: "2026-10-01T08:00:00Z",
};

const engagement: Engagement = {
  ...summary,
  closed_at: null,
  cy_tb_version_id: null,
  py_tb_version_id: null,
  rule_pack_version_id: null,
  rules_prefix: null,
  members: [],
  phases: [
    { phase: "planning", budget_hours: "40.00", actual_hours: "52.50", variance_hours: "-12.50", used_share: "1.3125" },
    { phase: "fieldwork", budget_hours: "120.00", actual_hours: "0.00", variance_hours: "120.00", used_share: "0.0000" },
    { phase: "completion", budget_hours: "0.00", actual_hours: "0.00", variance_hours: "0.00", used_share: null },
    { phase: "reporting", budget_hours: "0.00", actual_hours: "0.00", variance_hours: "0.00", used_share: null },
  ],
  budget_hours: "160.00",
  actual_hours: "52.50",
};

describe("engagements list", () => {
  it("renders engagements with their status and offers creation to a reviewer", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/engagements")) return jsonResponse(200, [summary]);
    });
    renderRoutes([{ path: "/engagements", element: <EngagementsPage /> }], "/engagements");
    expect(await screen.findByRole("link", { name: "FY2026 statutory audit" })).toHaveAttribute("href", "/engagements/e1");
    expect(screen.getByText("Synthetic Trading LLC")).toBeInTheDocument();
    const row = screen.getByRole("link", { name: "FY2026 statutory audit" }).closest("tr")!;
    expect(within(row).getByText("Fieldwork")).toBeInTheDocument();
    expect(within(row).getByText("External audit")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New engagement" })).toBeInTheDocument();
  });

  it("does not offer creation to an analyst and shows the empty state", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/engagements")) return jsonResponse(200, []);
    });
    renderRoutes([{ path: "/engagements", element: <EngagementsPage /> }], "/engagements");
    expect(await screen.findByText("No engagements yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New engagement" })).not.toBeInTheDocument();
  });

  it("posts the create form and validates the period order", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/entities")) return jsonResponse(200, [{ id: "ent1", name: "Synthetic Trading LLC" }]);
      if (url.endsWith("/engagements") && init?.method === "POST") return jsonResponse(201, engagement);
      if (url.endsWith("/engagements")) return jsonResponse(200, []);
      if (url.endsWith("/engagements/e1")) return jsonResponse(200, engagement);
    });
    renderRoutes(
      [
        { path: "/engagements", element: <EngagementsPage /> },
        { path: "/engagements/:engagementId", element: <p>detail page</p> },
      ],
      "/engagements",
    );
    await user.click(await screen.findByRole("button", { name: "New engagement" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(await within(dialog).findByLabelText("Legal entity"), "ent1");
    await user.type(within(dialog).getByLabelText("Name"), "FY2026 statutory audit");
    await user.type(within(dialog).getByLabelText("Period start"), "2026-12-31");
    await user.type(within(dialog).getByLabelText("Period end"), "2026-01-01");
    await user.click(within(dialog).getByRole("button", { name: "Create engagement" }));
    expect(await within(dialog).findByText("Must be on or after the start date.")).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Period start"));
    await user.type(within(dialog).getByLabelText("Period start"), "2026-01-01");
    await user.clear(within(dialog).getByLabelText("Period end"));
    await user.type(within(dialog).getByLabelText("Period end"), "2026-12-31");
    await user.click(within(dialog).getByRole("button", { name: "Create engagement" }));
    expect(await screen.findByText("detail page")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/engagements") && (i as RequestInit)?.method === "POST")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      entity_id: "ent1",
      kind: "external_audit",
      name: "FY2026 statutory audit",
      period_start: "2026-01-01",
      period_end: "2026-12-31",
    });
  });
});

describe("engagement detail", () => {
  it("shows budget against actual hours as the server sent them", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/engagements/e1")) return jsonResponse(200, engagement);
      if (url.endsWith("/engagements/e1/time-entries")) return jsonResponse(200, []);
    });
    renderRoutes([{ path: "/engagements/:engagementId", element: <EngagementDetailPage /> }], "/engagements/e1");
    expect(await screen.findByRole("heading", { name: "FY2026 statutory audit" })).toBeInTheDocument();
    expect(screen.getByText("-12.50")).toBeInTheDocument();
    expect(screen.getByText("1.3125")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Move to/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit budget" })).not.toBeInTheDocument();
  });

  it("disables Issue letter while the letter has no points", async () => {
    const letter: Letter = { points: [], versions: [] };
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/engagements/e1")) return jsonResponse(200, engagement);
      if (url.endsWith("/engagements/e1/letter")) return jsonResponse(200, letter);
    });
    renderRoutes([{ path: "/engagements/:engagementId", element: <EngagementDetailPage /> }], "/engagements/e1?tab=letter");
    expect(await screen.findByText("No points yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Issue letter" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add new confirmed findings" })).toBeEnabled();
    expect(screen.getByText("Not issued yet")).toBeInTheDocument();
  });

  it("enables Issue letter for included points and links issued versions to their exports", async () => {
    const letter: Letter = {
      points: [
        {
          id: "lp1",
          finding_id: "f1",
          finding_title: "Bank reconciliation not reviewed",
          finding_status: "confirmed",
          severity: "high",
          observation: "Synthetic observation text.",
          include: true,
          recommendation: "Review reconciliations monthly.",
          management_response: "",
          response_owner: "",
          response_due: null,
          evidence_refs: ["Synthetic policy · paragraph 4"],
        },
      ],
      versions: [{ version: 1, issued_by_name: "Demo Reviewer", issued_at: "2026-10-15T08:00:00Z", points: 1 }],
    };
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/engagements/e1")) return jsonResponse(200, engagement);
      if (url.endsWith("/engagements/e1/letter")) return jsonResponse(200, letter);
    });
    renderRoutes([{ path: "/engagements/:engagementId", element: <EngagementDetailPage /> }], "/engagements/e1?tab=letter");
    expect(await screen.findByText("Bank reconciliation not reviewed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Issue letter" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/api/engagements/e1/letter/1/export?format=pdf");
    expect(screen.getByRole("link", { name: "HTML" })).toHaveAttribute("href", "/api/engagements/e1/letter/1/export?format=html");
  });
});

describe("client portal", () => {
  it("restricts a client to the portal: one nav item, redirect from other pages, no dashboard call", async () => {
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("client"));
      if (url.endsWith("/portal/requests"))
        return jsonResponse(200, [
          {
            id: "r1",
            ref: "PBC-1",
            title: "Bank statements for December",
            description: "Synthetic request.",
            due_date: "2026-11-15",
            status: "requested",
            client_note: "",
            review_note: "",
            submitted_at: null,
            files: [],
          },
        ]);
    });
    const router = renderRoutes(
      [
        { path: "/", element: <p>overview page</p> },
        { path: "/engagements", element: <p>engagements page</p> },
        { path: "/portal", element: <PortalPage /> },
      ],
      "/engagements",
      true,
    );
    expect(await screen.findByText("Bank statements for December")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/portal");
    expect(screen.queryByText("engagements page")).not.toBeInTheDocument();
    const nav = screen.getAllByRole("navigation", { name: "Primary" })[0]!;
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/portal"]);
    expect(within(nav).queryByText("Engagements")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit for review" })).toBeDisabled();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/dashboard"))).toBe(false));
  });

  it("shows the full navigation, including Engagements, to staff", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.endsWith("/dashboard")) return jsonResponse(200, { findings_proposed: 0, open_tasks: 0 });
    });
    renderRoutes([{ path: "/", element: <p>overview page</p> }], "/", true);
    expect(await screen.findByText("overview page")).toBeInTheDocument();
    const nav = screen.getAllByRole("navigation", { name: "Primary" })[0]!;
    expect(within(nav).getByRole("link", { name: "Engagements" })).toHaveAttribute("href", "/engagements");
    expect(within(nav).queryByRole("link", { name: "My requests" })).not.toBeInTheDocument();
  });
});
