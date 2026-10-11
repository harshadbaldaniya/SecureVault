import { Link, Navigate, Route, Routes } from "react-router-dom";

import { AccessRequestsPage } from "@/features/access-requests/AccessRequestsPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { SharingPage } from "@/features/sharing/SharingPage";
import { AcceptInvitePage, ForgotPasswordPage, ResetPasswordPage } from "@/features/authentication/PasswordPages";
import { LoginPage } from "@/features/authentication/LoginPage";
import { SecurityPage } from "@/features/authentication/SecurityPage";
import { HomePage } from "@/features/dashboard/HomePage";
import { DepartmentsPage } from "@/features/departments/DepartmentsPage";
import { EmployeesPage } from "@/features/employees/EmployeesPage";
import { PolicyPage } from "@/features/policies/PolicyPage";
import { ServicesPage } from "@/features/policies/ServicesPage";
import { CredentialsPage } from "@/features/vault/CredentialsPage";
import { NotesPage } from "@/features/vault/NotesPage";

import { AppLayout } from "./AppLayout";
import { ProtectedRoute } from "./ProtectedRoute";

function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="text-5xl font-bold text-slate-300">404</p>
      <h1 className="mt-4 text-xl font-semibold">Page not found</h1>
      <Link to="/" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">
        Back to home
      </Link>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />

      <Route
        element={
          <ProtectedRoute>
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
  );
}
