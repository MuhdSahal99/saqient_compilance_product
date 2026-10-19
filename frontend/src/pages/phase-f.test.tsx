import type { ReactNode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import i18n from "@/i18n";
import { AuthProvider } from "@/lib/auth";
import { jsonResponse } from "@/test/utils";
import type { Role } from "@/lib/types";
import type { ContentPack, OrgAISettings } from "@/lib/content-packs";
import { ContentPackDetailPage, ContentPacksPage } from "./ContentPacksPage";
import { SettingsPage } from "./SettingsPage";

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
  return call ? (call[1] as RequestInit).body : undefined;
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await act(() => i18n.changeLanguage("en"));
});

const sha = "a".repeat(64);
const pack: ContentPack = {
  id: "aml-cft",
  version: "0.1.0",
  title: "AML/CFT programme review (synthetic)",
  sector: "financial_services",
  jurisdiction: "generic",
  status: "draft",
  synthetic: true,
  disclaimer: "Synthetic demonstration content — not legal guidance.",
  description: "Draft checks for a synthetic anti-money-laundering programme.",
  dataset_kinds: ["customer_master", "fixed_assets"],
  open_questions: ["Which customer risk rating scale does the entity use?"],
  manifest_sha256: sha,
  checklists: [
    {
      name: "AML programme documents",
      requirements: [
        { code: "AML-01", title: "Programme owner named", category: "Governance", severity: "high", check_type: "required_text" },
        { code: "FA-01", title: "Depreciation agrees to policy", category: "Assets", severity: "medium", check_type: "depreciation_recalc" },
      ],
    },
  ],
  rule_count: 4,
  installs: [],
};
const installed: ContentPack = {
  ...pack,
  installs: [
    {
      id: "i1",
      pack_version: "0.1.0",
      manifest_sha256: sha,
      checklist_version_ids: ["cv1"],
      rule_pack_version_id: "rpv1",
      installed_by_name: "Demo Admin",
      created_at: "2026-10-18T08:00:00Z",
    },
  ],
};

describe("content packs", () => {
  it("lists packs with sector, draft synthetic badge, counts and install state", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/content-packs")) return jsonResponse(200, [pack, { ...installed, id: "esr", title: "ESR and UBO (synthetic)" }]);
    });
    renderRoutes([{ path: "/content-packs", element: <ContentPacksPage /> }], "/content-packs");
    const row = (await screen.findByRole("link", { name: pack.title })).closest("tr")!;
    expect(within(row).getByText("Financial services")).toBeInTheDocument();
    expect(within(row).getByText("Draft · synthetic")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(within(row).getByText("4")).toBeInTheDocument();
    expect(within(row).getByText("Not installed")).toBeInTheDocument();
    const other = screen.getByRole("link", { name: "ESR and UBO (synthetic)" }).closest("tr")!;
    expect(within(other).getByText("Installed v0.1.0")).toBeInTheDocument();
  });

  it("shows the empty state", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/content-packs")) return jsonResponse(200, []);
    });
    renderRoutes([{ path: "/content-packs", element: <ContentPacksPage /> }], "/content-packs");
    expect(await screen.findByText("No content packs available")).toBeInTheDocument();
  });

  it("shows the disclaimer, open questions and requirements, and hides install from a reviewer", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/content-packs/aml-cft")) return jsonResponse(200, pack);
    });
    renderRoutes([{ path: "/content-packs/:packId", element: <ContentPackDetailPage /> }], "/content-packs/aml-cft");
    expect(await screen.findByRole("heading", { name: pack.title })).toBeInTheDocument();
    expect(screen.getAllByText(pack.disclaimer).length).toBeGreaterThan(0);
    expect(screen.getByText("Which customer risk rating scale does the entity use?")).toBeInTheDocument();
    expect(screen.getByText("Depreciation recalculation")).toBeInTheDocument();
    expect(screen.getByText("Fixed asset register")).toBeInTheDocument();
    expect(screen.getByTitle(sha)).toHaveTextContent("aaaaaaaaaaaa…");
    expect(screen.queryByRole("button", { name: "Install pack" })).not.toBeInTheDocument();
    expect(screen.getByText("Only an organisation admin can install a pack.")).toBeInTheDocument();
  });

  it("lets an org admin install after confirming, then links the installed drafts", async () => {
    const user = userEvent.setup();
    let done = false;
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("org_admin"));
      if (url.endsWith("/content-packs/aml-cft/install") && init?.method === "POST") {
        done = true;
        return jsonResponse(201, installed);
      }
      if (url.endsWith("/content-packs/aml-cft")) return jsonResponse(200, done ? installed : pack);
    });
    renderRoutes([{ path: "/content-packs/:packId", element: <ContentPackDetailPage /> }], "/content-packs/aml-cft");
    await user.click(await screen.findByRole("button", { name: "Install pack" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/review, verify and publish/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Install pack" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/content-packs/aml-cft/install") && i?.method === "POST")).toBe(true));
    expect(await screen.findByRole("link", { name: "Open installed checklist 1" })).toHaveAttribute("href", "/checklists/versions/cv1");
    expect(screen.getByRole("link", { name: "Open installed rule pack" })).toHaveAttribute("href", "/rule-packs/versions/rpv1");
    expect(screen.queryByRole("button", { name: "Install pack" })).not.toBeInTheDocument();
  });

  it("shows a conflict when the pack is already installed", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("org_admin"));
      if (url.endsWith("/content-packs/aml-cft/install") && init?.method === "POST") return jsonResponse(409, { detail: "This pack version is already installed." });
      if (url.endsWith("/content-packs/aml-cft")) return jsonResponse(200, pack);
    });
    renderRoutes([{ path: "/content-packs/:packId", element: <ContentPackDetailPage /> }], "/content-packs/aml-cft");
    await user.click(await screen.findByRole("button", { name: "Install pack" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Install pack" }));
    expect(await screen.findByText("This pack version is already installed.")).toBeInTheDocument();
  });

  it("returns not found for an unknown pack", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
    });
    renderRoutes([{ path: "/content-packs/:packId", element: <ContentPackDetailPage /> }], "/content-packs/nope");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});

