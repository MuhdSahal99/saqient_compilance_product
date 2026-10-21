import { lazy, Suspense, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { useTranslation } from "react-i18next";
import { AuthProvider, useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { AppLayout } from "@/components/layout";
import { LoadingState } from "@/components/common";
import { LoginPage } from "@/pages/LoginPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { DocumentDetailPage } from "@/pages/DocumentDetailPage";
import { ChecklistsPage, ChecklistVersionPage } from "@/pages/ChecklistsPage";
import { ReviewsPage } from "@/pages/ReviewsPage";
import { ReviewDetailPage } from "@/pages/ReviewDetailPage";
import { FindingsPage } from "@/pages/FindingsPage";
import { TasksPage } from "@/pages/TasksPage";
import { ReportsPage } from "@/pages/ReportsPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { EntitiesPage } from "@/pages/EntitiesPage";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { DatasetDetailPage } from "@/pages/DatasetDetailPage";
import { RulePacksPage, RulePackVersionPage } from "@/pages/RulePacksPage";
import { EInvoicesPage } from "@/pages/EInvoicesPage";
import { TaxCalendarPage } from "@/pages/TaxCalendarPage";
import { WorkpapersPage } from "@/pages/WorkpapersPage";
import { WorkpaperDetailPage } from "@/pages/WorkpaperDetailPage";
import { EngagementsPage } from "@/pages/EngagementsPage";
import { PortalPage } from "@/pages/PortalPage";
import { AcceptInvitePage, ForgotPasswordPage, ResetPasswordPage } from "@/pages/PublicAuthPages";

/** The engagement workspace is large; load it on first visit to keep the main bundle small. */
const EngagementDetailPage = lazy(() => import("@/pages/EngagementDetailPage").then((m) => ({ default: m.EngagementDetailPage })));

/** Phase E assurance screens, each loaded on first visit. */
const ReconciliationsPage = lazy(() => import("@/pages/ReconciliationsPage").then((m) => ({ default: m.ReconciliationsPage })));
const BankRecDetailPage = lazy(() => import("@/pages/ReconciliationDetailPages").then((m) => ({ default: m.BankRecDetailPage })));
const AccountRecDetailPage = lazy(() => import("@/pages/ReconciliationDetailPages").then((m) => ({ default: m.AccountRecDetailPage })));
const IntercompanyDetailPage = lazy(() => import("@/pages/ReconciliationDetailPages").then((m) => ({ default: m.IntercompanyDetailPage })));
const ClosePage = lazy(() => import("@/pages/ClosePage").then((m) => ({ default: m.ClosePage })));
const ClosePeriodDetailPage = lazy(() => import("@/pages/ClosePage").then((m) => ({ default: m.ClosePeriodDetailPage })));
const FluxDetailPage = lazy(() => import("@/pages/ClosePage").then((m) => ({ default: m.FluxDetailPage })));
const ControlsPage = lazy(() => import("@/pages/ControlsPage").then((m) => ({ default: m.ControlsPage })));
const ProcessDetailPage = lazy(() => import("@/pages/ControlDetailPages").then((m) => ({ default: m.ProcessDetailPage })));
const CertificationDetailPage = lazy(() => import("@/pages/ControlDetailPages").then((m) => ({ default: m.CertificationDetailPage })));
const ConnectorsPage = lazy(() => import("@/pages/ConnectorsPage").then((m) => ({ default: m.ConnectorsPage })));

/** Phase F sector content packs, loaded on first visit. */
const ContentPacksPage = lazy(() => import("@/pages/ContentPacksPage").then((m) => ({ default: m.ContentPacksPage })));
const ContentPackDetailPage = lazy(() => import("@/pages/ContentPacksPage").then((m) => ({ default: m.ContentPackDetailPage })));

/** Phase G AI assistant (multi-agent tasks), loaded on first visit. */
const AIAssistantPage = lazy(() => import("@/pages/AIAssistantPage").then((m) => ({ default: m.AIAssistantPage })));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<LoadingState />}>{children}</Suspense>;
}

