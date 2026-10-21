import type { ReactNode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import i18n from "@/i18n";
import { AuthProvider } from "@/lib/auth";
import { jsonResponse } from "@/test/utils";
import type { Role } from "@/lib/types";
import type { AIAgent, AITask } from "@/lib/ai-agents";
import { AIAssistantPage } from "./AIAssistantPage";
import { AIAssist } from "@/components/ai-task";

const org = { id: "o1", name: "Alpha Synthetic Audit Team", slug: "alpha-synthetic", is_demo: true };
function me(role: Role) {
  return {
    user: { id: "u1", email: "user@alpha.example", full_name: "Demo User", preferred_locale: "en", is_demo: true },
    org,
    role,
    memberships: [{ org, role }],
    csrf_token: "csrf",
    demo_mode: true,
    ai_enabled: true,
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

function renderAt(element: ReactNode) {
  const router = createMemoryRouter([{ path: "/", element: <AuthProvider>{element}</AuthProvider> }], { initialEntries: ["/"] });
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

const agents: AIAgent[] = [
  { name: "pack_qa", tier: "reasoning", model: "gemini-3.8-flash" },
  { name: "critic", tier: "fast", model: "gemini-3.5-flash-lite" },
];

const job = {
  id: "j1",
  kind: "ai_agent",
  status: "completed",
  attempts: 1,
  max_attempts: 2,
  progress: 100,
  cancel_requested: false,
  error: null,
  created_at: "2026-10-21T10:00:00Z",
  started_at: null,
  finished_at: null,
} as const;

function task(over: Partial<AITask> = {}): AITask {
  return {
    id: "t1",
    kind: "pack_qa",
    subject_type: "organization",
    subject_id: "o1",
    question: "Which deadline applies?",
    language: "en",
    status: "ready",
    provider: "gemini",
    is_mock: false,
    prompt_version: "agents-v1",
    output: {
      answer: "Synthetic answer from the verified rule.",
      insufficient: false,
      sources: [{ type: "rule", id: "r1", key: "synthetic.due_days", title: "Synthetic due days", label: "R1" }],
      checked: true,
    },
    warnings: [],
    error: "",
    requested_by_name: "Demo User",
    decided_by_name: null,
    decided_at: null,
    decision_note: "",
    created_at: "2026-10-21T10:00:00Z",
    finished_at: "2026-10-21T10:00:05Z",
    steps: [
      { ordinal: 0, agent: "router", tier: "fast", provider: "gemini", model: "gemini-3.5-flash-lite", model_version: "gemini-3.5-flash-lite-001", status: "ok", duration_ms: 300, input_tokens: 50, output_tokens: 10, note: "" },
      { ordinal: 1, agent: "pack_qa", tier: "reasoning", provider: "gemini", model: "gemini-3.8-flash", model_version: "gemini-3.8-flash-001", status: "ok", duration_ms: 900, input_tokens: 400, output_tokens: 80, note: "" },
    ],
    job: { ...job },
    ...over,
  };
}

test("the assistant explains how to turn AI on when no agents are offered", async () => {
  mockFetch((url) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
    if (url.endsWith("/ai/agents")) return jsonResponse(200, []);
    return undefined;
  });
  renderAt(<AIAssistantPage />);
  expect(await screen.findByText("AI is not turned on")).toBeInTheDocument();
});

test("asks a question and shows the answer, sources, models and the draft label", async () => {
  let posted: unknown;
  const fetchMock = mockFetch((url, init) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
    if (url.endsWith("/ai/agents")) return jsonResponse(200, agents);
    if (url.includes("/ai/tasks?")) return jsonResponse(200, posted ? [task()] : []);
    if (url.endsWith("/ai/tasks") && init?.method === "POST") {
      posted = JSON.parse(String(init.body));
      return jsonResponse(201, task());
    }
    return undefined;
  });
  renderAt(<AIAssistantPage />);
  expect(await screen.findByText("gemini-3.8-flash")).toBeInTheDocument();
  expect(screen.getByText("No AI tasks yet")).toBeInTheDocument();

  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Ask about your verified rules and checklists"), "Which deadline applies?");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  await waitFor(() => expect(posted).toEqual({ kind: "pack_qa", question: "Which deadline applies?", language: "en" }));
  expect(await screen.findByText("Synthetic answer from the verified rule.")).toBeInTheDocument();
  expect(screen.getByText("AI draft — needs human review")).toBeInTheDocument();
  expect(screen.getByText("Synthetic due days")).toBeInTheDocument();
  expect(screen.getByText(/2 agent steps/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalled();
});

test("reviewers can use drafted letter wording; analysts cannot decide", async () => {
  const letter = task({
    kind: "letter_draft",
    subject_type: "letter_point",
    subject_id: "p1",
    output: { implication: "Synthetic implication.", recommendation: "Synthetic recommendation.", checked: false },
    warnings: ["The checking agent could not match part of this draft to the evidence."],
  });
  let decided = "";
  mockFetch((url, init) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me("reviewer"));
    if (url.endsWith("/ai/agents")) return jsonResponse(200, agents);
    if (url.includes("/ai/tasks?")) return jsonResponse(200, [decided ? { ...letter, status: "accepted" } : letter]);
    if (url.endsWith("/ai/tasks/t1/accept") && init?.method === "POST") {
      decided = String(init.body);
      return jsonResponse(200, { ...letter, status: "accepted" });
    }
    return undefined;
  });
  renderAt(<AIAssist kind="letter_draft" subjectId="p1" />);
  expect(await screen.findByText("Synthetic recommendation.")).toBeInTheDocument();
  expect(screen.getByText("Not confirmed by the checking agent")).toBeInTheDocument();
  expect(screen.getByText(/could not match part of this draft/)).toBeInTheDocument();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Note (optional)"), "Edited later");
  await user.click(screen.getByRole("button", { name: "Use this wording" }));
  await waitFor(() => expect(JSON.parse(decided)).toEqual({ note: "Edited later" }));
});

test("analysts see the draft but no decision buttons", async () => {
  mockFetch((url) => {
    if (url.endsWith("/auth/me")) return jsonResponse(200, me("analyst"));
    if (url.endsWith("/ai/agents")) return jsonResponse(200, agents);
    if (url.includes("/ai/tasks?")) return jsonResponse(200, [task({ kind: "finding_explain", output: { explanation_en: "Plain words.", explanation_ar: "كلمات واضحة.", checked: true } })]);
    return undefined;
  });
  renderAt(<AIAssist kind="finding_explain" subjectId="f1" />);
  expect(await screen.findByText("Plain words.")).toBeInTheDocument();
  expect(screen.getByText("كلمات واضحة.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
});
