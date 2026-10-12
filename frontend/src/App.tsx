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
              { path: "/findings", element: <FindingsPage /> },
              { path: "/tasks", element: <TasksPage /> },
              { path: "/reports", element: <ReportsPage /> },
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
