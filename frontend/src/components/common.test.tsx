import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import i18n from "@/i18n";
import type { Evidence } from "@/lib/types";
import { ConfirmDialog, FindingStatusBadge, SeverityBadge, SyntheticBadge } from "./common";
import { EvidenceQuote, evidenceLocation } from "./evidence";

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("status badges", () => {
  it("labels synthetic content with the disclaimer", () => {
    render(<SyntheticBadge />);
    const badge = screen.getByText("Synthetic");
    expect(badge.closest("[title]")).toHaveAttribute("title", "Synthetic demonstration content — not legal guidance.");
  });

  it("renders severity and finding status in the active language", async () => {
    render(
      <>
        <SeverityBadge severity="high" />
        <FindingStatusBadge status="ready_for_rereview" />
      </>,
    );
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.getByText("Ready for re-review")).toBeInTheDocument();
    await act(() => i18n.changeLanguage("ar"));
    expect(await screen.findByText("عالية")).toBeInTheDocument();
  });
});

describe("evidence", () => {
  const base: Evidence = {
    block_id: "b1",
    ref: "p2.para3",
    page_number: 2,
    paragraph_number: 3,
    quote: "reviewed annually",
    context: "Access is reviewed annually by the owner.",
    highlight_start: 10,
    highlight_end: 27,
  };

  it("uses page numbers for PDFs and paragraph numbers otherwise", () => {
    const t = i18n.getFixedT("en");
    expect(evidenceLocation(base, t)).toBe("Page 2");
    expect(evidenceLocation({ ...base, page_number: null }, t)).toBe("Paragraph 3");
  });

  it("highlights only the matched span of stored text", async () => {
    const user = userEvent.setup();
    const onLocate = vi.fn();
    render(<EvidenceQuote evidence={base} onLocate={onLocate} />);
    const mark = screen.getByText("reviewed annually");
    expect(mark.tagName).toBe("MARK");
    await user.click(screen.getByRole("button", { name: "Page 2" }));
    expect(onLocate).toHaveBeenCalledWith(base);
  });
});

describe("ConfirmDialog", () => {
  it("calls onConfirm only when confirmed", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Delete this document?"
        description="Gone."
        confirmLabel="Delete"
        destructive
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onConfirm).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
