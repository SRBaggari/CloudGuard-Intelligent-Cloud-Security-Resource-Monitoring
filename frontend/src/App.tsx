import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import AppLayout from "@/components/layout/AppLayout";
import { AdminRoute, ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { Spinner, ToastProvider } from "@/components/ui";
import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";
import LoginPage from "@/pages/Login";
import RegisterPage from "@/pages/Register";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Monitoring = lazy(() => import("@/pages/Monitoring"));
const Topology = lazy(() => import("@/pages/Topology"));
const Containers = lazy(() => import("@/pages/Containers"));
const VirtualMachines = lazy(() => import("@/pages/VirtualMachines"));
const Alerts = lazy(() => import("@/pages/Alerts"));
const Security = lazy(() => import("@/pages/Security"));
const Integrity = lazy(() => import("@/pages/Integrity"));
const Analytics = lazy(() => import("@/pages/Analytics"));
const Reports = lazy(() => import("@/pages/Reports"));
const SettingsPage = lazy(() => import("@/pages/Settings"));
const Activity = lazy(() => import("@/pages/Activity"));
const Profile = lazy(() => import("@/pages/Profile"));
const Notifications = lazy(() => import("@/pages/Notifications"));
const Incidents = lazy(() => import("@/pages/Incidents"));
const IncidentDetail = lazy(() => import("@/pages/IncidentDetail"));
const NotFound = lazy(() => import("@/pages/NotFound"));

export function AppRoutes() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="monitoring" element={<Monitoring />} />
            <Route path="topology" element={<Topology />} />
            <Route path="containers" element={<Containers />} />
            <Route path="vms" element={<VirtualMachines />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="security" element={<Security />} />
            <Route path="analytics" element={<Analytics />} />
            <Route path="reports" element={<Reports />} />
            <Route path="profile" element={<Profile />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="incidents" element={<Incidents />} />
            <Route path="incidents/:id" element={<IncidentDetail />} />
            <Route element={<AdminRoute />}>
              <Route path="integrity" element={<Integrity />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="activity" element={<Activity />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
