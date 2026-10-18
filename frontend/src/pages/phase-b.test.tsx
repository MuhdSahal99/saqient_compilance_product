import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "@/i18n";
import { jsonResponse, renderWithProviders } from "@/test/utils";
import type { Role, XmlEvidence } from "@/lib/types";
import { EvidenceItem } from "@/components/evidence";
import { EInvoicesPage } from "./EInvoicesPage";
import { TaxCalendarPage } from "./TaxCalendarPage";
import { TasksPage } from "./TasksPage";
import { ReviewsPage } from "./ReviewsPage";
import { Route, Routes } from "react-router-dom";

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
  await act(() => i18n.changeLanguage("en"));
});

const batch = {
  id: "b1",
  entity_id: "e1",
  entity_name: "Synthetic Trading LLC",
  name: "October invoices",
  original_filename: "october.zip",
  raw_sha256: "a".repeat(64),
  file_count: 12,
  duplicate_count: 1,
  failed_count: 2,
  is_demo: true,
  created_at: "2026-10-01T08:00:00Z",
};

describe("e-invoices page", () => {
  it("lists batches with their counts and says nothing is sent to a platform", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/entities")) return jsonResponse(200, []);
      if (url.endsWith("/einvoice-batches")) return jsonResponse(200, [batch]);
      if (url.endsWith("/einvoice-monitors")) return jsonResponse(200, []);
    });
    renderWithProviders(<EInvoicesPage />);
    const row = (await screen.findByRole("button", { name: "October invoices" })).closest("tr")!;
    expect(within(row).getByText("Synthetic")).toBeInTheDocument();
    expect(within(row).getByText("Synthetic Trading LLC")).toBeInTheDocument();
    expect(within(row).getByText("12")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/Nothing on this page is sent to any e-invoicing platform/)).toBeInTheDocument();
    expect(await screen.findByText("No monitors yet. Create one to sample new e-invoices on a schedule.")).toBeInTheDocument();
  });

  it("shows an empty state and hides upload from viewers", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/entities")) return jsonResponse(200, []);
      if (url.endsWith("/einvoice-batches")) return jsonResponse(200, []);
      if (url.endsWith("/einvoice-monitors")) return jsonResponse(200, []);
    });
    renderWithProviders(<EInvoicesPage />);
    expect(await screen.findByText("No e-invoices yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload e-invoices" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New monitor" })).not.toBeInTheDocument();
  });
});

const obligation = (id: string, label: string, verified: boolean) => ({
  id,
  entity_id: "e1",
  entity_name: "Synthetic Trading LLC",
  tax_period_id: "tp1",
  obligation_key: `${id}-key`,
  label,
  tax_type: "vat",
  period_start: "2026-07-01",
  period_end: "2026-09-30",
  due_date: "2026-10-28",
  formula: `period_end + 28 days (${id})`,
  rule_key: "synthetic.vat.obligations",
  rule_pack_version_id: "rpv1",
  rule_verified: verified,
  rule_snapshot: {},
  task: null,
});

describe("tax calendar", () => {
  it("flags obligations computed from unverified rules and shows the formula", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("viewer"));
      if (url.endsWith("/entities")) return jsonResponse(200, []);
      if (url.endsWith("/tax-obligations"))
        return jsonResponse(200, [obligation("o1", "VAT return Q3", false), obligation("o2", "VAT payment Q3", true)]);
    });
    renderWithProviders(<TaxCalendarPage />);
    const draftRow = (await screen.findByText("VAT return Q3")).closest("tr")!;
    expect(within(draftRow).getByText("Unverified")).toBeInTheDocument();
    expect(within(draftRow).getByText("period_end + 28 days (o1)")).toBeInTheDocument();
    const verifiedRow = screen.getByText("VAT payment Q3").closest("tr")!;
    expect(within(verifiedRow).queryByText("Unverified")).not.toBeInTheDocument();
    expect(within(verifiedRow).getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText(/Do not rely on a date computed from a draft \(unverified\) rule/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate calendar" })).not.toBeInTheDocument();
  });
});

