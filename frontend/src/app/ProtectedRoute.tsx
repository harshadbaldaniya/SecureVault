import type { ReactNode } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";

import { PageLoader } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import type { Permission } from "@/types/api";

export function Forbidden() {
  return (
    <div className="mx-auto max-w-md py-16 text-center" role="alert">
      <p className="text-5xl font-bold text-slate-300">403</p>
      <h1 className="mt-4 text-xl font-semibold">You do not have access to this page</h1>
      <p className="mt-2 text-sm text-slate-500">Your role does not include this area. Ask an administrator if you think this is a mistake.</p>
      <Link to="/" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">
        Back to home
      </Link>
    </div>
  );
}

interface Props {
  children: ReactNode;
  /** Hides the page for users without this permission. The API enforces it independently. */
  permission?: Permission;
}

export function ProtectedRoute({ children, permission }: Props) {
  const { user, loading, can } = useAuth();
  const location = useLocation();

  if (loading) return <PageLoader label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (user.mfa_enrollment_required && location.pathname !== "/security") return <Navigate to="/security" replace />;
  if (permission && !can(permission)) return <Forbidden />;
  return <>{children}</>;
}
