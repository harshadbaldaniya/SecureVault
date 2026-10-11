/**
 * Audit action names, in the backend's order. Kept in step with apps/audit/models.AuditAction through
 * shared/audit-actions.json (checked by a backend test and a frontend test).
 */
export const AUDIT_ACTIONS = [
  "LOGIN",
  "LOGOUT",
  "REVEAL",
  "COPY",
  "CREATE",
  "EDIT",
  "DELETE",
  "SHARE",
  "REVOKE",
  "INVITE",
  "ACCOUNT_ACTIVATE",
  "KEY_ROTATION",
  "ANOMALY_REVIEW",
  "REPORT_EXPORT",
  "MFA_ENROLL",
  "MFA_DISABLE",
  "MFA_RESET",
  "PASSWORD_CHANGE",
  "PASSWORD_RESET_REQUEST",
  "PASSWORD_RESET",
  "ACCESS_REQUEST",
  "APPROVAL",
  "REJECTION",
  "DEVICE_TRUST_CHANGE",
  "LOCKDOWN",
  "EMPLOYEE_IMPORT",
  "POLICY_CHANGE",
] as const;
