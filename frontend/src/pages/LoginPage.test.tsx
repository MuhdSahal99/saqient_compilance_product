import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { jsonResponse, renderWithProviders } from "@/test/utils";
import { Route, Routes } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { LoginPage } from "./LoginPage";

function Probe() {
  const { me } = useAuth();
  return <p>{me ? `signed in as ${me.user.email}` : "signed out"}</p>;
}

describe("LoginPage", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return Promise.resolve(jsonResponse(401, { detail: "Not signed in." }));
      if (url.endsWith("/auth/login")) return Promise.resolve(jsonResponse(401, { detail: "Email or password is incorrect." }));
      return Promise.resolve(jsonResponse(404, {}));
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("validates fields before calling the API", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />, { route: "/login" });
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/login"))).toBe(false);
  });

  it("keeps the signed-in user after a successful login", async () => {
    const user = userEvent.setup();
    const org = { id: "o1", name: "Alpha Synthetic Audit Team", slug: "alpha-synthetic", is_demo: true };
    const me = {
      user: { id: "u1", email: "analyst@alpha.example", full_name: "Demo Analyst", preferred_locale: "en", is_demo: true },
      org,
      role: "analyst",
      memberships: [{ org, role: "analyst" }],
      csrf_token: "c",
      demo_mode: true,
      ai_enabled: false,
    };
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) return Promise.resolve(jsonResponse(200, me));
      return Promise.resolve(jsonResponse(401, { detail: "Not signed in." }));
    });
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Probe />} />
      </Routes>,
      { route: "/login" },
    );
    await user.type(await screen.findByLabelText("Email"), "analyst@alpha.example");
    await user.type(screen.getByLabelText("Password"), "Demo-Password-2026!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    // Regression: clearing the whole query cache used to detach the "me" observer and bounce back to /login.
    expect(await screen.findByText("signed in as analyst@alpha.example")).toBeInTheDocument();
  });

  it("shows the server error without echoing the password", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />, { route: "/login" });
    await user.type(await screen.findByLabelText("Email"), "analyst@alpha.example");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Email or password is incorrect.");
    expect(alert).not.toHaveTextContent("wrong-password");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/login"))).toBe(true));
  });
});
