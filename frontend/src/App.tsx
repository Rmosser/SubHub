import { lazy, Suspense } from "react";
import { Box, Spinner } from "@cloudscape-design/components";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@cloudscape-design/global-styles/index.css";
import { LocaleProvider } from "@/contexts/LocaleContext";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { ScenarioProvider } from "@/contexts/ScenarioContext";
import { SplitPanelProvider } from "@/contexts/SplitPanelContext";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AppShell } from "@/layouts/AppShell";
import { SetupGate } from "@/components/SetupGate";

const CatalogPage = lazy(() => import("@/pages/Catalog").then((module) => ({ default: module.CatalogPage })));
const ContractsPage = lazy(() => import("@/pages/Contracts").then((module) => ({ default: module.ContractsPage })));
const ProfilePage = lazy(() => import("@/pages/Profile/readmap/ReadMapPage").then((module) => ({ default: module.ReadMapPage })));
const LLMWorkflowsPage = lazy(() => import("@/pages/LLMWorkflows").then((module) => ({ default: module.LLMWorkflowsPage })));
const PoolsPage = lazy(() => import("@/pages/Pools").then((module) => ({ default: module.PoolsPage })));
const SourcesPage = lazy(() => import("@/pages/Sources").then((module) => ({ default: module.SourcesPage })));
const DevicesPage = lazy(() => import("@/pages/Devices").then((module) => ({ default: module.DevicesPage })));
const ReviewPage = lazy(() => import("@/pages/Review").then((module) => ({ default: module.ReviewPage })));
const AdvancedPage = lazy(() => import("@/pages/Advanced").then((module) => ({ default: module.AdvancedPage })));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function RouteFallback() {
  return (
    <Box padding="xl" textAlign="center" color="text-body-secondary">
      <Spinner size="large" />
    </Box>
  );
}

function LazyRoute({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<RouteFallback />}>{children}</Suspense>;
}

export function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <LocaleProvider>
          <NotificationProvider>
            <SetupGate>
            <ScenarioProvider>
              <BrowserRouter basename="/manage">
                <SplitPanelProvider>
                <Routes>
                  <Route path="/" element={<AppShell />}>
                    <Route index element={<Navigate to="sources" replace />} />
                    <Route path="catalog" element={<LazyRoute><CatalogPage /></LazyRoute>} />
                    <Route path="contracts" element={<LazyRoute><ContractsPage /></LazyRoute>} />
                    <Route path="profile" element={<LazyRoute><ProfilePage /></LazyRoute>} />
                    <Route path="llm" element={<LazyRoute><LLMWorkflowsPage /></LazyRoute>} />
                    <Route path="pools" element={<LazyRoute><PoolsPage /></LazyRoute>} />
                    <Route path="sources" element={<LazyRoute><SourcesPage /></LazyRoute>} />
                    <Route path="devices" element={<LazyRoute><DevicesPage /></LazyRoute>} />
                    <Route path="review" element={<LazyRoute><ReviewPage /></LazyRoute>} />
                    <Route path="advanced" element={<LazyRoute><AdvancedPage /></LazyRoute>} />
                  </Route>
                  <Route path="*" element={<Navigate to="/sources" replace />} />
                </Routes>
                </SplitPanelProvider>
              </BrowserRouter>
            </ScenarioProvider>
            </SetupGate>
          </NotificationProvider>
        </LocaleProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
