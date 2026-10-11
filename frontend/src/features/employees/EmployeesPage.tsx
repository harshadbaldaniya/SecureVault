import { useState } from "react";

import { PageHeader, LinkButton, tabClass, tabListClass } from "@/components/ui";
import { useAuth } from "@/features/authentication/AuthContext";

import { EmployeeDirectory } from "./EmployeeDirectory";
import { InvitationsPanel } from "./InvitationsPanel";

export function EmployeesPage() {
  const { can } = useAuth();
  const canInvite = can("invitations.manage");
  const [tab, setTab] = useState<"employees" | "invitations">("employees");

  return (
    <>
      <PageHeader
        title="Employees"
        description="People in your organization. New employees join through single-use invitations."
        actions={
          canInvite && (
            <LinkButton to="/employees/import">Import from Excel</LinkButton>
          )
        }
      />
      {canInvite && (
        <div role="tablist" aria-label="Employee views" className={tabListClass}>
          {(["employees", "invitations"] as const).map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              id={`tab-${name}`}
              aria-selected={tab === name}
              aria-controls={`panel-${name}`}
              onClick={() => setTab(name)}
              className={tabClass(tab === name)}
            >
              {name === "employees" ? "Directory" : "Invitations"}
            </button>
          ))}
        </div>
      )}
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "employees" || !canInvite ? <EmployeeDirectory /> : <InvitationsPanel />}
      </div>
    </>
  );
}
