import type { InvitationState, Role, UserStatus } from "@/types/api";

export const ROLE_LABEL: Record<Role, string> = {
  ORG_ADMIN: "Organization Administrator",
  SEC_ADMIN: "Security Administrator",
  EMPLOYEE: "Employee",
};

export const STATUS_LABEL: Record<UserStatus, string> = {
  INVITED: "Invited",
  ACTIVE: "Active",
  SUSPENDED: "Suspended",
  DEACTIVATED: "Deactivated",
};

export const STATUS_TONE: Record<UserStatus, "green" | "amber" | "red" | "slate"> = {
  INVITED: "slate",
  ACTIVE: "green",
  SUSPENDED: "amber",
  DEACTIVATED: "red",
};

export const INVITATION_LABEL: Record<InvitationState, string> = {
  PENDING: "Pending",
  ACCEPTED: "Accepted",
  REVOKED: "Revoked",
  EXPIRED: "Expired",
};

export const INVITATION_TONE: Record<InvitationState, "green" | "amber" | "red" | "slate" | "blue"> = {
  PENDING: "blue",
  ACCEPTED: "green",
  REVOKED: "red",
  EXPIRED: "slate",
};
