import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import i18n from "@/i18n";
import { AuthProvider } from "@/lib/auth";
import { jsonResponse } from "@/test/utils";
import type { DatasetDetail, DatasetVersion, Role } from "@/lib/types";
import { DatasetDetailPage } from "./DatasetDetailPage";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("sonner", async (orig) => {
  const actual = await orig<typeof import("sonner")>();
  return { ...actual, toast: Object.assign(vi.fn(), actual.toast, { error: toastError }) };
});

const org = { id: "o1", name: "Alpha Synthetic Audit Team", slug: "alpha-synthetic", is_demo: true };
function me(role: Role) {
  return {
    user: { id: "u1", email: "analyst@alpha.example", full_name: "Demo Analyst", preferred_locale: "en", is_demo: true },
    org,
    role,
    memberships: [{ org, role }],
    csrf_token: "csrf",
    demo_mode: true,
    ai_enabled: false,
  };
}

function version(n: number): DatasetVersion {
  return {
    id: `v${n}`,
    version_number: n,
    original_filename: `gl-${n}.csv`,
    file_format: "csv",
    size_bytes: 900,
    raw_sha256: "a".repeat(64),
    status: "ready",
    failure_message: null,
    source_columns: ["Journal"],
    source_row_count: 4,
    column_mapping: {},
    parse_options: {},
    mapping_confirmed_at: null,
    parquet_sha256: null,
    row_count: 4,
    derived_fields: [],
    totals: {},
    errors: [],
    error_count: 0,
    created_at: "2026-10-21T10:00:00Z",
    processed_at: null,
  };
}

function dataset(versions: DatasetVersion[]): DatasetDetail {
  return {
    id: "d1",
    entity_id: "e1",
    entity_name: "Synthetic Trading LLC (demo)",
    kind: "general_ledger",
    name: "January 2026 ledger",
    period_start: null,
    period_end: null,
    is_demo: false,
    created_at: "2026-10-21T10:00:00Z",
    latest_version: versions[versions.length - 1] ?? null,
    versions,
  };
}

type Handler = (url: string, init?: RequestInit) => Response | undefined;
function mockFetch(handler: Handler) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init) ?? jsonResponse(404, { detail: "Not found." })),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderPage() {
  const router = createMemoryRouter(
    [
      { path: "/datasets/:datasetId", element: <AuthProvider><DatasetDetailPage /></AuthProvider> },
      { path: "/datasets", element: <p>Dataset list</p> },
    ],
    { initialEntries: ["/datasets/d1"] },
  );
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

function common(role: Role, detail: DatasetDetail): Handler {
  return (url) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me(role));
    if (url.endsWith("/datasets/d1")) return jsonResponse(200, detail);
    if (url.endsWith("/dataset-kinds")) return jsonResponse(200, []);
    const m = url.match(/\/dataset-versions\/v(\d)$/);
    if (m) return jsonResponse(200, { ...version(Number(m[1])), dataset_id: "d1", kind: "general_ledger", preview: [], latest_job: null });
    if (url.includes("/rows")) return jsonResponse(200, { version_id: "v1", columns: [], rows: [], total: 0 });
    return undefined;
  };
}

test("an analyst deletes a wrongly uploaded dataset after confirming", async () => {
  let deleted = "";
  const base = common("analyst", dataset([version(1)]));
  mockFetch((url, init) => {
    if (init?.method === "DELETE") {
      deleted = url;
      return new Response(null, { status: 204 });
    }
    return base(url, init);
  });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Delete dataset" }));
  // One version only: no separate version delete is offered.
  expect(screen.queryByRole("button", { name: "Delete v1" })).not.toBeInTheDocument();
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(/cannot be deleted; upload a corrected version/)).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(deleted).toMatch(/\/api\/datasets\/d1$/));
  expect(await screen.findByText("Dataset list")).toBeInTheDocument();
});

test("a version in use is refused with the server's reason", async () => {
  const base = common("reviewer", dataset([version(1), version(2)]));
  mockFetch((url, init) => {
    if (init?.method === "DELETE" && url.endsWith("/dataset-versions/v2")) {
      return jsonResponse(409, { detail: "This data is used in 1 place(s), such as a review." });
    }
    return base(url, init);
  });
  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Delete v2" }));
  await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(toastError).toHaveBeenCalledWith(expect.stringMatching(/used in 1 place/)));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Delete v2" })).toBeInTheDocument();
});

test("viewers see no delete buttons", async () => {
  mockFetch(common("viewer", dataset([version(1), version(2)])));
  renderPage();
  expect(await screen.findByText("January 2026 ledger", { selector: "h1" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete dataset" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Delete v/ })).not.toBeInTheDocument();
});
