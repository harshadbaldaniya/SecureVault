import { Link } from "react-router-dom";

import { Badge, Card, PageHeader } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";

/**
 * Phase 1 home: the signed-in account and where to go next. It shows only real data.
 * The security dashboard (credential counts, alerts, devices, lockdown) arrives with the modules that produce it.
 */
export function HomePage() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <PageHeader title={`Welcome, ${user.full_name}`} description={`${user.organization.name}${user.department ? ` · ${user.department.name}` : ""}`} />
      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Your account">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Email</dt>
              <dd>{user.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Two-step verification</dt>
              <dd>
                <Badge tone={user.mfa_enabled ? "green" : "amber"}>{user.mfa_enabled ? "On" : "Off"}</Badge>
              </dd>
            </div>
          </dl>
          {!user.mfa_enabled && (
            <p className="mt-4 text-sm">
              <Link to="/security" className="font-medium text-brand-700 hover:underline">
                Turn on two-step verification
              </Link>
            </p>
          )}
        </Card>
        <Card title="Coming next" description="The encrypted vault, sharing, device trust and lockdown are built in the next phases.">
          <p className="text-sm text-slate-600">For now you can manage employees, departments, the service catalog, the security policy and review the audit trail, depending on your role.</p>
        </Card>
      </div>
    </>
  );
}
