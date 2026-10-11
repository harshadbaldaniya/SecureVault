# API documentation

The API is versioned under `/api/v1/` and speaks JSON only. The authoritative, machine-readable description is
[openapi.yaml](openapi.yaml) (generated from the code; a test fails if it is stale). In development, Swagger UI is served at
`/api/v1/docs/` after you sign in; in production it is off by default (`SV_ENABLE_API_DOCS`).

## Conventions

**Authentication.** Cookie sessions. `POST /auth/login/` sets the HttpOnly `sv_session` cookie. Unsafe methods (POST, PATCH, DELETE)
also need the CSRF token: call `GET /auth/csrf/` once, read the `sv_csrftoken` cookie, and send its value in the `X-CSRFToken`
header with an `Origin` header that matches the site. There are no API tokens or JWTs.

**Errors** always use one envelope:

```json
{"error": {"code": "permission_denied", "message": "You do not have permission to do this."}}
```

| Status | Meaning |
|---|---|
| 400 | Invalid input (`details` maps field names to messages) or a business rule (`code` says which) |
| 401 | Not signed in / session ended |
| 403 | Signed in but not allowed (also CSRF failure, MFA enrolment required) |
| 404 | Not found, **or** belongs to another organization (indistinguishable on purpose) |
| 409 | Conflict with existing data (e.g. already shared) |
| 410 | A view-once share has already been used |
| 423 | Emergency lockdown is active for this user |
| 429 | Rate limit; `Retry-After` is set |
| 503 | A dependency (database, Redis) is unavailable; `Retry-After: 5`. Credential endpoints return it when their rate-limit store is down. |

Error messages never contain stack traces, SQL, host names or secret values.

**Pagination.** List endpoints return `{"count", "next", "previous", "results"}` with `page` and `page_size` (default 25, max 100).
Filtering and ordering use query parameters documented per endpoint in the OpenAPI file.

**Secrets are write-only.** No read endpoint returns a secret. The only way to obtain one is `POST .../reveal/`, which is
authorized, rate-limited (30 per minute per user), audited, and answered with `Cache-Control: no-store`.

**Idempotency.** There is no `Idempotency-Key` header. Retry safety comes from natural uniqueness: a repeated share, access
request or invitation acceptance is rejected as a duplicate rather than repeated; single-use tokens and TOTP codes cannot be
replayed. A retried *create credential* call does create a second credential.

**Operational endpoints** (not part of the application API): `GET /health/` (public, dependency status only) and
`GET /metrics/` (Prometheus format, off unless `SV_METRICS_TOKEN` is set, bearer-token protected, never routed by nginx).

## Endpoint catalogue

Generated from [openapi.yaml](openapi.yaml). Which endpoints a person may call depends on their role and on the resource;
the OpenAPI file and the permission matrix in `backend/core/permissions.py` are authoritative.

