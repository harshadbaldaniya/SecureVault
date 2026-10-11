import { lazy, type ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { LinkButton } from "@/components/ui";
import { ArrowLeftIcon } from "@/components/icons";
import { AcceptInvitePage, ForgotPasswordPage, ResetPasswordPage } from "@/features/authentication/PasswordPages";
import { LoginPage } from "@/features/authentication/LoginPage";
import { HomePage } from "@/features/dashboard/HomePage";
import { GetStartedPage } from "@/features/landing/GetStartedPage";
import { LandingPage } from "@/features/landing/LandingPage";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";

import { AppLayout } from "./AppLayout";
import { ProtectedRoute } from "./ProtectedRoute";
import { ScrollManager } from "./ScrollManager";

/** Each signed-in screen is its own chunk, fetched on first visit (AppLayout shows a loader meanwhile). */
function page<M>(load: () => Promise<M>, name: keyof M) {
  return lazy(async () => ({ default: (await load())[name] as ComponentType }));
}

const AccessRequestsPage = page(() => import("@/features/access-requests/AccessRequestsPage"), "AccessRequestsPage");
const AlertsPage = page(() => import("@/features/devices/AlertsPage"), "AlertsPage");
const AuditPage = page(() => import("@/features/audit/AuditPage"), "AuditPage");
const CredentialsPage = page(() => import("@/features/vault/CredentialsPage"), "CredentialsPage");
const DepartmentsPage = page(() => import("@/features/departments/DepartmentsPage"), "DepartmentsPage");
const DevicesPage = page(() => import("@/features/devices/DevicesPage"), "DevicesPage");
const EmployeesPage = page(() => import("@/features/employees/EmployeesPage"), "EmployeesPage");
const ImportsPage = page(() => import("@/features/employees/ImportsPage"), "ImportsPage");
const LockdownPage = page(() => import("@/features/lockdown/LockdownPage"), "LockdownPage");
const NotesPage = page(() => import("@/features/vault/NotesPage"), "NotesPage");
const PolicyPage = page(() => import("@/features/policies/PolicyPage"), "PolicyPage");
const ReportsPage = page(() => import("@/features/reports/ReportsPage"), "ReportsPage");
const SecurityPage = page(() => import("@/features/authentication/SecurityPage"), "SecurityPage");
const ServicesPage = page(() => import("@/features/policies/ServicesPage"), "ServicesPage");
const SharingPage = page(() => import("@/features/sharing/SharingPage"), "SharingPage");

function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="text-5xl font-bold text-slate-500">404</p>
      <h1 className="mt-4 text-xl font-semibold">Page not found</h1>
      <LinkButton to="/" className="mt-6">
        <ArrowLeftIcon />
        Back to home
      </LinkButton>
    </div>
  );
}

export function AppRoutes() {
  return (
    <>
      <ScrollManager />
      <Routes>
        <Route path="/get-started" element={<GetStartedPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/accept-invite" element={<AcceptInvitePage />} />

        <Route
          element={
            <ProtectedRoute landing={<LandingPage />}>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<HomePage />} />
          <Route path="security" element={<SecurityPage />} />
          <Route path="vault" element={<CredentialsPage />} />
          <Route path="vault/notes" element={<NotesPage />} />
          <Route path="sharing" element={<SharingPage />} />
          <Route path="access-requests" element={<AccessRequestsPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route
            path="alerts"
            element={
              <ProtectedRoute permission="alerts.manage">
                <AlertsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="lockdown"
            element={
              <ProtectedRoute permission="lockdown.manage">
                <LockdownPage />
              </ProtectedRoute>
            }
          />
          <Route path="departments" element={<DepartmentsPage />} />
          <Route path="services" element={<ServicesPage />} />
          <Route path="policy" element={<PolicyPage />} />
          <Route
            path="employees"
            element={
              <ProtectedRoute permission="users.view">
                <EmployeesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="employees/import"
            element={
              <ProtectedRoute permission="invitations.manage">
                <ImportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="reports"
            element={
              <ProtectedRoute permission="reports.view">
                <ReportsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="audit"
            element={
              <ProtectedRoute permission="audit.view">
                <AuditPage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>

        <Route path="/index.html" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
