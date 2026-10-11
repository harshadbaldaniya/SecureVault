// Typed API contracts. These mirror the Django serializers (see /api/v1/docs/).

export type Role = "ORG_ADMIN" | "SEC_ADMIN" | "EMPLOYEE";
export type UserStatus = "INVITED" | "ACTIVE" | "SUSPENDED" | "DEACTIVATED";

/** Permission strings are for showing/hiding UI only; the server re-checks every request. */
export type Permission =
  | "users.view"
  | "users.manage"
  | "invitations.manage"
  | "departments.manage"
  | "services.manage"
  | "policies.manage"
  | "audit.view";

export interface Me {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  status: UserStatus;
  organization: { id: string; name: string; slug: string };
  department: { id: string; name: string; code: string } | null;
  permissions: Permission[];
  mfa_enabled: boolean;
  mfa_enrollment_required: boolean;
}

export interface LoginResult {
  mfa_required: boolean;
  user: Me | null;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Department {
  id: string;
  name: string;
  code: string;
  head: string | null;
  head_name: string | null;
  status: "ACTIVE" | "ARCHIVED";
  employee_count: number;
}

export interface Employee {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  status: UserStatus;
  department: string | null;
  department_name: string | null;
  last_login: string | null;
  created_at: string;
}

export type InvitationState = "PENDING" | "ACCEPTED" | "REVOKED" | "EXPIRED";

export interface Invitation {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  state: InvitationState;
  invited_by_name: string | null;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
  /** Present only in the create/resend response. Shown once, never stored. */
  invite_url?: string;
}

export type ServiceCategory = "CLOUD" | "DATABASE" | "DEVOPS" | "SAAS" | "INTERNAL" | "OTHER";

export interface ServiceItem {
  id: string;
  name: string;
  category: ServiceCategory;
  base_url: string;
  icon_url: string;
  default_port: number | null;
  status: "ACTIVE" | "INACTIVE";
}

export interface SecurityPolicy {
  id: string;
  name: string;
  min_password_length: number;
  require_uppercase: boolean;
  require_numbers: boolean;
  require_symbols: boolean;
  max_password_age_days: number;
  expiry_warning_days: number;
  allow_view_once: boolean;
  max_share_duration_days: number;
  require_device_trust: boolean;
  require_mfa: boolean;
  updated_at: string;
}

export interface AuditEntry {
  id: number;
  sequence: number;
  created_at: string;
  action: string;
  outcome: "SUCCESS" | "FAILURE" | "DENIED";
  actor_id: string | null;
  actor_email: string;
  target_type: string;
  target_id: string;
  target_label: string;
  reason: string;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  request_id: string;
}

export interface ChainVerification {
  chain: string;
  valid: boolean;
  checked: number;
  broken_at_sequence: number | null;
}

export type SecretType = "PASSWORD" | "API_KEY" | "OTHER";
export type VaultPermission = "VIEW" | "REVEAL" | "COPY" | "EDIT" | "DELETE" | "SHARE";
export type StrengthLevel = "very_weak" | "weak" | "fair" | "strong" | "very_strong";

/** Metadata only: the secret is never part of a read response. */
export interface Credential {
  id: string;
  title: string;
  username: string;
  service: string | null;
  service_name: string | null;
  secret_type: SecretType;
  category: string;
  tags: string[];
  expires_at: string | null;
  entropy_bits: number;
  strength: StrengthLevel;
  is_expired: boolean;
  expires_soon: boolean;
  password_age_days: number;
  reuse_count: number;
  owner_name: string;
  permissions: VaultPermission[];
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  password_changed_at: string;
}

export interface SecureNote {
  id: string;
  title: string;
  category: string;
  tags: string[];
  expires_at: string | null;
  owner_name: string;
  permissions: VaultPermission[];
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
}