const aiStatus = { enabled: false, provider: "mock", model: "mock-1", available_features: [], is_mock: false, note: "", deployment_enabled: true, org_opted_in: false };
const aiSettings: OrgAISettings = { deployment_available: true, provider: "mock", model: "mock-1", is_mock: true, opted_in: false, opted_in_at: null };

function settingsFetch(role: Role, settings: OrgAISettings, onPut?: () => Response) {
  return mockFetch((url, init) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me(role));
    if (url.endsWith("/ai/status")) return jsonResponse(200, aiStatus);
    if (url.endsWith("/org/ai-settings") && init?.method === "PUT") return onPut?.();
    if (url.endsWith("/org/ai-settings")) return jsonResponse(200, settings);
    if (url.includes("/members")) return jsonResponse(200, []);
  });
}

describe("AI opt-in", () => {
  it("lets an org admin opt in after a confirmation that explains what is sent", async () => {
    const user = userEvent.setup();
    const fetchMock = settingsFetch("org_admin", aiSettings, () => jsonResponse(200, { ...aiSettings, opted_in: true, opted_in_at: "2026-10-19T08:00:00Z" }));
    renderRoutes([{ path: "/settings", element: <SettingsPage /> }], "/settings");
    expect(await screen.findByText("Not opted in")).toBeInTheDocument();
    expect(screen.getByText("Mock provider")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Opt in to AI suggestions" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/sent to the configured model/)).toBeInTheDocument();
    expect(within(dialog).getByText(/reviewer's acceptance/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Opt in to AI suggestions" }));
    await waitFor(() => expect(bodyOf(fetchMock, "/org/ai-settings", "PUT")).toBe(JSON.stringify({ opted_in: true })));
    expect(await screen.findByText(/Opted in since/)).toBeInTheDocument();
  });

  it("disables opting in with the reason when the deployment has no provider", async () => {
    settingsFetch("org_admin", { ...aiSettings, deployment_available: false, provider: "disabled", model: null, is_mock: false });
    renderRoutes([{ path: "/settings", element: <SettingsPage /> }], "/settings");
    expect(await screen.findByText("No provider configured")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Opt in to AI suggestions" })).toBeDisabled();
    expect(screen.getByText(/cannot opt in/)).toBeInTheDocument();
  });

  it("does not offer the switch to a reviewer", async () => {
    settingsFetch("reviewer", { ...aiSettings, opted_in: true, opted_in_at: "2026-10-01T08:00:00Z" });
    renderRoutes([{ path: "/settings", element: <SettingsPage /> }], "/settings");
    expect(await screen.findByText(/Opted in since/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Opt (in to|out of) AI suggestions/ })).not.toBeInTheDocument();
    expect(screen.getByText("Only an organisation admin can change the opt-in.")).toBeInTheDocument();
  });
});
