import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { ArrowLeftIcon } from "@/components/icons";
import { PageLoader, LinkButton } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import type { Permission } from "@/types/api";

export function Forbidden() {
  return (
    <div className="mx-auto max-w-md py-16 text-center" role="alert">
      <p className="text-5xl font-bold text-slate-300">403</p>
      <h1 className="mt-4 text-xl font-semibold">You do not have access to this page</h1>
      <p className="mt-2 text-sm text-slate-500">Your role does not include this area. Ask an administrator if you think this is a mistake.</p>
      <LinkButton to="/" className="mt-6">
        <ArrowLeftIcon />
        Back to home
      </LinkButton>
    </div>
  );
}

interface Props {
  children: ReactNode;
  /** Shown instead of redirecting when a visitor who was never signed in opens the site root. */
  landing?: ReactNode;
  /** Hides the page for users without this permission. The API enforces it independently. */
  permission?: Permission;
}

export function ProtectedRoute({ children, permission, landing }: Props) {
  const { user, loading, can, sessionEnded } = useAuth();
  const location = useLocation();

  if (loading) return <PageLoader label="Checking your session…" />;
  if (!user) {
    // A visitor who has not been signed in at all sees the public landing page at the root.
    if (landing && !sessionEnded && location.pathname === "/") return <>{landing}</>;
    // "from" brings someone back to a link they opened while signed out. It is not set when a session just ended (sign-out,
    // expiry, lockdown): that page belongs to the previous session, and the next sign-in should open Home.
    return <Navigate to="/login" replace state={sessionEnded ? undefined : { from: location.pathname + location.search }} />;
  }
  if (user.mfa_enrollment_required && location.pathname !== "/security") return <Navigate to="/security" replace />;
  if (permission && !can(permission)) return <Forbidden />;
  return <>{children}</>;
}