describe("general tasks", () => {
  it("requires a note to close a task", async () => {
    const user = userEvent.setup();
    const task = {
      id: "t1",
      source_kind: "tax_obligation",
      source_id: "o1",
      entity_id: "e1",
      entity_name: "Synthetic Trading LLC",
      title: "File VAT return Q3",
      description: "",
      owner_id: "u1",
      owner_name: "Demo Admin",
      due_date: "2026-10-28",
      is_overdue: false,
      status: "open",
      completion_note: "",
      completed_at: null,
      created_at: "2026-10-01T08:00:00Z",
    };
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
      if (url.endsWith("/entities")) return jsonResponse(200, []);
      if (url.endsWith("/members")) return jsonResponse(200, []);
      if (url.endsWith("/tasks/t1") && init?.method === "PATCH") return jsonResponse(200, { ...task, status: "done" });
      if (url.includes("/tasks?")) return jsonResponse(200, [task]);
    });
    renderWithProviders(<TasksPage />, { route: "/tasks?view=general" });
    await user.click(await screen.findByRole("button", { name: "Update File VAT return Q3" }));
    const dialog = await screen.findByRole("dialog");
    await user.selectOptions(within(dialog).getByLabelText("Status"), "done");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Add a note to close this task, for example the filing reference.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).endsWith("/tasks/t1") && (i as RequestInit)?.method === "PATCH")).toBe(false);

    await user.type(within(dialog).getByLabelText("Closing note"), "Filing ref SYN-001");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/tasks/t1") && (i as RequestInit)?.method === "PATCH");
      expect(call && JSON.parse(String((call[1] as RequestInit).body))).toEqual({ status: "done", note: "Filing ref SYN-001" });
    });
  });
});

describe("e-invoice evidence", () => {
  it("shows the XPath left-to-right and links to the stored XML", () => {
    const ev: XmlEvidence = {
      type: "xml",
      einvoice_file_id: "f1",
      filename: "INV-001.xml",
      sha256: "b".repeat(64),
      invoice_number: "INV-001",
      xpath: "/Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount",
      line: 42,
      value: "105.00",
      label: "Payable amount does not equal the line totals plus tax",
      detail: { expected: "110.0000", difference: "-5.0000" },
    };
    render(<EvidenceItem evidence={ev} />);
    const xpath = screen.getByText("/Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount");
    expect(xpath).toHaveAttribute("dir", "ltr");
    expect(screen.getByRole("link", { name: "Download XML" })).toHaveAttribute("href", "/api/einvoice-files/f1/download");
    expect(screen.getByText("Line 42")).toBeInTheDocument();
    expect(screen.getByText("-5.0000")).toBeInTheDocument();
  });
});

describe("new review with an entity and e-invoices", () => {
  it("sends the entity, tax period and chosen batches", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
      if (url.includes("/documents?")) return jsonResponse(200, { items: [], total: 0, page: 1, page_size: 100 });
      if (url.endsWith("/checklists"))
        return jsonResponse(200, [
          { id: "c1", name: "E-invoice checks", description: "", kind: "synthetic_demo", created_at: "", versions: [{ id: "cv1", version_number: 1, state: "published" }] },
        ]);
      if (url.endsWith("/datasets")) return jsonResponse(200, []);
      if (url.endsWith("/rule-packs")) return jsonResponse(200, []);
      if (url.endsWith("/entities")) return jsonResponse(200, [{ id: "e1", name: "Synthetic Trading LLC" }]);
      if (url.endsWith("/entities/e1/tax-periods"))
        return jsonResponse(200, [{ id: "tp1", entity_id: "e1", tax_type: "vat", frequency: "quarterly", period_start: "2026-07-01", period_end: "2026-09-30", status: "open", created_at: "" }]);
      if (url.includes("/einvoice-batches?entity_id=e1")) return jsonResponse(200, [batch]);
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
    await user.type(await screen.findByLabelText("Review title"), "Q3 e-invoices");
    await user.selectOptions(screen.getByLabelText("Legal entity"), "e1");
    await user.click(await screen.findByRole("checkbox", { name: /October invoices/ }));
    await user.selectOptions(await screen.findByLabelText("Tax period"), "tp1");
    await user.click(screen.getByRole("button", { name: "Create and run checks" }));
    expect(await screen.findByText("review page")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/reviews") && (i as RequestInit)?.method === "POST")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({
      title: "Q3 e-invoices",
      checklist_version_id: "cv1",
      document_version_id: null,
      dataset_version_ids: [],
      rule_pack_version_id: null,
      as_of_date: null,
      entity_id: "e1",
      tax_period_id: "tp1",
      einvoice_batch_ids: ["b1"],
    });
  });
});