function RequireAuth() {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingState />;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function Root() {
  const { i18n } = useTranslation();
  return (
    <AuthProvider>
      <Outlet />
      <Toaster position={i18n.dir() === "rtl" ? "bottom-left" : "bottom-right"} richColors closeButton />
    </AuthProvider>
  );
}

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export const routes = [
  {
    element: <Root />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
      { path: "/reset-password", element: <ResetPasswordPage /> },
      { path: "/accept-invite", element: <AcceptInvitePage /> },
      {
        element: <RequireAuth />,
        children: [
          {
            element: <AppLayout />,
            children: [
              { path: "/", element: <OverviewPage /> },
              { path: "/reviews", element: <ReviewsPage /> },
              { path: "/reviews/:reviewId", element: <ReviewDetailPage /> },
              { path: "/documents", element: <DocumentsPage /> },
              { path: "/documents/:documentId", element: <DocumentDetailPage /> },
              { path: "/checklists", element: <ChecklistsPage /> },
              { path: "/checklists/versions/:versionId", element: <ChecklistVersionPage /> },
              { path: "/entities", element: <EntitiesPage /> },
              { path: "/datasets", element: <DatasetsPage /> },
              { path: "/datasets/:datasetId", element: <DatasetDetailPage /> },
              { path: "/einvoices", element: <EInvoicesPage /> },
              { path: "/workpapers", element: <WorkpapersPage /> },
              { path: "/workpapers/:workpaperId", element: <WorkpaperDetailPage /> },
              { path: "/rule-packs", element: <RulePacksPage /> },
              { path: "/rule-packs/versions/:versionId", element: <RulePackVersionPage /> },
              { path: "/content-packs", element: <Lazy><ContentPacksPage /></Lazy> },
              { path: "/content-packs/:packId", element: <Lazy><ContentPackDetailPage /></Lazy> },
              { path: "/findings", element: <FindingsPage /> },
              { path: "/tasks", element: <TasksPage /> },
              { path: "/tax-calendar", element: <TaxCalendarPage /> },
              { path: "/engagements", element: <EngagementsPage /> },
              {
                path: "/engagements/:engagementId",
                element: (
                  <Suspense fallback={<LoadingState />}>
                    <EngagementDetailPage />
                  </Suspense>
                ),
              },
              { path: "/reconciliations", element: <Lazy><ReconciliationsPage /></Lazy> },
              { path: "/reconciliations/bank/:recId", element: <Lazy><BankRecDetailPage /></Lazy> },
              { path: "/reconciliations/account/:recId", element: <Lazy><AccountRecDetailPage /></Lazy> },
              { path: "/reconciliations/intercompany/:recId", element: <Lazy><IntercompanyDetailPage /></Lazy> },
              { path: "/close", element: <Lazy><ClosePage /></Lazy> },
              { path: "/close/periods/:periodId", element: <Lazy><ClosePeriodDetailPage /></Lazy> },
              { path: "/close/flux/:fluxId", element: <Lazy><FluxDetailPage /></Lazy> },
              { path: "/controls", element: <Lazy><ControlsPage /></Lazy> },
              { path: "/controls/processes/:processId", element: <Lazy><ProcessDetailPage /></Lazy> },
              { path: "/controls/certifications/:certId", element: <Lazy><CertificationDetailPage /></Lazy> },
              { path: "/connectors", element: <Lazy><ConnectorsPage /></Lazy> },
              { path: "/portal", element: <PortalPage /> },
              { path: "/reports", element: <ReportsPage /> },
              { path: "/ai", element: <Lazy><AIAssistantPage /></Lazy> },
              { path: "/activity", element: <ActivityPage /> },
              { path: "/settings", element: <SettingsPage /> },
              { path: "*", element: <NotFoundPage /> },
            ],
          },
        ],
      },
    ],
  },
];

const queryClient = makeQueryClient();
const router = createBrowserRouter(routes);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
