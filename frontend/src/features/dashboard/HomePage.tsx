import { useQuery } from "@tanstack/react-query";

import { DocumentIcon } from "@/components/icons";
import { Alert, Badge, Card, PageHeader, PageLoader, Table, LinkButton, TextLink } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";
import { STRENGTH_TEXT } from "@/features/vault/strength";
import { api, ApiError } from "@/services/api";
import type { DailyCount, Dashboard } from "@/types/api";

import { BarChart, ColumnChart, Meter, StatTile, StatusMark } from "./charts";

const weekday = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" });
const toDatums = (days: DailyCount[]) => days.map((d) => ({ label: weekday(d.date), value: d.count }));

export function HomePage() {
  const { user } = useAuth();
  const query = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/dashboard/"), refetchInterval: 60_000 });
  if (!user) return null;

  return (
    <>
      <PageHeader title={`Welcome, ${user.full_name}`} description={`${user.organization.name}${user.department ? ` · ${user.department.name}` : ""}`} />
      {!user.mfa_enabled && (
        <Alert
          tone="info"
          className="mb-4"
          action={
            <LinkButton to="/security" size="sm">
              Turn it on
            </LinkButton>
          }
        >
          Two-step verification is off for your account.
        </Alert>
      )}
      {query.isPending ? (
        <PageLoader />
      ) : query.isError ? (
        <Alert tone="error">{query.error instanceof ApiError ? query.error.message : "Could not load the dashboard."}</Alert>
      ) : (
        <DashboardBody data={query.data} />
      )}
    </>
  );
}

function DashboardBody({ data }: { data: Dashboard }) {
  const { me, organization } = data;
  return (
    <div className="space-y-8">
      <section aria-labelledby="me-heading" className="space-y-4">
        <h2 id="me-heading" className="text-lg font-semibold">
          Your vault
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <StatTile
            label="Your credentials"
            value={me.credentials}
            hint={
              <TextLink to="/vault">Open the vault</TextLink>
            }
          />
          <StatTile label="Shared with you" value={me.shared_with_me} hint={`You share ${me.shares_given} grant${me.shares_given === 1 ? "" : "s"}`} />
          <StatTile label="Waiting for your approval" value={me.requests_to_approve} hint={me.my_pending_requests ? `${me.my_pending_requests} of your requests pending` : undefined} />
          <StatTile label="Expiring soon" value={me.expiring_soon} hint={me.expired ? `${me.expired} already expired` : "None expired"} />
          <StatTile label="Weak or reused" value={me.weak + me.reused} hint={`${me.weak} weak · ${me.reused} reused`} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <ColumnChart title="Your reveals and copies" caption="Last 7 days (UTC)" data={toDatums(me.activity)} valueLabel="Reveals and copies" />
          <BarChart
            title="Strength of your credentials"
            caption="Estimated entropy; an estimate, not a guarantee"
            data={me.strength.map((s) => ({ label: STRENGTH_TEXT[s.label], value: s.count }))}
            valueLabel="Credentials"
          />
        </div>
      </section>

      {organization && (
        <section aria-labelledby="org-heading" className="space-y-4">
          <h2 id="org-heading" className="text-lg font-semibold">
            Organization security
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Credentials in the vault" value={organization.credentials} />
            <StatTile label="Active share grants" value={organization.active_shares} />
            <StatTile label="Pending access requests" value={organization.pending_requests} />
            <StatTile label="Lockdown" value={organization.active_lockdowns.length ? "Active" : "None"}>
              <div className="mt-2">
                {organization.active_lockdowns.length ? <StatusMark level="critical" label={`${organization.active_lockdowns.length} active`} /> : <StatusMark level="good" label="Normal operation" />}
              </div>
            </StatTile>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Open security alerts">
              <ul className="space-y-2">
                <li>
                  <StatusMark level="critical" label={`${organization.open_alerts.HIGH} high`} />
                </li>
                <li>
                  <StatusMark level="serious" label={`${organization.open_alerts.MEDIUM} medium`} />
                </li>
                <li>
                  <StatusMark level="warning" label={`${organization.open_alerts.LOW} low`} />
                </li>
              </ul>
              <LinkButton to="/alerts" size="sm" className="mt-4">
                Review alerts
              </LinkButton>
            </Card>
            <Card title="Device posture">
              <Meter
                label="Trusted devices"
                value={organization.devices.trusted}
                total={organization.devices.trusted + organization.devices.pending + organization.devices.suspended}
                unit="devices"
              />
              <p className="mt-3 text-xs text-slate-500">
                {organization.devices.pending} pending approval · {organization.devices.suspended} suspended
              </p>
            </Card>
            <ColumnChart title="Reveals and copies, organization" caption="Last 7 days (UTC)" data={toDatums(organization.activity)} valueLabel="Reveals and copies" />
          </div>
          <Card title="Recent security events" description="Failures, denials, lockdowns, device-trust and policy changes.">
            {organization.recent_security_events.length === 0 ? (
              <p className="text-sm text-slate-500">Nothing to report.</p>
            ) : (
              <Table caption="Recent security events" headers={["When", "Event", "Outcome", "Who", "What"]}>
                {organization.recent_security_events.map((e, i) => (
                  <tr key={`${e.created_at}-${i}`}>
                    <td className="whitespace-nowrap px-4 py-2">{new Date(e.created_at).toLocaleString()}</td>
                    <td className="px-4 py-2 font-mono text-xs">{e.action}</td>
                    <td className="px-4 py-2">
                      <Badge tone={e.outcome === "SUCCESS" ? "green" : e.outcome === "DENIED" ? "amber" : "red"}>{e.outcome.toLowerCase()}</Badge>
                    </td>
                    <td className="px-4 py-2">{e.actor_email || "system"}</td>
                    <td className="px-4 py-2">{e.target_label || e.reason || "—"}</td>
                  </tr>
                ))}
              </Table>
            )}
            <LinkButton to="/audit" size="sm" className="mt-4">
              <DocumentIcon />
              Open the audit log
            </LinkButton>
          </Card>
        </section>
      )}
    </div>
  );
}