| Area | Method | Path | Summary |
|---|---|---|---|
| access-requests | GET | `/access-requests/` | access_requests_list |
| access-requests | POST | `/access-requests/` | access_requests_create |
| access-requests | GET | `/access-requests/{id}/` | access_requests_retrieve |
| access-requests | POST | `/access-requests/{id}/approve/` | access_requests_approve_create |
| access-requests | POST | `/access-requests/{id}/cancel/` | access_requests_cancel_create |
| access-requests | POST | `/access-requests/{id}/reject/` | access_requests_reject_create |
| alerts | GET | `/alerts/` | alerts_list |
| alerts | GET | `/alerts/{id}/` | alerts_retrieve |
| alerts | POST | `/alerts/{id}/acknowledge/` | alerts_acknowledge_create |
| alerts | POST | `/alerts/{id}/dismiss/` | alerts_dismiss_create |
| audit-logs | GET | `/audit-logs/` | audit_logs_list |
| audit-logs | GET | `/audit-logs/verify/` | audit_logs_verify_retrieve |
| audit-logs | GET | `/audit-logs/{id}/` | audit_logs_retrieve |
| auth | GET | `/auth/csrf/` | auth_csrf_retrieve |
| auth | POST | `/auth/invitations/accept/` | auth_invitations_accept_create |
| auth | POST | `/auth/login/` | auth_login_create |
| auth | POST | `/auth/logout/` | auth_logout_create |
| auth | GET | `/auth/me/` | auth_me_retrieve |
| auth | POST | `/auth/mfa/recovery-codes/` | auth_mfa_recovery_codes_create |
| auth | POST | `/auth/mfa/totp/confirm/` | auth_mfa_totp_confirm_create |
| auth | POST | `/auth/mfa/totp/disable/` | auth_mfa_totp_disable_create |
| auth | POST | `/auth/mfa/totp/setup/` | auth_mfa_totp_setup_create |
| auth | POST | `/auth/mfa/verify/` | auth_mfa_verify_create |
| auth | POST | `/auth/password-reset/` | auth_password_reset_create |
| auth | POST | `/auth/password-reset/confirm/` | auth_password_reset_confirm_create |
| auth | POST | `/auth/password/change/` | auth_password_change_create |
| dashboard | GET | `/dashboard/` | dashboard_retrieve |
| departments | GET | `/departments/` | departments_list |
| departments | POST | `/departments/` | departments_create |
| departments | DELETE | `/departments/{id}/` | departments_destroy |
| departments | GET | `/departments/{id}/` | departments_retrieve |
| departments | PATCH | `/departments/{id}/` | departments_partial_update |
| departments | PUT | `/departments/{id}/` | departments_update |
| devices | GET | `/devices/` | devices_list |
| devices | GET | `/devices/current/` | devices_current_retrieve |
| devices | POST | `/devices/register/` | devices_register_create |
| devices | GET | `/devices/{id}/` | devices_retrieve |
| devices | PATCH | `/devices/{id}/` | devices_partial_update |
| devices | POST | `/devices/{id}/approve/` | devices_approve_create |
| devices | GET | `/devices/{id}/events/` | devices_events_list |
| devices | POST | `/devices/{id}/revoke/` | devices_revoke_create |
| devices | POST | `/devices/{id}/suspend/` | devices_suspend_create |
| health | GET | `/health/` | health_retrieve |
| imports | GET | `/imports/` | imports_list |
| imports | POST | `/imports/` | imports_create |
| imports | GET | `/imports/template/` | imports_template_retrieve |
| imports | GET | `/imports/{id}/` | imports_retrieve |
| imports | POST | `/imports/{id}/retry/` | imports_retry_create |
| invitations | GET | `/invitations/` | invitations_list |
| invitations | POST | `/invitations/` | invitations_create |
| invitations | GET | `/invitations/{id}/` | invitations_retrieve |
| invitations | POST | `/invitations/{id}/resend/` | invitations_resend_create |
| invitations | POST | `/invitations/{id}/revoke/` | invitations_revoke_create |
| lockdown | GET | `/lockdown/` | lockdown_list |
| lockdown | POST | `/lockdown/activate/` | lockdown_activate_create |
| lockdown | GET | `/lockdown/status/` | lockdown_status_list |
| lockdown | GET | `/lockdown/{id}/` | lockdown_retrieve |
| lockdown | POST | `/lockdown/{id}/resolve/` | lockdown_resolve_create |
| notifications | GET | `/notifications/` | notifications_list |
| notifications | POST | `/notifications/read-all/` | notifications_read_all_create |
| notifications | GET | `/notifications/unread-count/` | notifications_unread_count_retrieve |
| notifications | POST | `/notifications/{id}/read/` | notifications_read_create |
| people | GET | `/people/` | people_list |
| policy | GET | `/policy/` | policy_retrieve |
| policy | PATCH | `/policy/` | policy_partial_update |
| reports | GET | `/reports/` | reports_catalog |
| reports | POST | `/reports/custom/` | reports_custom_create |
| reports | GET | `/reports/{key}/` | reports_run |
| services | GET | `/services/` | services_list |
| services | POST | `/services/` | services_create |
| services | DELETE | `/services/{id}/` | services_destroy |
| services | GET | `/services/{id}/` | services_retrieve |
| services | PATCH | `/services/{id}/` | services_partial_update |
| services | PUT | `/services/{id}/` | services_update |
| shares | GET | `/shares/` | shares_list |
| shares | GET | `/shares/tree/{credential_id}/` | shares_tree_retrieve |
| shares | GET | `/shares/{id}/` | shares_retrieve |
| shares | POST | `/shares/{id}/revoke/` | shares_revoke_create |
| users | GET | `/users/` | users_list |
| users | GET | `/users/{id}/` | users_retrieve |
| users | PATCH | `/users/{id}/` | users_partial_update |
| users | POST | `/users/{id}/password-reset-link/` | users_password_reset_link_create |
| users | POST | `/users/{id}/reset-mfa/` | users_reset_mfa_create |
| vault | GET | `/vault/credentials/` | vault_credentials_list |
| vault | POST | `/vault/credentials/` | vault_credentials_create |
| vault | DELETE | `/vault/credentials/{id}/` | vault_credentials_destroy |
| vault | GET | `/vault/credentials/{id}/` | vault_credentials_retrieve |
| vault | PATCH | `/vault/credentials/{id}/` | vault_credentials_partial_update |
| vault | POST | `/vault/credentials/{id}/restore/` | vault_credentials_restore_create |
| vault | POST | `/vault/credentials/{id}/reveal/` | vault_credentials_reveal_create |
| vault | POST | `/vault/credentials/{id}/share/` | vault_credentials_share_create |
| vault | GET | `/vault/directory/` | vault_directory_list |
| vault | GET | `/vault/notes/` | vault_notes_list |
| vault | POST | `/vault/notes/` | vault_notes_create |
| vault | DELETE | `/vault/notes/{id}/` | vault_notes_destroy |
| vault | GET | `/vault/notes/{id}/` | vault_notes_retrieve |
| vault | PATCH | `/vault/notes/{id}/` | vault_notes_partial_update |
| vault | POST | `/vault/notes/{id}/restore/` | vault_notes_restore_create |
| vault | POST | `/vault/notes/{id}/reveal/` | vault_notes_reveal_create |
