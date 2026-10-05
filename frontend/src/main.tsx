import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { Shell } from "./components/Shell";
import { RequestsPage } from "./pages/Requests";
import { RequestPage } from "./pages/Request";
import { ImportsPage } from "./pages/Imports";
import { BatchPage } from "./pages/Batch";
import { DashboardPage } from "./pages/Dashboard";
import { InboxPage } from "./pages/Inbox";
import { ActivityPage } from "./pages/Activity";
import { HubPage } from "./pages/Hub";
import { ErrorBoundary, report } from "./components/ErrorBoundary";

window.addEventListener("error", (e) => report(e.error ?? e.message));
window.addEventListener("unhandledrejection", (e) => report(e.reason));

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, e: any) => n < 2 && e?.status !== 401 && e?.status !== 404,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={qc}>
        <BrowserRouter>
          <Routes>
            <Route path="/u/:token" element={<HubPage />} />
            <Route element={<Shell />}>
              <Route path="/" element={<RequestsPage />} />
              <Route path="/requests/:id" element={<RequestPage />} />
              <Route path="/imports" element={<ImportsPage />} />
              <Route path="/imports/:id" element={<BatchPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/activity" element={<ActivityPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
