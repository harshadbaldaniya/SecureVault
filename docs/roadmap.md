# Roadmap

Prioritized improvements beyond the MVP. The order follows risk: first what must happen before holding real secrets, then what
makes it a better product. Items map to [known-limitations.md](known-limitations.md).

## P0: before any real use

1. **Independent security review and penetration test**, with the threat model and test report as inputs. Fix findings before launch.
2. **KMS/HSM-backed `KeyProvider`** (cloud KMS or Vault transit): keys never in the container environment; envelope operations audited
   by the KMS. Document and rehearse key-loss and rotation procedures.
3. **Anchor the audit chain externally**: periodically publish the head hash (a signed object in write-once storage, or a transparency
   log) so a full-table rewrite is detectable.
4. **Managed or replicated PostgreSQL and Redis**, automated encrypted off-host backups with scheduled restore tests, and a documented
   recovery objective.
5. **Run it on a real host**: CA certificate, firewall, log shipping and alerts on the metrics and audit events already exposed;
   schedule the purge and expiry jobs.
6. **Multi-replica test**: two or more backend containers behind nginx, with the same smoke, load and lockdown checks.

## P1: product and assurance

7. **SSO** (OIDC first, then SAML) and **SCIM** provisioning, so people are not invited one by one.
8. **WebAuthn/passkeys** as a second factor, alongside TOTP.
9. **Idempotency keys** for create operations; **session list and "sign out other devices"** in the UI.
10. **Password-breach checking** (k-anonymity range queries) and rotation reminders/automation for stored credentials.
11. **Accessibility audit** (axe in CI, screen-reader pass) and **Firefox/Safari** in the end-to-end suite; add TOTP, device-approval
    and report flows to it.
12. **Real SMTP integration test** (a local relay in CI) and delivery-failure surfacing in the UI (which invitations were not delivered).
13. **Anomaly detection v2**: IP reputation/geo-velocity, per-user baselines, tunable thresholds, clear explanations. Keep it explainable.
14. **Credential list query** rewritten for very large organizations; revisit the plans in `explain_hot_queries.py` as data grows.

## P2: later, only with a concrete need

15. Browser extension and mobile apps (autofill, capture).
16. Break-glass and approval workflows (two-person rule) for the most sensitive credentials.
17. Retention and erasure policy for the audit trail (hash-chain-compatible: tombstoning with checkpoints).
18. Kubernetes manifests or a Helm chart, only if the single-host Compose deployment stops being enough. Microservices are not on
    this list: nothing measured so far justifies them.
